/* Export the trained last-block MLP into its original GGUF. */
#define _POSIX_C_SOURCE 200809L
#include "gguf.h"

#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static uint64_t align32(uint64_t n) { return (n + 31) & ~UINT64_C(31); }
static int put(FILE *f, const void *p, size_t n) { return fwrite(p, 1, n, f) == n ? 0 : -1; }
static int copy(FILE *in, FILE *out, uint64_t start, uint64_t length) {
    unsigned char buffer[65536];
    if (fseeko(in, (off_t)start, SEEK_SET)) return -1;
    while (length) {
        size_t n = length < sizeof(buffer) ? (size_t)length : sizeof(buffer);
        if (fread(buffer, 1, n, in) != n || put(out, buffer, n)) return -1;
        length -= n;
    }
    return 0;
}
static int padding(FILE *f) {
    static const char zero[32] = {0};
    off_t pos = ftello(f);
    return pos < 0 ? -1 : put(f, zero, (size_t)(-(uint64_t)pos & 31));
}
static int floats(FILE *in, FILE *out, uint64_t elements) {
    float buffer[16384];
    while (elements) {
        size_t n = elements < 16384 ? (size_t)elements : 16384;
        if (fread(buffer, sizeof(float), n, in) != n) return -1;
        for (size_t i = 0; i < n; i++) if (!isfinite(buffer[i])) {
            fprintf(stderr, "jovovich: replacement contains non-finite float32 weights\n");
            return -1;
        }
        if (put(out, buffer, n * sizeof(float))) return -1;
        elements -= n;
    }
    return 0;
}

/* Locate directory fields without reserializing names, shapes, or metadata. */
static int fields(FILE *source, const gguf_file *gf, uint64_t *positions) {
    if (fseeko(source, (off_t)gf->kv_end, SEEK_SET)) return -1;
    for (uint64_t i = 0; i < gf->n_tensors; i++) {
        uint64_t length;
        uint32_t ndim;
        off_t pos = ftello(source);
        if (pos < 0 || (uint64_t)pos > gf->data_offset ||
            gf->data_offset - (uint64_t)pos < 8 || fread(&length, 8, 1, source) != 1 ||
            length > gf->data_offset - (uint64_t)pos - 8 ||
            fseeko(source, (off_t)length, SEEK_CUR) || fread(&ndim, 4, 1, source) != 1 ||
            ndim < 1 || ndim > 4 || ndim != gf->tensors[i].ndim ||
            fseeko(source, (off_t)ndim * 8, SEEK_CUR)) return -1;
        pos = ftello(source);
        if (pos < 0 || (uint64_t)pos > gf->data_offset ||
            gf->data_offset - (uint64_t)pos < 12) return -1;
        positions[i] = (uint64_t)pos;
        if (fseeko(source, 12, SEEK_CUR)) return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s base.gguf prefix jovovich.gguf\n"
                        "  reads prefix.gate.f32, prefix.up.f32, prefix.down.f32\n", argv[0]);
        return 2;
    }
    uint32_t endian = 1;
    if (*(unsigned char *)&endian != 1 || sizeof(float) != 4) {
        fprintf(stderr, "jovovich: GGUF export requires little-endian float32\n");
        return 1;
    }
    int result = 1, created = 0;
    FILE *source = NULL, *replacement[3] = {NULL, NULL, NULL}, *out = NULL;
    uint64_t *offsets = NULL, *positions = NULL;
    gguf_file *gf = gguf_open(argv[1]);
    if (!gf) goto done;
    if (strcmp(gf->arch, "qwen2") && strcmp(gf->arch, "qwen3")) {
        fprintf(stderr, "jovovich: MLP export requires dense qwen2 or qwen3\n");
        goto done;
    }
    uint64_t alignment;
    if (gguf_get_kv(gf, "general.alignment") &&
        (gguf_read_uint_kv(argv[1], "general.alignment", &alignment) || alignment != 32)) {
        fprintf(stderr, "jovovich: unsupported GGUF alignment\n");
        goto done;
    }
    if (gf->n_layers <= 0 || gf->embed_dim <= 0 || gf->ffn_dim <= 0) goto done;
    uint64_t width = (uint64_t)gf->embed_dim, hidden = (uint64_t)gf->ffn_dim;
    if (width > UINT64_MAX / hidden / sizeof(float)) goto done;
    uint64_t elements = width * hidden, replacement_bytes = elements * sizeof(float);
    const char *parts[] = {"gate", "up", "down"};
    int indices[3];
    for (int p = 0; p < 3; p++) {
        char name[128];
        snprintf(name, sizeof(name), "blk.%d.ffn_%s.weight", gf->n_layers - 1, parts[p]);
        indices[p] = gguf_find_tensor(gf, name);
        if (indices[p] < 0) {
            fprintf(stderr, "jovovich: missing last-block tensor %s\n", name);
            goto done;
        }
        const gguf_tensor_info *t = &gf->tensors[indices[p]];
        if (t->ndim != 2 || t->shape[0] != (p == 2 ? hidden : width) ||
            t->shape[1] != (p == 2 ? width : hidden)) {
            fprintf(stderr, "jovovich: %s shape disagrees with embedding/FFN dimensions\n", name);
            goto done;
        }
        for (uint64_t i = (uint64_t)indices[p] + 1; i < gf->n_tensors; i++)
            if (!strcmp(gf->tensors[i].name, name)) goto done;
        size_t size = strlen(argv[2]) + strlen(parts[p]) + 6;
        char *file = malloc(size);
        if (!file) goto done;
        snprintf(file, size, "%s.%s.f32", argv[2], parts[p]);
        replacement[p] = fopen(file, "rb");
        free(file);
        struct stat st;
        if (!replacement[p] || fstat(fileno(replacement[p]), &st) ||
            !S_ISREG(st.st_mode) || st.st_size < 0 || (uint64_t)st.st_size != replacement_bytes) {
            fprintf(stderr, "jovovich: expected %llu bytes in prefix.%s.f32\n",
                    (unsigned long long)replacement_bytes, parts[p]);
            goto done;
        }
    }
    source = fopen(argv[1], "rb");
    struct stat st;
    if (!source || fstat(fileno(source), &st) || st.st_size < 0 ||
        !S_ISREG(st.st_mode) || gf->data_offset > (uint64_t)st.st_size) goto done;
    uint64_t source_bytes = (uint64_t)st.st_size - gf->data_offset;
    offsets = calloc((size_t)gf->n_tensors, sizeof(*offsets));
    positions = calloc((size_t)gf->n_tensors, sizeof(*positions));
    if (!offsets || !positions || fields(source, gf, positions)) goto done;
    uint64_t cursor = 0;
    for (uint64_t i = 0; i < gf->n_tensors; i++) {
        const gguf_tensor_info *t = &gf->tensors[i];
        uint64_t n = 1;
        if (t->ndim < 1 || t->ndim > 4) goto done;
        for (uint32_t d = 0; d < t->ndim; d++) {
            if (!t->shape[d] || n > UINT64_MAX / t->shape[d]) goto done;
            n *= t->shape[d];
        }
        uint64_t bytes = gguf_type_size(t->dtype, n);
        if (!bytes || t->offset > source_bytes || bytes > source_bytes - t->offset) goto done;
        if (i == (uint64_t)indices[0] || i == (uint64_t)indices[1] || i == (uint64_t)indices[2])
            bytes = replacement_bytes;
        offsets[i] = cursor;
        if (bytes > UINT64_MAX - 31 || cursor > UINT64_MAX - bytes - 31) goto done;
        cursor = align32(cursor + bytes);
    }
    int fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (fd < 0) { perror("jovovich: create export"); goto done; }
    created = 1;
    out = fdopen(fd, "wb");
    if (!out) { close(fd); goto done; }
    if (copy(source, out, 0, gf->data_offset)) goto done;
    for (uint64_t i = 0; i < gf->n_tensors; i++) {
        uint32_t type = gf->tensors[i].dtype;
        if (i == (uint64_t)indices[0] || i == (uint64_t)indices[1] || i == (uint64_t)indices[2])
            type = GGUF_TYPE_F32;
        if (fseeko(out, (off_t)positions[i], SEEK_SET) || put(out, &type, 4) ||
            put(out, &offsets[i], 8)) goto done;
    }
    if (fseeko(out, (off_t)gf->data_offset, SEEK_SET)) goto done;
    for (uint64_t i = 0; i < gf->n_tensors; i++) {
        int part = -1;
        for (int p = 0; p < 3; p++) if (i == (uint64_t)indices[p]) part = p;
        if (part >= 0) {
            if (floats(replacement[part], out, elements)) goto done;
        } else {
            const gguf_tensor_info *t = &gf->tensors[i];
            if (copy(source, out, gf->data_offset + t->offset,
                     gguf_type_size(t->dtype, t->n_elements))) goto done;
        }
        if (padding(out)) goto done;
    }
    if (fclose(out)) { out = NULL; goto done; }
    out = NULL;
    fprintf(stderr, "jovovich: replaced block %d gate/up/down with float32; other tensors and metadata preserved\n",
            gf->n_layers - 1);
    result = 0;
done:
    if (out) fclose(out);
    if (source) fclose(source);
    for (int p = 0; p < 3; p++) if (replacement[p]) fclose(replacement[p]);
    if (gf) gguf_close(gf);
    free(offsets);
    free(positions);
    if (result && created) unlink(argv[3]);
    if (result) fprintf(stderr, "jovovich: MLP export failed\n");
    return result;
}
