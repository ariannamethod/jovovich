/* Reduce four validated score-quality runs to the preregistered crossover metrics. */
#include "report_json.h"
#include <math.h>
#include <stdio.h>

enum { ARMS=4, CASES=32, PER_FAMILY=16 };
static const char *const arm_names[]={"source","control","observed","witness"};

typedef struct {
    int correct, fixed, lost, false_alarms, misses, mutation_pairs, rule_pairs, fixtures;
} tally;

static void fail(const char *message) {
    fprintf(stderr,"Trace score: %s\n",message);
    exit(EXIT_FAILURE);
}

static void read_score(const char *path,int decisions[CASES],char input_sha[65],char expected_sha[65],char prepare_sha[65],int arm,const char *manifest) {
    char *score=nj_load(path,NULL);
    if(!score)fail("could not open score");
    const char *end=report_json_end(score,0);
    if(!end || *nj_ws(end) || !nj_is(nj_get(score,"schema"),"jovovich.quality-score/1") ||
       nj_get(score,"readout_sha256") || nj_get(score,"boundary_policy"))fail("expected plain frozen-base score");
    const char *keys[]={"inputs_sha256","expected_sha256","prepare_sha256"};
    char *hashes[]={input_sha,expected_sha,prepare_sha};
    for(int k=0;k<3;k++) {
        char *value=nj_string(nj_get(score,keys[k]));
        const char *pinned=k==0 ? nj_get(nj_get(manifest,keys[k]),arm_names[arm]) : nj_get(manifest,keys[k]);
        if(!value || strlen(value)!=64 || strspn(value,"0123456789abcdef")!=64 ||
           !nj_is(pinned,value))fail("inconsistent score provenance");
        memcpy(hashes[k],value,65);
        free(value);
    }
    int n=0,bad=0;
    for(const char *row=nj_first(nj_get(score,"cases"),&bad);row;row=nj_next(row,']',&bad)) {
        char id[16];
        snprintf(id,sizeof(id),"trace-%02d",n);
        int violation=n%4==1 || n%4==2;
        if(n>=CASES || !nj_is(nj_get(row,"id"),id) || !nj_is(nj_get(row,"expected"),violation?"CONCERN":"CLEAN") ||
           !nj_is(nj_get(row,"split"),"transfer") || !nj_is(nj_get(row,"family"),n<PER_FAMILY?"order":"count"))
            fail("incomplete or misaligned crossover");
        const char *prob=nj_get(row,"probabilities");
        double concern,clean;
        if(nj_number(nj_get(prob,"CONCERN"),&concern) || nj_number(nj_get(prob,"CLEAN"),&clean) ||
           !isfinite(concern) || !isfinite(clean) || concern<0 || concern>1 || clean<0 || clean>1 ||
           fabs(concern+clean-1)>1e-6 || !nj_is(nj_get(row,"predicted"),concern>=clean?"CONCERN":"CLEAN"))
            fail("invalid probabilities or verdict");
        decisions[n++]=concern>=clean;
    }
    if(bad || n!=CASES)fail("expected 32 reviews per arm");
    free(score);
}

static tally summarize(const int predictions[CASES],const int baseline[CASES],int first,int last) {
    tally t={0};
    for(int g=first;g<last;g+=4) {
        int ok[4];
        for(int j=0;j<4;j++) {
            int violation=j==1 || j==2;
            int i=g+j,was=baseline[i]==violation;
            ok[j]=predictions[i]==violation;
            t.correct+=ok[j];t.fixed+=ok[j] && !was;t.lost+=!ok[j] && was;
            t.false_alarms+=!ok[j] && !violation;t.misses+=!ok[j] && violation;
        }
        t.mutation_pairs+=(ok[0] && ok[1])+(ok[2] && ok[3]);
        t.rule_pairs+=(ok[0] && ok[2])+(ok[1] && ok[3]);
        t.fixtures+=ok[0] && ok[1] && ok[2] && ok[3];
    }
    return t;
}

static void print_tally(tally t) {
    printf("{\"correct\":%d,\"mutation_pairs\":%d,\"rule_pairs\":%d,\"complete_fixtures\":%d,"
           "\"false_alarms\":%d,\"misses\":%d,\"fixed_vs_source\":%d,\"lost_vs_source\":%d}",
           t.correct,t.mutation_pairs,t.rule_pairs,t.fixtures,t.false_alarms,t.misses,t.fixed,t.lost);
}

int main(int argc,char **argv) {
    if(argc!=5)fail("expected four score paths in source, control, observed, witness order");
    int predictions[ARMS][CASES];
    char inputs[ARMS][65],expected_sha[65],prepare_sha[65];
    char *manifest=nj_load("examples/execution-traces/manifest.json",NULL);
    if(!manifest)fail("missing corpus manifest");
    for(int a=0;a<ARMS;a++)
        read_score(argv[a+1],predictions[a],inputs[a],expected_sha,prepare_sha,a,manifest);
    free(manifest);
    int complete_pairs[ARMS];
    int families_pass=0;
    printf("{\"schema\":\"jovovich.trace-score/1\",\"expected_sha256\":\"%s\",\"prepare_sha256\":\"%s\",\n\"arms\":[\n",
           expected_sha,prepare_sha);
    for(int a=0;a<ARMS;a++) {
        tally order=summarize(predictions[a],predictions[0],0,PER_FAMILY);
        tally count=summarize(predictions[a],predictions[0],PER_FAMILY,CASES);
        tally both=summarize(predictions[a],predictions[0],0,CASES);
        complete_pairs[a]=both.mutation_pairs;
        if(a==3)families_pass=order.mutation_pairs>=7 && count.mutation_pairs>=7;
        printf("{\"name\":\"%s\",\"inputs_sha256\":\"%s\",\"all\":",arm_names[a],inputs[a]);
        print_tally(both);fputs(",\"order\":",stdout);print_tally(order);
        fputs(",\"count\":",stdout);print_tally(count);puts(a+1==ARMS?"}":"},");
    }
    int passes=families_pass && complete_pairs[3]>complete_pairs[0] && complete_pairs[3]>complete_pairs[1];
    printf("],\"passes_prespecified_transfer\":%s}\n",passes?"true":"false");
    return fflush(stdout)==EOF || ferror(stdout);
}
