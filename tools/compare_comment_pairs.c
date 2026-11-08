/* Reduce two runs after their Git reports and carryover scores have been verified. */
#include "report_json.h"
#include <math.h>

enum { MODELS = 2, ARMS = 2, PAIRS = 8, CONTROLS = 32 };
typedef struct {
    double p;
    char input[65], prompt[65];
    int has_trace, differing, concern;
} vote;
typedef struct { int pairs, alarms, misses; double squared_error; } score;
static const char *const names[MODELS] = {"original", "onejev1.6"};
static const char *const arms[ARMS] = {"source", "gated"};

static void stop(const char *reason) { fprintf(stderr, "Checkpoint comparison: %s\n", reason); exit(1); }
static void digest(const char *obj, const char *key, char value[65]) {
    char *s = nj_string(nj_get(obj,key));
    if (!s || strlen(s)!=64 || strspn(s,"0123456789abcdef")!=64) stop("missing digest");
    memcpy(value,s,65); free(s);
}
static char *row(FILE *f) {
    size_t bytes = 0; int bad = 0;
    char *s = report_json_row(f,&bytes,&bad,1048576,1048576);
    if (bad) stop("malformed input");
    return s;
}
static vote read_vote(FILE *f) {
    vote v = {0};
    char *s = row(f);
    if (!s) stop("short run");
    const char *e=nj_get(s,"execution"), *view=nj_get(e,"boundary_view"), *trace=nj_get(e,"trace_witness");
    const char *choice=nj_get(s,"choice"), *p=nj_get(choice,"probabilities");
    if (nj_get(e,"readout_sha256") || nj_number(nj_get(p,"CONCERN"),&v.p) ||
        !isfinite(v.p) || v.p<0 || v.p>1) stop("invalid base vote");
    v.concern=nj_is(nj_get(choice,"verdict"),"CONCERN");
    if (!v.concern && !nj_is(nj_get(choice,"verdict"),"CLEAN")) stop("missing verdict");
    digest(e,"input_sha256",v.input); digest(view,"prompt_sha256",v.prompt);
    v.has_trace=trace!=NULL;
    if (trace) {
        long long n;
        if (nj_int(nj_get(trace,"differing"),&n) || n<0 || n>64) stop("invalid trace count");
        v.differing=(int)n;
    }
    free(s); return v;
}
static void read_both(FILE *runs[MODELS], vote pair[MODELS]) {
    for (int m=0;m<MODELS;m++) pair[m]=read_vote(runs[m]);
    if (strcmp(pair[0].input,pair[1].input) || strcmp(pair[0].prompt,pair[1].prompt) ||
        pair[0].has_trace!=pair[1].has_trace || pair[0].differing!=pair[1].differing)
        stop("model inputs or prompts differ");
}

int main(int argc, char **argv) {
    if (argc!=6) {
        fprintf(stderr,"Usage: %s INDEX.tsv CARRYOVER-EXPECTED.jsonl ORIGINAL.jsonl CANDIDATE.jsonl DRAW-REFERENCE.json\n",argv[0]);return 2;
    }
    FILE *index=fopen(argv[1],"r"), *gold=fopen(argv[2],"r");
    FILE *runs[MODELS]={fopen(argv[3],"r"),fopen(argv[4],"r")};
    if (!index || !gold || !runs[0] || !runs[1]) stop("missing input");
    char line[128];
    if (!fgets(line,sizeof(line),index) || strcmp(line,"pair\tfamily\texpected\tarm\tmode\n")) stop("invalid index header");
    score scores[MODELS][ARMS]={0};
    double gated[PAIRS][MODELS][2]={0};
    for (int i=0;i<PAIRS;i++) {
        int false_alarm[MODELS][ARMS]={0};
        for (int violation=0;violation<2;violation++) {
            vote source[MODELS]={{0}};
            for (int arm=0;arm<ARMS;arm++) {
                char family[16],expected[16],arm_name[16]; int group,mode;
                if (!fgets(line,sizeof(line),index) || sscanf(line,"%d %15s %15s %15s %d",&group,family,expected,arm_name,&mode)!=5 ||
                    group!=i+1 || strcmp(family,i<4?"order":"count") || strcmp(expected,violation?"CONCERN":"CLEAN") ||
                    strcmp(arm_name,arms[arm]) || (mode!=0 && mode!=1)) stop("unexpected pair layout");
                vote pair[MODELS];read_both(runs,pair);
                for (int m=0;m<MODELS;m++) {
                    vote v=pair[m];score *t=&scores[m][arm];
                    if (v.has_trace!=arm || v.differing!=(arm && violation)) stop("unexpected gate decision");
                    if (!arm) source[m]=v;
                    else {
                        if (!violation && (strcmp(v.prompt,source[m].prompt) || v.p!=source[m].p || v.concern!=source[m].concern))
                            stop("a shared effect changed the verdict or prompt");
                        gated[i][m][violation]=v.p;
                    }
                    if (!violation) { false_alarm[m][arm]=v.concern; t->alarms+=v.concern; }
                    else { t->misses+=!v.concern; t->pairs+=!false_alarm[m][arm] && v.concern; }
                    t->squared_error+=(v.p-violation)*(v.p-violation);
                }
            }
        }
    }
    if (fgets(line,sizeof(line),index) || ferror(index)) stop("extra index rows");
    vote anchor[MODELS], repair[MODELS]; read_both(runs,anchor);
    if (fabs(anchor[0].p-0.6640163064)>0.0002) stop("PR 55 anchor changed");
    int correct[MODELS]={0};
    for (int i=0;i<CONTROLS;i++) {
        vote pair[MODELS]; read_both(runs,pair);
        char *g=row(gold);
        if (!g) stop("missing carryover label");
        int target=nj_is(nj_get(g,"expected"),"CONCERN");
        if (!target && !nj_is(nj_get(g,"expected"),"CLEAN")) stop("invalid carryover label");
        for (int m=0;m<MODELS;m++) correct[m]+=pair[m].concern==target;
        free(g);
    }
    read_both(runs,repair);
    char *reference=nj_load(argv[5],NULL);
    int bad=0; double independent;
    const char *probabilities=nj_get(reference,"probabilities");
    const char *first=nj_first(probabilities,&bad);
    if (!reference || !nj_is(nj_get(reference,"schema"),"jovovich.f32-reference/1") ||
        !nj_is(nj_get(reference,"prompt_sha256"),repair[1].prompt) || bad || !first ||
        nj_number(first,&independent) || !isfinite(independent) || fabs(repair[1].p-independent)>0.0002)
        stop("candidate differs from the independent F32 repair reference");
    free(reference);
    if (row(gold) || row(runs[0]) || row(runs[1]) || correct[0]!=CONTROLS) stop("carryover size or reference changed");
    score old=scores[0][1], newer=scores[1][1];
    int qualifies=newer.pairs>old.pairs && newer.alarms<old.alarms && newer.misses<=old.misses && correct[1]==CONTROLS;
    puts("{\"schema\":\"jovovich.checkpoint-comparison/1\",\"arms\":[");
    for (int m=0;m<MODELS;m++) for (int arm=0;arm<ARMS;arm++) {
        score t=scores[m][arm];
        printf("{\"model\":\"%s\",\"arm\":\"%s\",\"both_correct\":%d,\"false_alarms\":%d,\"misses\":%d,\"brier\":%.9f}%s\n",
               names[m],arms[arm],t.pairs,t.alarms,t.misses,t.squared_error/(2*PAIRS),m==1 && arm==1?"":",");
    }
    puts("],\"gated_pairs\":[");
    for (int i=0;i<PAIRS;i++) printf("{\"pair\":%d,\"family\":\"%s\",\"original\":[%.9g,%.9g],\"onejev1.6\":[%.9g,%.9g]}%s\n",
        i+1,i<4?"order":"count",gated[i][0][0],gated[i][0][1],gated[i][1][0],gated[i][1][1],i+1==PAIRS?"":",");
    printf("],\"anchor_p_concern\":[%.9g,%.9g],\"draw_repair_p_concern\":[%.9g,%.9g],\"carryover_correct\":[%d,%d],\"qualifies_for_wider_trial\":%s}\n",
           anchor[0].p,anchor[1].p,repair[0].p,repair[1].p,correct[0],correct[1],qualifies?"true":"false");
    fclose(index);fclose(gold);fclose(runs[0]);fclose(runs[1]);
    return ferror(stdout) || fflush(stdout);
}
