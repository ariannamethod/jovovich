/* Put a trained head into its original GGUF. Preserve tokenizer and body bytes. */
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
static int u32(FILE *f, uint32_t n) { return put(f, &n, 4); }
static int u64(FILE *f, uint64_t n) { return put(f, &n, 8); }
static int string(FILE *f, const char *s) {
    size_t n = strlen(s);
    return u64(f, n) || put(f, s, n) ? -1 : 0;
}
static int padding(FILE *f) {
    static const char zero[32] = {0};
    off_t p = ftello(f);
    return p < 0 ? -1 : put(f, zero, (size_t)(-(uint64_t)p & 31));
}
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
static int head_copy(FILE *in, FILE *out, uint64_t elements) {
    float buffer[16384];
    while (elements) {
        size_t n = elements < 16384 ? (size_t)elements : 16384;
        if (fread(buffer, sizeof(float), n, in) != n) return -1;
        for (size_t i = 0; i < n; i++) if (!isfinite(buffer[i])) return -1;
        if (put(out, buffer, n * sizeof(float))) return -1;
        elements -= n;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s base.gguf output-head.f32 jovovich.gguf\n", argv[0]);
        return 2;
    }
    uint32_t endian = 1;
    if (*(unsigned char *)&endian != 1 || sizeof(float) != 4) {
        fprintf(stderr, "jovovich: GGUF export requires little-endian float32\n");
        return 1;
    }
    int result = 1, created = 0;
    FILE *source = NULL, *head = NULL, *out = NULL;
    gguf_file *gf = gguf_open(argv[1]);
    uint64_t *offsets = NULL;
    if (!gf) goto done;
    if (strcmp(gf->arch, "qwen2")) {
        fprintf(stderr, "jovovich: this head belongs to a qwen2 body\n");
        goto done;
    }
    uint64_t alignment;
    if (gguf_get_kv(gf, "general.alignment") &&
        (gguf_read_uint_kv(argv[1], "general.alignment", &alignment) || alignment != 32)) {
        fprintf(stderr, "jovovich: unsupported GGUF alignment\n");
        goto done;
    }
    int emb = gguf_find_tensor(gf, "token_embd.weight");
    if (emb < 0 || gf->tensors[emb].ndim != 2) goto done;
    uint64_t width = gf->tensors[emb].shape[0], vocab = gf->tensors[emb].shape[1];
    if (!width || !vocab || width > UINT64_MAX / vocab / 4) goto done;
    uint64_t head_bytes = width * vocab * 4;
    int old_head = gguf_find_tensor(gf, "output.weight");
    if (old_head >= 0 && (gf->tensors[old_head].ndim != 2 ||
        gf->tensors[old_head].shape[0] != width || gf->tensors[old_head].shape[1] != vocab)) {
        fprintf(stderr, "jovovich: output head shape disagrees with token embeddings\n");
        goto done;
    }
    uint64_t count = gf->n_tensors + (old_head < 0);
    if (count > GGUF_MAX_TENSORS) goto done;
    uint64_t head_index = old_head < 0 ? gf->n_tensors : (uint64_t)old_head;
    head = fopen(argv[2], "rb");
    source = fopen(argv[1], "rb");
    struct stat st;
    if (!head || !source || fstat(fileno(head), &st) ||
        !S_ISREG(st.st_mode) || st.st_size < 0 || (uint64_t)st.st_size != head_bytes) {
        fprintf(stderr, "jovovich: expected %llu bytes of float32 head weights\n",
                (unsigned long long)head_bytes);
        goto done;
    }
    offsets = calloc((size_t)count, sizeof(*offsets));
    if (!offsets) goto done;
    uint64_t cursor = 0;
    for (uint64_t i = 0; i < count; i++) {
        offsets[i] = cursor;
        uint64_t bytes = head_bytes;
        if (i != head_index) {
            gguf_tensor_info *t = &gf->tensors[i];
            bytes = gguf_type_size(t->dtype, t->n_elements);
            if (!bytes || t->offset > gf->data_size || bytes > gf->data_size - t->offset)
                goto done;
        }
        if (cursor > UINT64_MAX - bytes - 31) goto done;
        cursor = align32(cursor + bytes);
    }
    int fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (fd < 0) { perror("jovovich: create export"); goto done; }
    created = 1;
    out = fdopen(fd, "wb");
    if (!out) { close(fd); goto done; }
    if (u32(out, GGUF_MAGIC) || u32(out, gf->version) || u64(out, count) ||
        u64(out, gf->n_kv) || copy(source, out, 24, gf->kv_end - 24)) goto done;
    for (uint64_t i = 0; i < count; i++) {
        if (i == head_index) {
            if (string(out, "output.weight") || u32(out, 2) || u64(out, width) ||
                u64(out, vocab) || u32(out, GGUF_TYPE_F32) || u64(out, offsets[i])) goto done;
        } else {
            gguf_tensor_info *t = &gf->tensors[i];
            if (string(out, t->name) || u32(out, t->ndim)) goto done;
            for (uint32_t d = 0; d < t->ndim; d++) if (u64(out, t->shape[d])) goto done;
            if (u32(out, t->dtype) || u64(out, offsets[i])) goto done;
        }
    }
    if (padding(out)) goto done;
    for (uint64_t i = 0; i < count; i++) {
        if (i == head_index) {
            if (head_copy(head, out, width * vocab)) goto done;
        } else {
            gguf_tensor_info *t = &gf->tensors[i];
            if (copy(source, out, gf->data_offset + t->offset,
                     gguf_type_size(t->dtype, t->n_elements))) goto done;
        }
        if (padding(out)) goto done;
    }
    if (fclose(out)) { out = NULL; goto done; }
    out = NULL;
    fprintf(stderr, "jovovich: %s a %llu x %llu float32 head; body and metadata preserved\n",
            old_head < 0 ? "appended" : "replaced", (unsigned long long)vocab,
            (unsigned long long)width);
    result = 0;
done:
    if (out) fclose(out);
    if (source) fclose(source);
    if (head) fclose(head);
    if (gf) gguf_close(gf);
    free(offsets);
    if (result && created) unlink(argv[3]);
    if (result) fprintf(stderr, "jovovich: head export failed\n");
    return result;
}
