#ifndef JOV_HTML_STATE_H
#define JOV_HTML_STATE_H
#include "ariannamethod.h"
#include "hash.h"
#include "json.h"
#include "tools/narrow_json.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* A complete committed file, distinct from the diff retained as review evidence. */
typedef struct {
    char *content, *blob;
    char sha256[65], digest[65];
} jov_html_state;

static inline int jov_html_path(const char *file) {
    const char *ext=file?strrchr(file,'.'):NULL;
    if(!ext || strlen(ext)>5)return 0;
    char lower[6];size_t n=strlen(ext);
    for(size_t i=0;i<=n;i++)lower[i]=ext[i]>='A' && ext[i]<='Z'?ext[i]+('a'-'A'):ext[i];
    return !strcmp(lower,".html") || !strcmp(lower,".htm");
}
static inline void jov_html_free(jov_html_state *s) {
    free(s->content);free(s->blob);memset(s,0,sizeof(*s));
}
static inline void jov_html_json(FILE *out,const jov_html_state *s) {
    fputs("{\"schema\":\"jovovich.html-state/1\",",out);
    json_field(out,"head_blob",s->blob);fputc(',',out);
    json_field(out,"sha256",s->sha256);fputc(',',out);
    json_field(out,"content",s->content);fputc('}',out);
}
static inline int jov_html_hash(jov_html_state *s) {
    FILE *f=tmpfile();if(!f)return 1;
    jov_html_json(f,s);long n=ftell(f);char *p=NULL;int bad=1;
    if(n>0 && n<=1048576 && !ferror(f) && !fseek(f,0,SEEK_SET) && (p=malloc((size_t)n)) &&
       fread(p,1,(size_t)n,f)==(size_t)n)bad=hash_bytes(p,(size_t)n,s->digest);
    free(p);if(fclose(f))bad=1;return bad;
}
/* Absent state preserves the historical diff prompt. No extension-based
 * reinterpretation of an old input or an archived answer occurs here. */
static inline int jov_html_decode(const char *raw,const char *file,const char *head,jov_html_state *s) {
    if(!raw)return 0;
    if(!jov_html_path(file) || !head || !nj_is(nj_get(raw,"schema"),"jovovich.html-state/1") ||
       !(s->content=nj_string(nj_get(raw,"content"))) || !(s->blob=nj_string(nj_get(raw,"head_blob"))) ||
       strlen(s->blob)!=strlen(head) || strspn(s->blob,"0123456789abcdef")!=strlen(head) ||
       strlen(s->content)>262144 || hash_bytes(s->content,strlen(s->content),s->sha256) ||
       !nj_is(nj_get(raw,"sha256"),s->sha256) || jov_html_hash(s))return 1;
    AM_String *text=am_string_new(s->content);if(!text)return 1;
    am_string_free(text);return 0;
}
static inline const char *jov_html_context(const jov_html_state *s,const char *file,const char *rule) {
    if(!s->content || am_set_var_text("source_file",file) || am_set_var_text("source_rules",rule) ||
       am_set_var_text("source_html",s->content) || am_exec_file("aml/html-context.aml"))return NULL;
    return am_get_var_text("review_context");
}
static inline int jov_html_order(int reverse) {
    float order[1]={(float)reverse};
    return am_set_var_array("html_order",order,1);
}
static inline int jov_html_scores(const float logits[4],float probabilities[2]) {
    for(int i=0;i<4;i++)if(!isfinite(logits[i]))return 1;
    if(am_set_var_array("html_logits",logits,4) || am_exec_file("aml/score-html.aml") ||
       am_exec_file("aml/score-choices.aml"))return 1;
    int n=0;const float *p=am_get_var_array("probabilities",&n);
    if(!p || n!=2 || !isfinite(p[0]) || !isfinite(p[1]))return 1;
    memcpy(probabilities,p,2*sizeof(float));return 0;
}
#endif
