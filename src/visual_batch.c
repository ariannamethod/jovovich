#define _POSIX_C_SOURCE 200809L
#include "visual_batch.h"
#include "visual_compare.h"
#include "report_json.h"
#include "review.h"
#include "hash.h"
#include "ariannamethod.h"
#include <math.h>

void jov_visual_batch_free(jov_visual_batch *v) {
    free(v->request);free(v->comparison);free(v->file);free(v->id);memset(v,0,sizeof(*v));
}
int jov_visual_batch_load(jov_visual_batch *v,const char *memory,const char *request,
    const char *repository,int pr,const char *base,const char *head) {
    if(request)request=nj_ws(request);
    const char *end=request?report_json_end(request,0):NULL;
    if(!end || *request!='{' || !repository || !*repository || pr<1 ||
       !(v->request=strndup(request,(size_t)(end-request))) ||
       jov_visual_comparison(memory,v->request,&v->comparison))goto bad;
    const char *c=v->comparison;
    v->id=nj_string(nj_get(c,"id"));
    if(!v->id || !nj_is(nj_get(c,"repository"),repository))goto bad;
    const char *sides[]={"before","after"},*commits[]={base,head};
    for(int i=0;i<2;i++) {
        const char *receipt=nj_get(c,sides[i]);
        const char *src=nj_get(nj_get(receipt,"origin"),"source");long long number;
        if(!nj_is(nj_get(src,"repository"),repository) ||
           !nj_is(nj_get(src,"commit"),commits[i]) ||
           nj_int(nj_get(src,"pull_request"),&number) || number!=pr)goto bad;
        if(!i)v->file=nj_string(nj_get(src,"path"));
        if(!v->file || !nj_is(nj_get(src,"path"),v->file))goto bad;
    }
    if(hash_bytes(c,strlen(c),v->digest))goto bad;
    return 0;
bad:
    jov_visual_batch_free(v);return 1;
}
static int same(const char *a,const char *ak,const char *b,const char *bk) {
    char *s=nj_string(nj_get(b,bk));int ok=s && nj_is(nj_get(a,ak),s);free(s);return ok;
}
int jov_visual_batch_answer(const jov_visual_batch *v,const char *answer,const char *manifest,float *concern) {
    const char *comparison=nj_get(answer,"comparison"),*end=comparison?report_json_end(comparison,0):NULL;
    double la,lb,a,b,c,k;char ph[65];int reverse=nj_is(nj_get(v->request,"concern_letter"),"B");
    if(!end || (size_t)(end-comparison)!=strlen(v->comparison) || memcmp(comparison,v->comparison,(size_t)(end-comparison)) ||
       !nj_is(nj_get(answer,"schema"),"jovovich.visual-review/1") || !nj_is(nj_get(answer,"id"),v->id) ||
       !same(answer,"input_sha256",v->comparison,"input_sha256") ||
       !same(answer,"weights_sha256",manifest,"weights_sha256") || !same(answer,"tokenizer_sha256",manifest,"tokenizer_sha256"))return 1;
    /* Restore the exact AML frame without rereading memory or mutable files. */
    const char *sides[]={"before","after"};char *values[2]={0},*question=NULL,*rule=NULL;int bad=1;
    for(int i=0;i<2;i++) {
        const char *obs=nj_get(nj_get(nj_get(v->comparison,sides[i]),"origin"),"observation");
        values[i]=nj_string(nj_get(obs,nj_is(nj_get(obs,"letter"),"A")?"choice_a":"choice_b"));
        if(!i)question=nj_string(nj_get(obs,"question"));
    }
    rule=nj_string(nj_get(nj_get(v->comparison,"rule"),"quote"));float order[1]={(float)reverse};
    if(!question || !rule || !values[0] || !values[1] ||
       am_set_var_text("compare_rule",rule) || am_set_var_text("compare_question",question) ||
       am_set_var_text("compare_before",values[0]) || am_set_var_text("compare_after",values[1]) ||
       am_set_var_array("compare_order",order,1) || am_exec_file("aml/visual-compare.aml") || am_exec_file("aml/visual-recall.aml"))goto done;
    const char *prompt=am_get_var_text("prompt"),*q=am_get_var_text("visual_question"),*ca=am_get_var_text("visual_a"),*cb=am_get_var_text("visual_b");
    if(!prompt || !q || !ca || !cb || hash_bytes(prompt,strlen(prompt),ph) ||
       !nj_is(nj_get(answer,"prompt_sha256"),ph) || !nj_is(nj_get(answer,"question"),q) ||
       !nj_is(nj_get(answer,"choice_a"),ca) || !nj_is(nj_get(answer,"choice_b"),cb) ||
       nj_number(nj_get(answer,"logit_a"),&la) || nj_number(nj_get(answer,"logit_b"),&lb) ||
       nj_number(nj_get(answer,"p_a"),&a) || nj_number(nj_get(answer,"p_b"),&b) ||
       nj_number(nj_get(answer,"concern"),&c) || nj_number(nj_get(answer,"clean"),&k) ||
       !isfinite(la) || !isfinite(lb) || !isfinite(a) || !isfinite(b) || !isfinite(c) || !isfinite(k) ||
       a<0 || a>1 || b<0 || b>1 || fabs(a+b-1)>1e-6 ||
       c!=(reverse?b:a) || k!=(reverse?a:b))goto done;
    float logits[2]={(float)la,(float)lb};int n=0;
    if(!isfinite(logits[0]) || !isfinite(logits[1]) || am_set_var_array("choice_logits",logits,2) || am_exec_file("aml/score-choices.aml"))goto done;
    const float *p=am_get_var_array("probabilities",&n);
    if(!p || n!=2 || (float)a!=p[0] || (float)b!=p[1] ||
       (c>=k)!=(p[reverse]>=p[1-reverse]) ||
       !nj_is(nj_get(answer,"verdict"),c>=k?"CONCERN":"CLEAN") ||
       !nj_is(nj_get(answer,"letter"),(c>=k?!reverse:reverse)?"A":"B"))goto done;
    *concern=c>=k?1:0;bad=0;
done:
    free(values[0]);free(values[1]);free(question);free(rule);return bad;
}
static void text_field(FILE *out,const char *row,const char *key) {
    char *s=nj_string(nj_get(row,key));if(s)jov_markdown_text(out,s,0);free(s);
}
int jov_visual_batch_markdown(FILE *out,const jov_visual_batch *v,const char *answer) {
    double c,k;if(nj_number(nj_get(answer,"concern"),&c) || nj_number(nj_get(answer,"clean"),&k))return 1;
    fputs("\n---\n\n### Visual review: ",out);jov_markdown_text(out,v->file,0);
    fprintf(out,"\n\n**%s** · CONCERN %.6f · CLEAN %.6f\n\nRepository: ",c>=k?"CONCERN":"CLEAN",c,k);
    text_field(out,v->comparison,"repository");fputs(" · Key: ",out);text_field(out,v->comparison,"key");
    const char *sides[]={"before","after"};
    for(int i=0;i<2;i++) {
        const char *r=nj_get(v->comparison,sides[i]),*o=nj_get(r,"origin"),*src=nj_get(o,"source"),*obs=nj_get(o,"observation");
        long long seq=0,pr=0;nj_int(nj_get(r,"sequence"),&seq);nj_int(nj_get(src,"pull_request"),&pr);
        fprintf(out,"\n\n%s (memory #%lld, PR #%lld): ",i?"After":"Before",seq,pr);
        text_field(out,obs,nj_is(nj_get(obs,"letter"),"A")?"choice_a":"choice_b");
        fputs("\n\nGit: ",out);text_field(out,src,"commit");fputs(" · ",out);text_field(out,src,"path");
        fputs("\n\nImage SHA-256: ",out);text_field(out,nj_get(obs,"image"),"sha256");
    }
    const char *rule=nj_get(v->comparison,"rule");long long first=0,last=0;
    nj_int(nj_get(rule,"first"),&first);nj_int(nj_get(rule,"last"),&last);
    fputs("\n\nBase rule: ",out);text_field(out,rule,"path");fprintf(out,":%lld–%lld\n\n",first,last);
    text_field(out,rule,"quote");fputs("\n\nComparison SHA-256: ",out);jov_markdown_text(out,v->digest,0);fputc('\n',out);
    return ferror(out);
}
