/* Fixture for the per-layer readout: a tiny qwen2 body with a separable
 * direction planted at one known depth, built with the repository's own GGUF
 * writer and the real tokenizer so the frozen extractor's prefix guard and
 * tokenization path are the ones under test.
 *
 * Mechanism. Every block is inert (all projections zero, norm weights one), so
 * the residual at the decision position is the embedding of the shared final
 * prefix token and is identical for all 52 rows. The planted block alone reads
 * coordinate 0 through attention — scores are zero, so the pattern is the
 * uniform causal mean — and writes it into coordinate 1. Coordinate 0 of an
 * embedding is one exactly for the marker tokens, which appear only in the rows
 * the metadata labels concern. Depths below the plant are therefore exactly
 * constant; the plant and every depth above it carry the direction, because a
 * residual stream cannot forget. The invariant under test is the onset depth.
 *
 * Usage: build-layer-fixture REAL.gguf METADATA.txt OUTPUT_DIR PLANT_LAYER
 *        PLANT_LAYER -1 plants nothing: the null body.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gguf.h"
#include "examples/bpe.h"

/* Width 64 rather than 8: a planted direction with one or two companions leaves
 * the permuted-label fits on a flat ridge, and the declared gradient gate reads
 * that as a failed run. Twelve label-independent companion columns put the
 * fixture's conditioning in the same regime as the published 896-column fit. */
enum { FIX_E = 64, FIX_HEADS = 4, FIX_KV_HEADS = 4, FIX_FFN = 128, FIX_LAYERS = 4, FIX_CTX = 512,
       FIX_FILLER_MAX = 7,
       FIX_MARKER_IN = 0, FIX_MARKER_OUT = 1,   /* the planted label direction */
       FIX_DIGIT_IN = 2, FIX_DIGIT_OUT = 12,    /* ten row-digit companions */
       FIX_FILLER_IN = 22, FIX_FILLER_OUT = 23 };
#define FIX_MARKER " zzqqz"
#define FIX_FILLER "y"
#define FIX_SYSTEM "fixture"
#define FIX_PLANT_SCALE 1.0f

static void die(const char *m) { fprintf(stderr, "build-layer-fixture: %s\n", m); exit(1); }

static char *join(const char *dir, const char *name) {
    size_t n = strlen(dir) + strlen(name) + 2;
    char *p = malloc(n);
    if (!p || snprintf(p, n, "%s/%s", dir, name) >= (int)n) die("output path too long");
    return p;
}

/* Copy one key verbatim when the source file carries it; silence when it does not. */
static void copy_str_kv(gguf_writer *w, const char *path, const char *key) {
    char value[256];
    if (gguf_read_str_kv(path, key, value, sizeof(value)) == 0)
        if (gguf_write_kv_str(w, key, value)) die("cannot write string metadata");
}
static void copy_uint_kv(gguf_writer *w, const char *path, const char *key) {
    uint64_t value = 0;
    if (gguf_read_uint_kv(path, key, &value) == 0)
        if (gguf_write_kv_u32(w, key, (uint32_t)value)) die("cannot write unsigned metadata");
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: %s REAL.gguf METADATA.txt OUTPUT_DIR PLANT_LAYER\n", argv[0]); return 2; }
    const char *real = argv[1], *meta_path = argv[2], *dir = argv[3];
    char *end = NULL;
    long plant = strtol(argv[4], &end, 10);
    if (!end || *end || plant < -1 || plant >= FIX_LAYERS) die("plant layer must be -1 or a block index");

    int rows = 0, width = 0, groups = 0, pairs = 0;
    FILE *meta = fopen(meta_path, "r");
    char magic[64];
    if (!meta || fscanf(meta, "%63s", magic) != 1 || strcmp(magic, "JOVOVICH_READOUT_V1") ||
        fscanf(meta, "%d %d %d %d", &rows, &width, &groups, &pairs) != 4 || rows < 4 || rows > 10000)
        die("cannot read frozen metadata");
    int *label = calloc((size_t)rows, sizeof(int)), *group = calloc((size_t)rows, sizeof(int));
    int *pair = calloc((size_t)rows, sizeof(int)), *subset = calloc((size_t)rows, sizeof(int));
    if (!label || !group || !pair || !subset) die("metadata allocation failed");
    for (int i = 0; i < rows; i++)
        if (fscanf(meta, "%d %d %d %d", &label[i], &group[i], &pair[i], &subset[i]) != 4)
            die("cannot read metadata row");
    fclose(meta);

    bpe_tokenizer *tok = bpe_load(real);
    if (!tok) die("cannot load the real tokenizer");
    int vocab = bpe_n_vocab(tok);
    if (vocab < 1024) die("unexpected tokenizer size");
    int marker[16], n_marker = bpe_encode_raw(tok, FIX_MARKER, marker, 16);
    if (n_marker < 1 || n_marker > 16) die("marker does not encode");
    for (int i = 0; i < n_marker; i++) if (marker[i] < 0 || marker[i] >= vocab) die("marker id out of range");
    /* Pair-indexed filler gives the planted block a second, label-independent
     * column: a one-column centered matrix leaves the permuted-label fits on a
     * flat optimum, which the declared gradient gate reads as a failed run. */
    int filler[64], n_filler = 0;
    for (int k = 1; k <= FIX_FILLER_MAX + 1; k++) {
        char text[FIX_FILLER_MAX + 2];
        for (int c = 0; c < k; c++) text[c] = FIX_FILLER[0];
        text[k] = 0;
        int ids[32], n = bpe_encode_raw(tok, text, ids, 32);
        for (int i = 0; i < n; i++) {
            int seen = 0;
            for (int j = 0; j < n_filler; j++) if (filler[j] == ids[i]) seen = 1;
            for (int j = 0; j < n_marker; j++) if (marker[j] == ids[i]) die("filler collides with the marker");
            if (!seen) { if (n_filler == 64) die("too many filler ids"); filler[n_filler++] = ids[i]; }
        }
    }
    if (!n_filler) die("filler does not encode");
    int digit[10];
    for (int d = 0; d < 10; d++) {
        char text[2] = { (char)('0' + d), 0 };
        int ids[8], n = bpe_encode_raw(tok, text, ids, 8);
        if (n != 1) die("a decimal digit must be one token");
        digit[d] = ids[0];
    }
    bpe_free(tok);

    /* Prompt-only input in the frozen JVRO1 format: concern rows carry the marker. */
    char *prompts_path = join(dir, "fixture-prompts.bin");
    FILE *p = fopen(prompts_path, "wbx");
    if (!p) die("prompt output must be a new file");
    unsigned char count[4] = { (unsigned char)rows, (unsigned char)(rows >> 8),
                               (unsigned char)(rows >> 16), (unsigned char)(rows >> 24) };
    if (fwrite("JVRO1\0\0\0", 1, 8, p) != 8 || fwrite(count, 1, 4, p) != 4) die("cannot write prompt header");
    for (int i = 0; i < rows; i++) {
        char user[128], pad[FIX_FILLER_MAX + 1];
        int n_pad = pair[i] % FIX_FILLER_MAX + 1;
        for (int c = 0; c < n_pad; c++) pad[c] = FIX_FILLER[0];
        pad[n_pad] = 0;
        snprintf(user, sizeof(user), "case %02d %s%s", i, pad, label[i] ? FIX_MARKER : "");
        const char *parts[2] = { FIX_SYSTEM, user };
        for (int k = 0; k < 2; k++) {
            uint32_t len = (uint32_t)strlen(parts[k]);
            unsigned char b[4] = { (unsigned char)len, (unsigned char)(len >> 8),
                                   (unsigned char)(len >> 16), (unsigned char)(len >> 24) };
            if (fwrite(b, 1, 4, p) != 4 || fwrite(parts[k], 1, len, p) != len) die("cannot write prompt text");
        }
    }
    if (fclose(p)) die("cannot finalize prompts");

    /* Same labels, families, pairs and subsets as the frozen corpus; this body's width. */
    char *meta_out_path = join(dir, "fixture-metadata.txt");
    FILE *mo = fopen(meta_out_path, "wx");
    if (!mo) die("metadata output must be a new file");
    fprintf(mo, "JOVOVICH_READOUT_V1\n%d %d %d %d\n", rows, FIX_E, groups, pairs);
    for (int i = 0; i < rows; i++) fprintf(mo, "%d %d %d %d\n", label[i], group[i], pair[i], subset[i]);
    if (fclose(mo)) die("cannot finalize metadata");

    char *model_path = join(dir, "fixture.gguf");
    gguf_writer *w = gguf_write_open(model_path);
    if (!w) die("cannot open fixture model for writing");
    if (gguf_write_kv_str(w, "general.architecture", "qwen2") ||
        gguf_write_kv_u32(w, "qwen2.block_count", FIX_LAYERS) ||
        gguf_write_kv_u32(w, "qwen2.embedding_length", FIX_E) ||
        gguf_write_kv_u32(w, "qwen2.feed_forward_length", FIX_FFN) ||
        gguf_write_kv_u32(w, "qwen2.attention.head_count", FIX_HEADS) ||
        gguf_write_kv_u32(w, "qwen2.attention.head_count_kv", FIX_KV_HEADS) ||
        gguf_write_kv_u32(w, "qwen2.context_length", FIX_CTX) ||
        gguf_write_kv_f32(w, "qwen2.rope.freq_base", 1000000.0f) ||
        gguf_write_kv_f32(w, "qwen2.attention.layer_norm_rms_epsilon", 1e-6f))
        die("cannot write architecture metadata");
    copy_str_kv(w, real, "tokenizer.ggml.model");
    copy_str_kv(w, real, "tokenizer.ggml.pre");
    int n_tokens = 0, n_merges = 0, n_types = 0;
    char **tokens = gguf_read_str_array(real, "tokenizer.ggml.tokens", &n_tokens);
    char **merges = gguf_read_str_array(real, "tokenizer.ggml.merges", &n_merges);
    int32_t *types = gguf_read_i32_array(real, "tokenizer.ggml.token_type", &n_types);
    if (!tokens || n_tokens != vocab) die("cannot read the real token list");
    if (gguf_write_kv_str_array(w, "tokenizer.ggml.tokens", (const char *const *)tokens, (uint64_t)n_tokens))
        die("cannot write token list");
    if (merges && n_merges > 0 &&
        gguf_write_kv_str_array(w, "tokenizer.ggml.merges", (const char *const *)merges, (uint64_t)n_merges))
        die("cannot write merge list");
    if (types && n_types == vocab &&
        gguf_write_kv_i32_array(w, "tokenizer.ggml.token_type", types, (uint64_t)n_types))
        die("cannot write token types");
    copy_uint_kv(w, real, "tokenizer.ggml.eos_token_id");
    copy_uint_kv(w, real, "tokenizer.ggml.bos_token_id");
    copy_uint_kv(w, real, "tokenizer.ggml.add_bos_token");

    const uint64_t emb_shape[2] = { FIX_E, (uint64_t)vocab };
    if (gguf_write_tensor_decl(w, "token_embd.weight", 2, emb_shape, GGUF_TYPE_F32))
        die("cannot declare embeddings");
    if (gguf_write_tensor_decl(w, "output_norm.weight", 1, (const uint64_t[]){ FIX_E }, GGUF_TYPE_F32))
        die("cannot declare the final norm");
    for (int l = 0; l < FIX_LAYERS; l++) {
        char name[64];
        const struct { const char *suffix; uint64_t in, out; int ndim; } decls[] = {
            { "attn_norm.weight",   FIX_E, 0, 1 },
            { "attn_q.weight",      FIX_E, FIX_E, 2 },
            { "attn_k.weight",      FIX_E, FIX_E, 2 },
            { "attn_v.weight",      FIX_E, FIX_E, 2 },
            { "attn_output.weight", FIX_E, FIX_E, 2 },
            { "ffn_norm.weight",    FIX_E, 0, 1 },
            { "ffn_gate.weight",    FIX_E, FIX_FFN, 2 },
            { "ffn_up.weight",      FIX_E, FIX_FFN, 2 },
            { "ffn_down.weight",    FIX_FFN, FIX_E, 2 },
        };
        for (unsigned d = 0; d < sizeof(decls) / sizeof(*decls); d++) {
            snprintf(name, sizeof(name), "blk.%d.%s", l, decls[d].suffix);
            const uint64_t shape[2] = { decls[d].in, decls[d].out };
            if (gguf_write_tensor_decl(w, name, decls[d].ndim, shape, GGUF_TYPE_F32))
                die("cannot declare a block tensor");
        }
    }

    float *embeddings = calloc((size_t)vocab * FIX_E, sizeof(float));
    if (!embeddings) die("embedding allocation failed");
    for (int v = 0; v < vocab; v++) embeddings[(size_t)v * FIX_E + FIX_E - 1] = 1.0f;
    for (int i = 0; i < n_marker; i++) embeddings[(size_t)marker[i] * FIX_E + FIX_MARKER_IN] = 1.0f;
    for (int i = 0; i < n_filler; i++) embeddings[(size_t)filler[i] * FIX_E + FIX_FILLER_IN] = 1.0f;
    for (int d = 0; d < 10; d++) embeddings[(size_t)digit[d] * FIX_E + FIX_DIGIT_IN + d] = 1.0f;
    if (gguf_write_tensor_f32(w, "token_embd.weight", embeddings, (uint64_t)vocab * FIX_E))
        die("cannot write embeddings");
    free(embeddings);
    float ones[FIX_E], zero_e2[FIX_E * FIX_E] = { 0 }, zero_ffn[FIX_E * FIX_FFN] = { 0 };
    for (int j = 0; j < FIX_E; j++) ones[j] = 1.0f;
    if (gguf_write_tensor_f32(w, "output_norm.weight", ones, FIX_E)) die("cannot write the final norm");
    for (int l = 0; l < FIX_LAYERS; l++) {
        char name[64];
        float v_proj[FIX_E * FIX_E] = { 0 }, o_proj[FIX_E * FIX_E] = { 0 };
        if (l == plant) {
            /* Lane 0 carries the marker, lanes 1..11 the label-independent
             * companions; all of them live in head 0. The uniform causal
             * attention makes each lane the running mean of its coordinate. */
            v_proj[0 * FIX_E + FIX_MARKER_IN] = 1.0f;
            o_proj[FIX_MARKER_OUT * FIX_E + 0] = FIX_PLANT_SCALE;
            for (int d = 0; d < 10; d++) {
                v_proj[(1 + d) * FIX_E + FIX_DIGIT_IN + d] = 1.0f;
                o_proj[(FIX_DIGIT_OUT + d) * FIX_E + 1 + d] = FIX_PLANT_SCALE;
            }
            v_proj[11 * FIX_E + FIX_FILLER_IN] = 1.0f;
            o_proj[FIX_FILLER_OUT * FIX_E + 11] = FIX_PLANT_SCALE;
        }
        const struct { const char *suffix; const float *data; uint64_t n; } writes[] = {
            { "attn_norm.weight",   ones,     FIX_E },
            { "attn_q.weight",      zero_e2,  FIX_E * FIX_E },
            { "attn_k.weight",      zero_e2,  FIX_E * FIX_E },
            { "attn_v.weight",      v_proj,   FIX_E * FIX_E },
            { "attn_output.weight", o_proj,   FIX_E * FIX_E },
            { "ffn_norm.weight",    ones,     FIX_E },
            { "ffn_gate.weight",    zero_ffn, FIX_E * FIX_FFN },
            { "ffn_up.weight",      zero_ffn, FIX_E * FIX_FFN },
            { "ffn_down.weight",    zero_ffn, FIX_FFN * FIX_E },
        };
        for (unsigned d = 0; d < sizeof(writes) / sizeof(*writes); d++) {
            snprintf(name, sizeof(name), "blk.%d.%s", l, writes[d].suffix);
            if (gguf_write_tensor_f32(w, name, writes[d].data, writes[d].n))
                die("cannot write a block tensor");
        }
    }
    if (gguf_write_close(w)) die("fixture model did not close cleanly");

    printf("{\"fixture\":\"%s\",\"prompts\":\"%s\",\"metadata\":\"%s\","
           "\"plant_layer\":%ld,\"layers\":%d,\"embed\":%d,\"heads\":%d,\"kv_heads\":%d,"
           "\"ffn\":%d,\"context\":%d,\"vocab\":%d,\"rows\":%d,\"families\":%d,\"pairs\":%d,"
           "\"marker_text\":\"%s\",\"marker_ids\":[",
           model_path, prompts_path, meta_out_path, plant, FIX_LAYERS, FIX_E, FIX_HEADS,
           FIX_KV_HEADS, FIX_FFN, FIX_CTX, vocab, rows, groups, pairs, FIX_MARKER);
    for (int i = 0; i < n_marker; i++) printf("%s%d", i ? "," : "", marker[i]);
    printf("],\"filler_text\":\"%s\",\"filler_ids\":[", FIX_FILLER);
    for (int i = 0; i < n_filler; i++) printf("%s%d", i ? "," : "", filler[i]);
    printf("],\"digit_ids\":[");
    for (int d = 0; d < 10; d++) printf("%s%d", d ? "," : "", digit[d]);
    printf("],\"coordinates\":{\"marker_in\":%d,\"marker_out\":%d,\"digit_in\":%d,\"digit_out\":%d,"
           "\"filler_in\":%d,\"filler_out\":%d,\"constant\":%d",
           FIX_MARKER_IN, FIX_MARKER_OUT, FIX_DIGIT_IN, FIX_DIGIT_OUT, FIX_FILLER_IN, FIX_FILLER_OUT, FIX_E - 1);
    printf("}");
    int concern = 0;
    for (int i = 0; i < rows; i++) concern += label[i];
    printf(",\"plant_scale\":%.9g,\"concern_rows\":%d}\n", (double)FIX_PLANT_SCALE, concern);
    free(label); free(group); free(pair); free(subset);
    free(prompts_path); free(meta_out_path); free(model_path);
    return 0;
}
