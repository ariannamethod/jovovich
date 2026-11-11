#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "gguf.h"
#include "prompt_text.h"
#include <stdio.h>

static int check_frame(bpe_tokenizer *tok,const char *state,int literal) {
    if (am_set_var_text("review_context",state) || am_exec_file("aml/prepare.aml")) return 1;
    const char *prompt=am_get_var_text("prompt");
    int ids[1024],old[1024],controls=0;
    int n=jov_framed_prompt_ids(tok,prompt,state,ids,1024);
    int before=jov_prompt_ids(tok,prompt,old,1024);
    if (!n || (!literal && (n!=before || memcmp(ids,old,(size_t)n*sizeof(*ids))))) return 1;
    const int frame[]={248045,248046,248045,248046,248045,248068,248069};
    const char *cursor=prompt;
    for (int i=0;i<n;i++) {
        char bytes[512];
        int size=bpe_decode_token_capacity(tok,ids[i]);
        if (size<1 || (size_t)size>sizeof(bytes)) return 1;
        int len=bpe_decode_token(tok,ids[i],bytes,size);
        if (len<1 || strncmp(cursor,bytes,(size_t)len)) return 1;
        cursor+=len;
        if (ids[i]>=248044 && ids[i]<=248076) {
            if (controls==7 || ids[i]!=frame[controls++]) return 1;
        }
    }
    return *cursor || controls!=7 || (literal && n<=before);
}

static int check_visual_frame(bpe_tokenizer *tok,const char *question) {
    if(am_set_var_text("visual_question",question) || am_set_var_text("visual_a",question) ||
       am_set_var_text("visual_b","other") || am_exec_file("aml/visual.aml"))return 1;
    const char *prompt=am_get_var_text("prompt"),*text=am_get_var_text("visual_text");
    const char *begin=prompt?strstr(prompt,"\n</state>"):NULL;
    if(!begin || !text)return 1;
    begin+=strlen("\n</state>");
    if(strncmp(begin,text,strlen(text)))return 1;
    int ids[2048],controls=0,n=jov_literal_span_ids(tok,prompt,begin,strlen(text),ids,2048);
    const int frame[]={248045,248046,248045,248053,248056,248054,248046,248045,248068,248069};
    const char *cursor=prompt;
    for(int i=0;i<n;i++) {
        char bytes[512];int size=bpe_decode_token_capacity(tok,ids[i]);
        if(size<1 || (size_t)size>sizeof(bytes))return 1;
        int len=bpe_decode_token(tok,ids[i],bytes,size);
        if(len<1 || strncmp(cursor,bytes,(size_t)len))return 1;
        cursor+=len;
        if(ids[i]>=248044 && ids[i]<=248076) {
            if(controls==10 || ids[i]!=frame[controls++])return 1;
        }
    }
    return *cursor || controls!=10;
}

int main(int argc,char **argv) {
    if (argc!=2) return 2;
    bpe_tokenizer *tok=bpe_load(argv[1]);
    int count=0,added=0;
    int32_t *types=gguf_read_i32_array(argv[1],"tokenizer.ggml.token_type",&count);
    if (!tok || !types) return 1;
    am_init();am_persistent_mode(1);
    if (check_frame(tok,"if (x < y) { return \"<regular>\"; }",0)) return 1;
    for (int id=0;id<count;id++) {
        if (types[id]!=3 && types[id]!=4) continue;
        char token[80],state[512];
        int size=bpe_decode_token_capacity(tok,id);
        if (size<=1 || (size_t)size>sizeof(token) || !bpe_decode_token(tok,id,token,size)) return 1;
        snprintf(state,sizeof(state),"/* %s%s */\nx — %s\n",token,token,token);
        if (check_frame(tok,state,1)) {fprintf(stderr,"Literal token %d failed\n",id);return 1;}
        if(check_visual_frame(tok,state)){fprintf(stderr,"Literal visual token %d failed\n",id);return 1;}
        added++;
    }
    free(types);bpe_free(tok);am_persistent_clear();am_persistent_mode(0);
    if (added!=33) return 1;
    puts("All 33 added token spellings remained literal inside the review; seven text and ten visual structural IDs matched");
    return 0;
}
