#ifndef JOV_PROMPT_TEXT_H
#define JOV_PROMPT_TEXT_H
#include "examples/bpe.h"
#include <stdlib.h>
#include <string.h>

static inline int jov_ascii_graph(unsigned char c) { return c >= 33 && c <= 126; }

/* A spaced em dash is one Qwen punctuation piece between two ASCII words
 * or symbols. The pinned tokenizer names it 1892. Require the exact decoded
 * bytes and leave both ASCII spans, including chat tokens, to native BPE. */
static inline int jov_prompt_ids(bpe_tokenizer *tok, const char *text, int *ids, int capacity) {
    const char *dash = "\xe2\x80\x94";
    const char *first = strstr(text, dash);
    if (!first) return bpe_encode_special(tok, text, ids, capacity);
    char bytes[8];
    if (bpe_add_bos(tok) || bpe_decode_token(tok, 1892, bytes, sizeof(bytes)) != 4 ||
        memcmp(bytes, " \xe2\x80\x94", 4)) return 0;
    char *copy = strdup(text);
    if (!copy) return 0;
    char *span = copy, *hit = copy + (first - text);
    int count = 0;
    while (hit) {
        if (hit - span < 2 || !jov_ascii_graph((unsigned char)hit[-2]) ||
            hit[-1] != ' ' || hit[3] != ' ' || !jov_ascii_graph((unsigned char)hit[4])) goto invalid;
        hit[-1] = '\0';
        int n = bpe_encode_special(tok, span, ids + count, capacity - count);
        if (n < 1 || n >= capacity - count) goto invalid;
        count += n;
        ids[count++] = 1892;
        span = hit + 3;
        hit = strstr(span, dash);
    }
    int n = bpe_encode_special(tok, span, ids + count, capacity - count);
    if (n < 1 || n >= capacity - count) goto invalid;
    free(copy);
    return count + n;
invalid:
    free(copy);
    return 0;
}
#endif
