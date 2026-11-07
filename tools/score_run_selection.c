/* Audit selector receipts and compare each gated live review to PR 51. */
#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "hash.h"
#include "report_json.h"
#include "run_selection.h"
#include <math.h>

enum { APIS=8, LAYOUTS=4, ROWS=APIS*LAYOUTS };
static const char *const archive="examples/execution-traces";
typedef struct {int mode,letter_a;double p_one;} pick;
typedef struct {int correct,pairs,false_alarms,misses;} tally;

static void fail(const char *message) {fprintf(stderr,"Run-selection score: %s\n",message);exit(1);}
static FILE *open_input(const char *dir,const char *file) {
    char path[4096];int n=snprintf(path,sizeof(path),"%s/%s",dir,file);
    FILE *f=(n>=0 && (size_t)n<sizeof(path))?fopen(path,"rb"):NULL;
    if(!f)fail(file);
    return f;
}
static char *next_row(FILE *f) {
    char *s=NULL;size_t size=0;ssize_t n=getline(&s,&size,f);
    if(n<1 || n>1048576 || memchr(s,0,(size_t)n))fail("missing or invalid row");
    const char *end=report_json_end(s,0);
    if(!end || *nj_ws(end))fail("invalid JSON");
    return s;
}
static void finish(FILE *f) {
    if(fgetc(f)!=EOF || ferror(f) || fclose(f))fail("extra rows or read failure");
}
static int integer(const char *row,const char *key,long long expected) {
    long long value;return !nj_int(nj_get(row,key),&value) && value==expected;
}
static double probability(const char *obj,const char *key) {
    double p;
    if(nj_number(nj_get(obj,key),&p) || !isfinite(p) || p<0 || p>1)fail("invalid probability");
    return p;
}
static void read_picks(const char *dir,pick picks[APIS][LAYOUTS]) {
    FILE *inputs=open_input(dir,"choices.jsonl"),*answers=open_input(dir,"choices-answers.jsonl");
    char *manifest=nj_load("models/onejev-0.8b.json",NULL);
    if(!manifest)fail("missing model manifest");
    char *weights=nj_string(nj_get(manifest,"weights_sha256")),*tokenizer=nj_string(nj_get(manifest,"tokenizer_sha256"));
    if(!weights || !tokenizer)fail("missing model bindings");
    for(int api=0;api<APIS;api++)for(int layout=0;layout<LAYOUTS;layout++) {
        char *in=next_row(inputs),*out=next_row(answers);char id[32],ih[65],ph[65];int mode_a;
        snprintf(id,sizeof(id),"select-%d-%d-%d",api,layout/2,layout%2);
        if(!nj_is(nj_get(in,"id"),id) || !nj_is(nj_get(out,"id"),id) ||
           !nj_is(nj_get(out,"schema"),"jovovich.run-choice/1") ||
           !nj_is(nj_get(out,"weights_sha256"),weights) || !nj_is(nj_get(out,"tokenizer_sha256"),tokenizer) ||
           hash_bytes(in,strlen(in),ih) || !nj_is(nj_get(out,"input_sha256"),ih) ||
           jov_prepare_selection(in,&mode_a) || mode_a!=layout%2)fail("selector provenance");
        const char *prompt=am_get_var_text("prompt");
        if(!prompt || hash_bytes(prompt,strlen(prompt),ph) || !nj_is(nj_get(out,"prompt_sha256"),ph))fail("selector prompt");
        double a=probability(out,"p_a"),b=probability(out,"p_b");
        int letter=a>=b,mode=letter?mode_a:1-mode_a;
        if(fabs(a+b-1)>1e-6 || !nj_is(nj_get(out,"letter"),letter?"A":"B") ||
           !integer(out,"selected_mode",mode))fail("selector choice");
        picks[api][layout]=(pick){mode,letter,mode_a?a:b};
        free(in);free(out);
    }
    finish(inputs);finish(answers);free(manifest);free(weights);free(tokenizer);
}
static void read_oracle(const char *dir,int modes[APIS]) {
    FILE *f=open_input(dir,"oracle-modes");
    for(int i=0;i<APIS;i++) {
        int c=fgetc(f);if(c!='0' && c!='1')fail("invalid compiled oracle");
        modes[i]=c-'0';
    }
    if(fgetc(f)!='\n')fail("invalid oracle length");
    finish(f);
}
static int score_choice(const char *row,const char *id,double p[2]) {
    const char *choice=nj_get(row,"choice"),*probs=nj_get(choice,"probabilities");
    p[0]=probability(probs,"CONCERN");p[1]=probability(probs,"CLEAN");
    int concern=p[0]>=p[1];
    if(!nj_is(nj_get(row,"id"),id) || fabs(p[0]+p[1]-1)>1e-6 ||
       !nj_is(nj_get(choice,"verdict"),concern?"CONCERN":"CLEAN"))fail("invalid review choice");
    return concern;
}
static void check_live(const char *answer,const char *old,int differing,int mode,int runs,const char *id) {
    double p[2],prior[2];
    int chosen=score_choice(answer,id,p),before=score_choice(old,id,prior);
    if(chosen!=before || (float)p[0]!=(float)prior[0] || (float)p[1]!=(float)prior[1])fail("F32 replay mismatch");
    const char *e=nj_get(answer,"execution"),*t=nj_get(e,"trace_witness");
    if(nj_get(e,"readout_sha256") || nj_get(e,"boundary_view") || !nj_is(nj_get(t,"policy"),"paired-trace-diff/1") ||
       !integer(t,"differing",differing) || !integer(t,"runs",runs) ||
       (differing?!integer(t,"selected_mode",mode):nj_get(t,"selected_mode")!=NULL))fail("trace gate decision");
    char *ctx=nj_string(nj_get(nj_get(old,"input"),"context"));char h[65];
    if(!ctx || am_set_var_text("review_context",ctx) || am_exec_file("aml/prepare.aml"))fail("archive context");
    const char *prompt=am_get_var_text("prompt");
    if(!prompt || hash_bytes(prompt,strlen(prompt),h) || !nj_is(nj_get(t,"prompt_sha256"),h))fail("archive prompt mismatch");
    free(ctx);
}
static void downstream(const char *dir,pick picks[APIS][LAYOUTS],const int modes[APIS],tally totals[4]) {
    const char *files[]={"source-answers.jsonl","control-answers.jsonl","witness-answers.jsonl",
                         "selected-answers.jsonl","mechanical-answers.jsonl"};
    FILE *streams[5];int prev[4]={0};
    for(int j=0;j<5;j++)streams[j]=open_input(j<3?archive:dir,files[j]);
    for(int i=0;i<ROWS;i++) {
        char id[24],*rows[5];int verdicts[5];double p[2];
        snprintf(id,sizeof(id),"trace-%02d",i);
        for(int j=0;j<5;j++){rows[j]=next_row(streams[j]);verdicts[j]=score_choice(rows[j],id,p);}
        int mode=modes[i/4],found=picks[i/4][0].mode==mode;
        check_live(rows[3],rows[found?2:0],found,mode,1,id);
        check_live(rows[4],rows[2],1,mode,2,id);
        int expected=i%4==1 || i%4==2;
        int verdict[]={verdicts[0],verdicts[found?2:1],verdicts[3],verdicts[4]};
        for(int j=0;j<4;j++) {
            int ok=verdict[j]==expected;
            totals[j].correct+=ok;totals[j].false_alarms+=!ok && !expected;totals[j].misses+=!ok && expected;
            if(i%2)totals[j].pairs+=ok && prev[j];
            prev[j]=ok;
        }
        for(int j=0;j<5;j++)free(rows[j]);
    }
    for(int j=0;j<5;j++)finish(streams[j]);
}
static void report(const char *dir,pick picks[APIS][LAYOUTS],const int modes[APIS]) {
    tally totals[4]={{0}};
    downstream(dir,picks,modes,totals);
    int correct[LAYOUTS]={0},robust[2]={0},letter_a=0,stable=0,option_flips=0,body_flips=0;
    double brier=0;
    puts("{\"schema\":\"jovovich.run-selection-score/1\",\"fixtures\":[");
    for(int i=0;i<APIS;i++) {
        int all=1,same=1;
        printf("{\"index\":%d,\"witness_mode\":%d,\"selected_modes\":[",i,modes[i]);
        for(int j=0;j<LAYOUTS;j++) {
            pick x=picks[i][j];int ok=x.mode==modes[i];double error=x.p_one-modes[i];
            brier+=error*error;letter_a+=x.letter_a;correct[j]+=ok;
            all&=ok;same&=x.mode==picks[i][0].mode;
            if(j%2)option_flips+=x.mode!=picks[i][j-1].mode;
            if(j>=2)body_flips+=x.mode!=picks[i][j-2].mode;
            printf("%s%d",j?",":"",x.mode);
        }
        printf("]}%s\n",i+1==APIS?"":",");robust[i/4]+=all;stable+=same;
    }
    int passed=robust[0]>=3 && robust[1]>=3 && robust[0]+robust[1]>=7;
    printf("],\"layout_correct\":[%d,%d,%d,%d],\"robust_order\":%d,\"robust_count\":%d,"
           "\"stable_apis\":%d,\"letter_a\":%d,\"option_swap_mode_changes\":%d,\"body_swap_mode_changes\":%d,"
           "\"binary_brier\":%.10g,\"passes_selector_criterion\":%s,\n\"downstream\":[\n",
           correct[0],correct[1],correct[2],correct[3],robust[0],robust[1],stable,letter_a,option_flips,body_flips,
           brier/ROWS,passed?"true":"false");
    const char *names[]={"source","selector_unfiltered","selector_gated","mechanical"};
    for(int i=0;i<4;i++) {
        tally t=totals[i];
        printf("{\"name\":\"%s\",\"correct\":%d,\"pairs\":%d,\"false_alarms\":%d,\"misses\":%d}%s\n",
               names[i],t.correct,t.pairs,t.false_alarms,t.misses,i==3?"":",");
    }
    puts("]}");
}

int main(int argc,char **argv) {
    if(argc!=3 || (strcmp(argv[1],"modes") && strcmp(argv[1],"score")))fail("expected modes|score RUN_DIRECTORY");
    pick picks[APIS][LAYOUTS];int modes[APIS];am_init();am_persistent_mode(1);
    read_picks(argv[2],picks);
    if(!strcmp(argv[1],"modes")) {
        for(int i=0;i<APIS;i++)fputc('0'+picks[i][0].mode,stdout);
        puts("");
    } else {read_oracle(argv[2],modes);report(argv[2],picks,modes);}
    am_persistent_mode(0);return fflush(stdout)==EOF || ferror(stdout);
}
