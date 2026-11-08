/* Score a complete native review run against separately stored expectations. */
#define _POSIX_C_SOURCE 200809L
#include "review.h"
#include "json.h"
#include "boundary_view.h"
#include "hash.h"
#include "report_json.h"
#include "model_manifest.h"
#include "ariannamethod.h"
#include <math.h>

#define MAX_CASES 256
typedef struct {
    char *id,*split,*family,*expected,*predicted;
    double concern,clean;
} result;
typedef struct {int total,correct,missed_concern,false_concern;} tally;

static char *field(const char*j,const char*k){return nj_string(nj_get(j,k));}
static int same(const char*j,const char*k,const char*want) {
    char*s=field(j,k);int ok=s && want && !strcmp(s,want);free(s);return ok;
}
static int choice(const char*s){return s && (!strcmp(s,"CONCERN") || !strcmp(s,"CLEAN"));}
static int line(FILE*f,char**s,size_t*cap) {
    ssize_t n=getline(s,cap,f);if(n<0)return ferror(f)?-1:0;
    if(n>1048576 || memchr(*s,0,(size_t)n))return -1;
    const char*end=report_json_end(*s,0);return end && !*nj_ws(end)?1:-1;
}
static int validate(result*r,const char*expected,const char*input,const char*answer,const char*manifest,const char*prepare,int index,int *policy) {
    r->id=field(expected,"id");r->split=field(expected,"split");r->family=field(expected,"family");r->expected=field(expected,"expected");
    const char*p=nj_get(nj_get(answer,"choice"),"probabilities"),*in=nj_get(answer,"input"),*e=nj_get(answer,"execution"),*m=nj_get(answer,"model");
    r->predicted=field(nj_get(answer,"choice"),"verdict");
    long long version;if(nj_int(nj_get(answer,"schema_version"),&version) || version!=1)return 1;
    if(!r->id || !*r->id || !r->family || !*r->family || !r->split ||
       (strcmp(r->split,"development") && strcmp(r->split,"transfer")) || !choice(r->expected) || !choice(r->predicted) ||
       !same(input,"id",r->id) || !same(answer,"id",r->id) ||
       nj_number(nj_get(p,"CONCERN"),&r->concern) || nj_number(nj_get(p,"CLEAN"),&r->clean) ||
       !isfinite(r->concern) || !isfinite(r->clean) || r->concern<0 || r->clean<0 || r->concern>1 || r->clean>1 ||
       fabs(r->concern+r->clean-1)>1e-6 || strcmp(r->predicted,r->concern>=r->clean?"CONCERN":"CLEAN"))return 1;
    const char*keys[]={"context","rule_excerpt","change_excerpt"};
    for(int i=0;i<3;i++){char*s=field(input,keys[i]);int ok=same(in,keys[i],s);free(s);if(!ok)return 1;}
    char*file=field(input,"file"),*ctx=field(input,"context"),*rule=field(input,"rule_excerpt"),*change=field(input,"change_excerpt");
    char*model=field(manifest,"model_id"),*revision=field(manifest,"revision"),*wh=field(manifest,"weights_sha256"),*th=field(manifest,"tokenizer_sha256");
    jov_review review={.id=r->id,.file=file,.context=ctx,.rule_excerpt=rule,.change_excerpt=change,.model=model,.revision=revision,
        .question="pending",.concern=r->concern,.clean=r->clean};
    char hash[65];int bad=jov_review_validate(&review) || !same(nj_get(answer,"scope"),"file",file) || !same(m,"id",model) ||
        !same(m,"revision",revision) || !same(e,"engine","NoTorch") || !same(e,"language","AML") || !same(e,"arithmetic","float32") ||
        !same(e,"weights_sha256",wh) || !same(e,"tokenizer_sha256",th) || hash_bytes(input,strlen(input),hash) || !same(e,"input_sha256",hash);
    if(!bad)bad=jov_verify_boundary_view(answer,input,r->id,ctx,rule,change,prepare,index,policy) || !same(answer,"question",am_get_var_text("question"));
    free(file);free(ctx);free(rule);free(change);free(model);free(revision);free(wh);free(th);return bad;
}
static void count(tally*t,const result*r) {
    t->total++;
    if(!strcmp(r->expected,r->predicted))t->correct++;
    else if(!strcmp(r->expected,"CONCERN"))t->missed_concern++;
    else t->false_concern++;
}
static void totals(FILE*f,const tally*t) {
    fprintf(f,"{\"total\":%d,\"correct\":%d,\"missed_concern\":%d,\"false_concern\":%d}",t->total,t->correct,t->missed_concern,t->false_concern);
}
static int file_hash(const char*path,char hash[65]) {
    size_t n=0;char*s=nj_load(path,&n);if(!s)return 1;
    int bad=hash_bytes(s,n,hash);free(s);return bad;
}
int main(int argc,char**argv) {
    const char *manifest_path = jov_manifest_option(&argc, argv);
    if(!manifest_path || argc!=5){fprintf(stderr,"Usage: %s [--model onejev|onejev1.6] EXPECTED.jsonl INPUTS.jsonl ANSWERS.jsonl PREPARE.aml\n",argv[0]);return 2;}
    FILE*g=fopen(argv[1],"rb"),*i=fopen(argv[2],"rb"),*a=fopen(argv[3],"rb");
    char*manifest=nj_load(manifest_path,NULL),*gold=NULL,*input=NULL,*answer=NULL;size_t gc=0,ic=0,ac=0;
    char gold_hash[65],input_hash[65],prepare_hash[65], readout[65]={0};
    result rows[MAX_CASES]={{0}};tally all={0},development={0},transfer={0};int rc=1,n=0,read,policy=0;
    if(!g || !i || !a || !manifest || file_hash(argv[1],gold_hash) || file_hash(argv[2],input_hash) || file_hash(argv[4],prepare_hash))goto done;
    am_init();am_persistent_mode(1);
    while((read=line(g,&gold,&gc))==1) {
        if(n==MAX_CASES || line(i,&input,&ic)!=1 || line(a,&answer,&ac)!=1 || report_readout(answer,n,readout) || validate(rows+n,gold,input,answer,manifest,argv[4],n,&policy))goto done;
        for(int j=0;j<n;j++)if(!strcmp(rows[n].id,rows[j].id))goto done;
        count(&all,rows+n);count(!strcmp(rows[n].split,"development")?&development:&transfer,rows+n);n++;
    }
    if(read<0 || !n || line(i,&input,&ic)!=0 || line(a,&answer,&ac)!=0)goto done;
    fputs("{\"schema\":\"jovovich.quality-score/1\",",stdout);json_field(stdout,"inputs_sha256",input_hash);fputc(',',stdout);
    json_field(stdout,"expected_sha256",gold_hash);fputc(',',stdout);json_field(stdout,"prepare_sha256",prepare_hash);
    if(policy){fputc(',',stdout);json_field(stdout,"boundary_policy","signed-int-comparison/1");}
    if(*readout){fputc(',',stdout);json_field(stdout,"readout_sha256",readout);}
    fputs(",\"all\":",stdout);totals(stdout,&all);
    fputs(",\"development\":",stdout);totals(stdout,&development);fputs(",\"transfer\":",stdout);totals(stdout,&transfer);
    fputs(",\"cases\":[",stdout);
    for(int j=0;j<n;j++) {
        result*r=rows+j;if(j)fputc(',',stdout);fputc('{',stdout);
        json_field(stdout,"id",r->id);fputc(',',stdout);json_field(stdout,"split",r->split);fputc(',',stdout);json_field(stdout,"family",r->family);
        fputc(',',stdout);json_field(stdout,"expected",r->expected);fputc(',',stdout);json_field(stdout,"predicted",r->predicted);
        fprintf(stdout,",\"probabilities\":{\"CONCERN\":%.17g,\"CLEAN\":%.17g}}",r->concern,r->clean);
    }
    fputs("]}\n",stdout);rc=ferror(stdout) || fflush(stdout);
done:
    if(rc)fprintf(stderr,"Invalid or incomplete quality run at case %d\n",n+1);
    if(g)fclose(g);
    if(i)fclose(i);
    if(a)fclose(a);
    for(int j=0;j<MAX_CASES;j++){free(rows[j].id);free(rows[j].split);free(rows[j].family);free(rows[j].expected);free(rows[j].predicted);}
    free(gold);free(input);free(answer);free(manifest);am_persistent_mode(0);return rc?1:0;
}
