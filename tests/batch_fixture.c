/* Synthetic serialization fixtures only. No model inference occurs here. */
#define _POSIX_C_SOURCE 200809L
#include "review.h"
#include "facts.h"
#include "hash.h"
#include "tools/narrow_json.h"
#include "ariannamethod.h"
#include <assert.h>
static char *str(const char*j,const char*k){char*s=nj_string(nj_get(j,k));assert(s);return s;}
static int num(const char*j,const char*k){long long v;assert(!nj_int(nj_get(j,k),&v));return (int)v;}
int main(int argc,char**argv) {
    assert(argc==4);
    if(!strcmp(argv[1],"check")) {
        char*j=nj_load(argv[2],NULL);assert(j);const char*s=nj_get(j,"summary");
        int concerns=atoi(argv[3]);assert(num(s,"reviewed_files")==2 && num(s,"concern_files")==concerns && num(s,"clean_files")==2-concerns);
        assert(nj_is(nj_get(s,"verdict"),concerns?"CONCERN":"CLEAN"));assert(!nj_get(s,"probabilities"));
        int bad=0,n=0;for(const char*r=nj_first(nj_get(j,"reviews"),&bad);r;r=nj_next(r,']',&bad)){assert(nj_get(r,"source") && nj_get(r,"execution"));n++;}
        assert(!bad && n==2);free(j);puts("Batch summary: exact counts, rule and per-file receipts preserved");return 0;
    }
    assert(!strcmp(argv[1],"emit"));FILE*f=fopen(argv[2],"r");assert(f);
    char*m=nj_load("models/onejev-0.8b.json",NULL);assert(m);
    char*model=str(m,"model_id"),*revision=str(m,"revision"),*wh=str(m,"weights_sha256"),*th=str(m,"tokenizer_sha256");
    am_init();am_persistent_mode(1);char*line=NULL;size_t cap=0;ssize_t n;int i=0;
    while((n=getline(&line,&cap,f))>=0) {
        char*id=str(line,"id"),*file=str(line,"file"),*context=str(line,"context"),*rule=str(line,"rule_excerpt"),*change=str(line,"change_excerpt");
        const char*s=nj_get(line,"source");const char*keys[]={"base_commit","head_commit","rules_path","rules_blob","rules_sha256","diff_sha256"};char*o[6];
        for(int j=0;j<6;j++)o[j]=str(s,keys[j]);
        jov_source source={o[0],o[1],o[2],o[3],o[4],o[5],num(s,"rule_first_line"),num(s,"rule_last_line")};
        char ih[65];assert(!hash_bytes(line,(size_t)n,ih));
        if(i==1 && !strcmp(argv[3],"badhash"))ih[0]=ih[0]=='0'?'1':'0';
        jov_execution e={ih,wh,th,20763,1,0,NULL,NULL,NULL};
        double a=i==1 && !strcmp(argv[3],"mixed")?.9:i==1 && !strcmp(argv[3],"tie")?.5:.1;
        assert(!am_set_var_text("review_context",context) && !am_exec_file("aml/prepare.aml"));
        jov_review r={.id=id,.model=model,.revision=revision,.question=am_get_var_text("question"),.file=file,.context=context,
            .rule_excerpt=rule,.change_excerpt=change,.concern=a,.clean=1-a,.source=&source,.execution=&e};
        jov_fact *fact = NULL;
        assert(!jov_fact_decode(nj_get(line, "fact"), &fact));
        r.fact = fact;
        assert(!jov_review_json(stdout,&r));
        jov_fact_free(fact);
        free(id);free(file);free(context);free(rule);free(change);for(int j=0;j<6;j++)free(o[j]);i++;
    }
    assert(i>=1);fclose(f);free(line);free(m);free(model);free(revision);free(wh);free(th);am_persistent_mode(0);return 0;
}
