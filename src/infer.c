/* JOVOVICH's mouth. notorch does every model operation; stdin carries ChatML. */
#include "harness/arch.h"
#include "examples/bpe.h"

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(const char *name) {
    fprintf(stderr, "usage: %s --model file.gguf [--tokens 256] [--context 8192] "
                    "[--temperature 0] [--tokens-only | --token-ids] < prompt.txt\n", name);
}

static int positive_int(const char *s, int *out) {
    char *end;
    errno = 0;
    long n = strtol(s, &end, 10);
    if (errno || end == s || *end || n < 1 || n > INT_MAX) return -1;
    *out = (int)n;
    return 0;
}

static char *read_prompt(void) {
    size_t len = 0, cap = 4096;
    char *p = malloc(cap);
    if (!p) return NULL;
    for (;;) {
        size_t n = fread(p + len, 1, cap - len - 1, stdin);
        if (memchr(p + len, 0, n)) {
            fprintf(stderr, "jovovich: prompt contains a NUL byte\n");
            free(p);
            return NULL;
        }
        len += n;
        if (ferror(stdin)) { free(p); return NULL; }
        if (feof(stdin)) break;
        if (len == cap - 1) {
            /* A megabyte of diff already exceeds this body's useful context. */
            if (cap >= 16 * 1024 * 1024) {
                fprintf(stderr, "jovovich: prompt exceeds 16 MiB\n");
                free(p);
                return NULL;
            }
            cap *= 2;
            char *next = realloc(p, cap);
            if (!next) { free(p); return NULL; }
            p = next;
        }
    }
    p[len] = 0;
    return p;
}

/* CONTROL tokens are intentionally literal in notorch's ordinary-text encoder.
 * A chat caller owns its template and inserts those IDs, just as the trainer
 * does. Tokenizing their spelling as prose changes the model's input protocol. */
static int encode_chatml(bpe_tokenizer *tok, char *text, int *ids, int cap,
                        int im_start, int im_end) {
    char *p = text;
    int n = 0;
    while (*p && n < cap) {
        char *start = strstr(p, "<|im_start|>");
        char *end = strstr(p, "<|im_end|>");
        char *marker = start && (!end || start < end) ? start : end;
        if (!marker) return n + bpe_encode_raw(tok, p, ids + n, cap - n);
        char saved = *marker;
        *marker = 0;
        n += bpe_encode_raw(tok, p, ids + n, cap - n);
        *marker = saved;
        if (n == cap) return n;
        ids[n++] = marker == start ? im_start : im_end;
        p = marker + (marker == start ? strlen("<|im_start|>") : strlen("<|im_end|>"));
    }
    return n;
}

int main(int argc, char **argv) {
    const char *path = NULL;
    int max_tokens = 256, context = 8192, tokens_only = 0, token_ids = 0;
    float temperature = 0;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--help")) { usage(argv[0]); return 0; }
        if (!strcmp(arg, "--tokens-only")) { tokens_only = 1; continue; }
        if (!strcmp(arg, "--token-ids")) { token_ids = 1; continue; }
        if (i + 1 >= argc) { usage(argv[0]); return 2; }
        const char *value = argv[++i];
        if (!strcmp(arg, "--model")) path = value;
        else if (!strcmp(arg, "--tokens")) {
            if (positive_int(value, &max_tokens)) { usage(argv[0]); return 2; }
        } else if (!strcmp(arg, "--context")) {
            if (positive_int(value, &context)) { usage(argv[0]); return 2; }
        } else if (!strcmp(arg, "--temperature")) {
            char *end;
            errno = 0;
            temperature = strtof(value, &end);
            if (errno || end == value || *end || !isfinite(temperature) || temperature < 0) {
                usage(argv[0]); return 2;
            }
        } else { usage(argv[0]); return 2; }
    }
    if (!path || max_tokens >= context || context > 131072) {
        fprintf(stderr, "jovovich: require a model and 0 < tokens < context <= 131072\n");
        return 2;
    }

    int result = 1;
    char *prompt = NULL;
    int *ids = NULL;
    float *logits = NULL;
    bpe_tokenizer *tok = NULL;
    kv_cache *kv = NULL;
    void *model = NULL;
    const nt_arch *arch = &nt_arch_llama;
    gguf_file *gf = gguf_open(path);
    if (!gf) goto done;
    /* notorch's dense Qwen3 path loads QK norms and applies them before RoPE;
     * keeping the file's architecture also preserves its metadata namespace. */
    if (strcmp(gf->arch, "qwen2") && strcmp(gf->arch, "qwen3")) {
        fprintf(stderr, "jovovich: expected qwen2 or qwen3 architecture, got '%s'\n", gf->arch);
        goto done;
    }
    if (gf->ctx_len > 0 && context > gf->ctx_len) {
        fprintf(stderr, "jovovich: context %d exceeds model context %d\n", context, gf->ctx_len);
        goto done;
    }
    tok = bpe_load(path);
    if (!tok) { fprintf(stderr, "jovovich: model has no readable tokenizer\n"); goto done; }
    int im_start = bpe_token_id(tok, "<|im_start|>");
    int im_end = bpe_token_id(tok, "<|im_end|>");
    int endoftext = bpe_token_id(tok, "<|endoftext|>");
    uint64_t eos_value;
    if (im_start < 0 || im_end < 0 ||
        gguf_read_uint_kv(path, "tokenizer.ggml.eos_token_id", &eos_value) ||
        eos_value >= (uint64_t)bpe_n_vocab(tok)) {
        fprintf(stderr, "jovovich: missing ChatML markers or valid EOS metadata\n");
        goto done;
    }
    int eos = (int)eos_value;
    prompt = read_prompt();
    ids = malloc(((size_t)context + 1) * sizeof(*ids));
    if (!prompt || !ids) { fprintf(stderr, "jovovich: cannot read prompt\n"); goto done; }
    if (!*prompt) { fprintf(stderr, "jovovich: empty prompt\n"); goto done; }
    /* One extra slot detects overflow, including bpe_encode's capped result. */
    int n = encode_chatml(tok, prompt, ids, context + 1, im_start, im_end);
    if (n < 1 || n > context - max_tokens) {
        fprintf(stderr, "jovovich: prompt has %s%d tokens; context %d reserves %d for output\n",
                n == context + 1 ? "at least " : "", n, context, max_tokens);
        goto done;
    }
    if (token_ids) {
        for (int i = 0; i < n; i++) printf("%s%d", i ? "," : "", ids[i]);
        putchar('\n'); result = 0; goto done;
    }
    if (tokens_only) { printf("%d\n", n); result = 0; goto done; }

    nt_dims dims = {0};
    model = arch->load(gf, &dims);
    if (!model) goto done;
    if (dims.vocab != bpe_n_vocab(tok)) {
        fprintf(stderr, "jovovich: tokenizer and model vocabulary sizes disagree\n");
        goto done;
    }
    kv = kv_new(dims.n_layers, n + max_tokens, dims.kv_dim);
    logits = malloc((size_t)dims.vocab * sizeof(*logits));
    if (!kv || !kv->k || !kv->v || !logits) {
        fprintf(stderr, "jovovich: cannot allocate inference buffers\n");
        goto done;
    }
    fprintf(stderr, "jovovich: prompt=%d reserve=%d context=%d; ChatML=%d/%d EOS=%d\n",
            n, max_tokens, context, im_start, im_end, eos);
    double started = now_ms();
    for (int pos = 0; pos < n; pos += NT_PREFILL_CHUNK) {
        int count = n - pos;
        if (count > NT_PREFILL_CHUNK) count = NT_PREFILL_CHUNK;
        int rc = arch->forward(model, kv, ids + pos, count, pos,
                               pos + count == n ? logits : NULL);
        if (rc != NT_OK) {
            fprintf(stderr, "jovovich: prefill failed: %s\n", nt_strerror(rc));
            goto done;
        }
    }
    double prefilling = now_ms() - started;
    int generated = 0, stopped = 0;
    for (int step = 0; step < max_tokens; step++) {
        int next = sample(logits, dims.vocab, temperature);
        if (next == eos || next == im_end || next == endoftext || bpe_is_eog(tok, next)) {
            stopped = 1;
            break;
        }
        char piece[8192];
        int bytes = bpe_decode_token(tok, next, piece, sizeof(piece));
        if (bytes >= (int)sizeof(piece) - 1 ||
            fwrite(piece, 1, (size_t)bytes, stdout) != (size_t)bytes || fflush(stdout)) {
            fprintf(stderr, "jovovich: cannot emit complete output token\n");
            goto done;
        }
        generated++;
        if (step + 1 == max_tokens) break;
        int rc = arch->forward(model, kv, &next, 1, n + step, logits);
        if (rc != NT_OK) {
            fprintf(stderr, "jovovich: decode failed: %s\n", nt_strerror(rc));
            goto done;
        }
    }
    fprintf(stderr, "jovovich: prefill %.0f ms, generated %d tokens in %.0f ms, stop=%s\n",
            prefilling, generated, now_ms() - started - prefilling,
            stopped ? "eos" : "token-limit");
    result = 0;
done:
    free(prompt);
    free(ids);
    free(logits);
    kv_free(kv);
    if (model) arch->free(model);
    if (tok) bpe_free(tok);
    if (gf) gguf_close(gf);
    return result;
}
