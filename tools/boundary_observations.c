/* Score the predeclared 2-by-3 within-case observation experiment. */
#define _POSIX_C_SOURCE 200809L
#include "boundary.h"
#include "report_json.h"
#include "hash.h"
#include "json.h"
#include "ariannamethod.h"
#include <math.h>

enum { ROWS=96, ARMS=3, HEADS=2 };
static const char *const arm_names[]={"none","boundary","adjacent"};
typedef struct { char prompt[65],input[65];double p[HEADS];int concern[HEADS]; } decision;
typedef struct { int correct,pairs,stable,groups,false_alarms,misses,fixed,broken;double p_sum[2]; } tally;

static void fail(const char *s){fprintf(stderr,"Observation score: %s\n",s);exit(1);}
static char *load(const char *dir,const char *name,char hash[65]) {
    char path[4096];size_t size;
    if(snprintf(path,sizeof(path),"%s/%s",dir,name)>=(int)sizeof(path))fail("path too long");
    char *data=nj_load(path,&size);
    if(!data || (hash && hash_bytes(data,size,hash)))fail("unreadable input");
    return data;
}
static char *field(const char *obj,const char *name) {
    char *s=nj_string(nj_get(obj,name));if(!s)fail("missing string");return s;
}
static void prompt_hash(const char *context,char hash[65]) {
    if(am_set_var_text("review_context",context) || am_exec_file("aml/prepare.aml"))fail("AML prepare failed");
    const char *prompt=am_get_var_text("prompt");
    if(!prompt || hash_bytes(prompt,strlen(prompt),hash))fail("missing AML prompt");
}
static void read_arm(int arm,const char *corpus,const char *run,const char *gold_hash,
                     const char *head_hash,decision rows[ROWS],char input_hash[65],char feature_hash[65]) {
    char path[64];snprintf(path,sizeof(path),"%s.jsonl",arm_names[arm]);
    char *inputs=load(arm?run:corpus,arm?path:"eval-inputs.jsonl",input_hash),*next=inputs;
    snprintf(path,sizeof(path),"%s-score.json",arm_names[arm]);
    char *score=load(run,path,NULL);
    const char *end=report_json_end(score,0);
    if(!end || *nj_ws(end) || !nj_is(nj_get(score,"schema"),"jovovich.readout-score/1") ||
       !nj_is(nj_get(score,"inputs_sha256"),input_hash) || !nj_is(nj_get(score,"expected_sha256"),gold_hash) ||
       !nj_is(nj_get(score,"readout_sha256"),head_hash))fail("score provenance mismatch");
    char *fh=field(score,"features_sha256");
    if(strlen(fh)!=64 || strspn(fh,"0123456789abcdef")!=64)fail("invalid feature digest");
    memcpy(feature_hash,fh,65);free(fh);
    int bad=0,n=0;char *direct[2]={0};
    for(const char *c=nj_first(nj_get(score,"cases"),&bad);c;c=nj_next(c,']',&bad)) {
        if(n>=ROWS)fail("extra cases");
        char *input=next,*newline=strchr(input,'\n');if(!newline)fail("missing input row");
        if(hash_bytes(input,(size_t)(newline-input)+1,rows[n].input))fail("input digest");
        *newline=0;next=newline+1;
        char id[24];snprintf(id,sizeof(id),"equiv-%03d",128+n);
        if(!nj_is(nj_get(input,"id"),id) || !nj_is(nj_get(c,"id"),id) ||
           !nj_is(nj_get(c,"expected"),n%2?"CONCERN":"CLEAN"))fail("case misalignment");
        char *context=field(input,"context"),*rule=field(input,"rule_excerpt"),*change=field(input,"change_excerpt");
        if(n%8<2){free(direct[n%2]);direct[n%2]=strdup(context);if(!direct[n%2])fail("allocation");}
        char code[JOV_BOUNDARY_CODE_SIZE],*view=NULL;
        if(jov_boundary_context(context,rule,change,code,&view)!=1 || strcmp(view,direct[n%2]))
            fail("canonical context differs from its direct representative");
        prompt_hash(context,rows[n].prompt);
        char canonical_prompt[65];prompt_hash(view,canonical_prompt);
        if(strcmp(canonical_prompt,rows[n-n%8+n%2].prompt))fail("canonical prompt identity mismatch");
        for(int h=0;h<HEADS;h++) {
            double p;
            if(nj_number(nj_get(c,h?"readout_concern_probability":"base_concern_probability"),&p) ||
               !isfinite(p) || p<0 || p>1)fail("bad probability");
            const char *verdict=nj_get(c,h?"readout":"base");
            int concern=nj_is(verdict,"CONCERN");
            if((!concern && !nj_is(verdict,"CLEAN")) || (p>.5 && !concern) || (p<.5 && concern))fail("bad verdict");
            rows[n].p[h]=p;rows[n].concern[h]=concern;
        }
        free(view);free(context);free(rule);free(change);n++;
    }
    if(bad || n!=ROWS || *next)fail("incomplete score");
    free(direct[0]);free(direct[1]);free(inputs);free(score);
}

static void verify_live_group(const char *run,const decision boundary[ROWS]) {
    char *data=load(run,"canonical-live.jsonl",NULL),*next=data;
    for(int i=0;i<8;i++) {
        char *row=next,*newline=strchr(row,'\n');
        if(!newline)fail("incomplete live replay");
        *newline=0;next=newline+1;
        const char *end=report_json_end(row,0),*execution=nj_get(row,"execution");
        const char *view=nj_get(execution,"boundary_view"),*choice=nj_get(row,"choice");
        char id[24];snprintf(id,sizeof(id),"equiv-%03d",128+i);
        double p;
        if(!end || *nj_ws(end) || !nj_is(nj_get(row,"id"),id) || nj_get(execution,"readout_sha256") ||
           !nj_is(nj_get(execution,"input_sha256"),boundary[i].input) ||
           !nj_is(nj_get(view,"policy"),"signed-int-comparison/1") ||
           !nj_is(nj_get(view,"prompt_sha256"),boundary[i%2].prompt) ||
           !nj_is(nj_get(choice,"verdict"),boundary[i%2].concern[0]?"CONCERN":"CLEAN") ||
           nj_number(nj_get(nj_get(choice,"probabilities"),"CONCERN"),&p) ||
           (float)p!=(float)boundary[i%2].p[0])fail("live replay differs from the mapped model decision");
    }
    if(*next)fail("extra replay answer");
    free(data);
}

static tally count(decision rows[ROWS],decision control[ROWS],int canonical,int h) {
    tally t={0};
    for(int g=0;g<ROWS;g+=8) {
        int v[8],ok=0;
        for(int i=0;i<8;i++) {
            int j=g+(canonical?i%2:i),expected=i%2;
            v[i]=rows[j].concern[h];t.p_sum[expected]+=rows[j].p[h];
            int correct=v[i]==expected,was=control[j].concern[h]==expected;
            ok+=correct;t.fixed+=correct && !was;t.broken+=!correct && was;
            t.false_alarms+=!correct && !expected;t.misses+=!correct && expected;
        }
        t.correct+=ok;t.groups+=ok==8;
        for(int i=0;i<8;i+=2)t.pairs+=!v[i] && v[i+1];
        for(int i=0;i<2;i++)t.stable+=v[i]==v[i+2] && v[i]==v[i+4] && v[i]==v[i+6];
    }
    return t;
}
int main(int argc,char **argv) {
    if(argc!=3)fail("expected CORPUS_DIR RUN_DIR");
    char *manifest=load("examples/equivalent-boundaries","manifest.json",NULL);
    char *run=load("examples/equivalent-boundaries","run.json",NULL);
    char *gold=field(nj_get(manifest,"sha256"),"eval-expected.jsonl");
    char *head=field(nj_get(nj_get(run,"heads"),"files"),"experiments/equivalent-boundaries-20261107/paired.json");
    decision rows[ARMS][ROWS];char ih[ARMS][65],fh[ARMS][65];
    am_init();am_persistent_mode(1);
    for(int a=0;a<ARMS;a++)read_arm(a,argv[1],argv[2],gold,head,rows[a],ih[a],fh[a]);
    if(!nj_is(nj_get(nj_get(manifest,"sha256"),"eval-inputs.jsonl"),ih[0]))fail("unexpected base corpus");
    verify_live_group(argv[2],rows[1]);
    printf("{\"schema\":\"jovovich.boundary-observations/1\",\"paired_sha256\":\"%s\",\n\"arms\":[",head);
    for(int a=0;a<ARMS;a++)printf("%s{\"name\":\"%s\",\"inputs_sha256\":\"%s\",\"features_sha256\":\"%s\"}",a?",":"",arm_names[a],ih[a],fh[a]);
    puts("],\n\"results\":[");
    for(int h=0;h<HEADS;h++)for(int canonical=0;canonical<2;canonical++)for(int a=0;a<ARMS;a++) {
        tally t=count(rows[a],rows[0],canonical,h);
        tally neighbor=count(rows[a],rows[2],canonical,h);
        printf("{\"head\":\"%s\",\"view\":\"%s\",\"observation\":\"%s\",\"correct\":%d,\"pairs\":%d,"
               "\"stable\":%d,\"complete\":%d,\"false_alarms\":%d,\"misses\":%d,\"fixed_vs_none\":%d,\"broken_vs_none\":%d,"
               "\"fixed_vs_adjacent\":%d,\"broken_vs_adjacent\":%d,\"mean_p_clean_broken\":[%.9g,%.9g],\"mean_pair_probability_gap\":%.9g}%s\n",h?"paired":"base",canonical?"canonical":"raw",
               arm_names[a],t.correct,t.pairs,t.stable,t.groups,t.false_alarms,t.misses,t.fixed,t.broken,
               neighbor.fixed,neighbor.broken,t.p_sum[0]/48,t.p_sum[1]/48,(t.p_sum[1]-t.p_sum[0])/48,h==1 && canonical && a==2?"":",");
    }
    puts("],\"cases\":[");
    for(int i=0;i<ROWS;i++) {
        int j=i-i%8+i%2;
        printf("{\"id\":\"equiv-%03d\",\"canonical_representative\":\"equiv-%03d\",\"expected\":\"%s\",\"arms\":[",128+i,128+j,i%2?"CONCERN":"CLEAN");
        for(int a=0;a<ARMS;a++)printf("%s{\"raw_prompt_sha256\":\"%s\",\"canonical_prompt_sha256\":\"%s\","
            "\"raw_p_concern\":[%.9g,%.9g],\"canonical_p_concern\":[%.9g,%.9g]}",a?",":"",rows[a][i].prompt,rows[a][j].prompt,
            rows[a][i].p[0],rows[a][i].p[1],rows[a][j].p[0],rows[a][j].p[1]);
        printf("]}%s\n",i+1==ROWS?"":",");
    }
    puts("]}");am_persistent_mode(0);free(run);free(manifest);free(gold);free(head);
    return fflush(stdout)==EOF;
}
