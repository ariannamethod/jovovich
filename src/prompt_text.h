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

/* Both models pin the same tokenizer. Its consecutive GGUF CONTROL and
 * USER_DEFINED records are 248044..248076. Preserve the source bytes, but never
 * feed a role, tool, reasoning or multimodal control ID from the review data.
 * Tokenize the intact frame first: ordinary prompts retain all BPE merges,
 * including those that straddle the edges of the evidence. */
static inline int jov_framed_prompt_ids(bpe_tokenizer *tok,const char *prompt,const char *state,
                                        int *ids,int capacity) {
    const char marker[]="<|im_start|>user\n<state>\n";
    const char *begin=strstr(prompt,marker);
    if (!begin || !state || capacity<=0) return 0;
    begin+=sizeof(marker)-1;
    size_t state_length=strlen(state);
    if (strncmp(begin,state,state_length) || strncmp(begin+state_length,"\n</state>\n",10)) return 0;
    int count=jov_prompt_ids(tok,prompt,ids,capacity);
    if (count<=0 || count>=capacity || !strchr(state,'<')) return count<capacity?count:0;
    const char *end=begin+state_length, *cursor=prompt+strlen(prompt);
    int write=capacity;
    for (int i=count-1;i>=0;i--) {
        char token[512];
        int bufsize=bpe_decode_token_capacity(tok,ids[i]);
        if (bufsize<=0 || (size_t)bufsize>sizeof(token)) return 0;
        int len=bpe_decode_token(tok,ids[i],token,bufsize);
        if (len<=0 || cursor-prompt<len || memcmp(cursor-len,token,(size_t)len)) return 0;
        cursor-=len;
        if (ids[i]>=248044 && ids[i]<=248076 && cursor>=begin && cursor<end) {
            /* Split the literal opening '<' away. Raw BPE alone still admits
             * USER_DEFINED tokens. Both parts decode to the exact spelling. */
            int ordinary[64];
            if (cursor+len>end || token[0]!='<' || len<2 || len>=(int)(sizeof(ordinary)/sizeof(*ordinary))) return 0;
            int open=bpe_encode_raw(tok,"<",ordinary,1);
            int rest=bpe_encode_raw(tok,token+1,ordinary+1,len);
            if (open!=1 || rest<1 || write-rest-1<i) return 0;
            write-=rest+1;
            for (int j=0;j<=rest;j++)
                if (ordinary[j]>=248044 && ordinary[j]<=248076) return 0;
            memcpy(ids+write,ordinary,(size_t)(rest+1)*sizeof(*ids));
        } else {
            if (write<=i) return 0;
            ids[--write]=ids[i];
        }
    }
    if (cursor!=prompt) return 0;
    count=capacity-write;
    memmove(ids,ids+write,(size_t)count*sizeof(*ids));
    return count;
}
#endif
