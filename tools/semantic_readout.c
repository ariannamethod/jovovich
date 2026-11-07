/* Fit the binary output adapter or score a paired frozen-backbone run. */
#include "hash.h"
#include "json.h"
#include "readout.h"
#include "report_json.h"
#include "notorch.h"
#include "harness/runtime.h"
#include <math.h>

enum { TRAIN_ROWS=128, MAX_ROWS=256, STEPS=400 };
static const float learning_rate=1.0f, l2=0.005f;

typedef struct { char *data, *cursor; char hash[65]; } lines;
typedef struct {
    char *id, *family;
    int concern;
    float base, adjusted, base_probs[2], adapted_probs[2], unit[JOV_WIDTH];
} example;

static void fail(const char *why) {fprintf(stderr,"%s\n",why);exit(1);}

static lines open_lines(const char *path) {
    size_t size=0;
    lines file={0};
    file.data=nj_load(path,&size);
    if (!file.data || hash_bytes(file.data,size,file.hash)) fail("Cannot read dataset");
    file.cursor=file.data;
    return file;
}

static char *next_row(lines *file, char digest[65]) {
    char *start=file->cursor;
    if (!*start) return NULL;
    char *end=strchr(start,'\n');
    if (!end || end-start>1048576) fail("Expected a bounded newline-terminated JSON row");
    if (digest && hash_bytes(start,(size_t)(end-start)+1,digest)) fail("Cannot hash input");
    *end=0;
    file->cursor=end+1;
    const char *tail=report_json_end(start,0);
    if (!tail || *nj_ws(tail)) fail("Invalid JSON row");
    return start;
}

static int load_examples(example *rows, lines *inputs, lines *features, lines *expected,
                         const char *weights, const char *tokenizer) {
    int n=0;
    char input_hash[65], *input;
    while ((input=next_row(inputs,input_hash))) {
        if (n==MAX_ROWS) fail("Too many examples");
        example *row=rows+n;
        const char *feat=next_row(features,NULL);
        row->id=nj_string(nj_get(input,"id"));
        if (!feat || !row->id || !*row->id || !nj_is(nj_get(feat,"id"),row->id) ||
            !nj_is(nj_get(feat,"schema"),"jovovich.features/1") ||
            !nj_is(nj_get(feat,"weights_sha256"),weights) ||
            !nj_is(nj_get(feat,"tokenizer_sha256"),tokenizer) ||
            !nj_is(nj_get(feat,"input_sha256"),input_hash))
            fail("Feature provenance differs from the input or model");
        for (int i=0; i<n; i++) if (!strcmp(rows[i].id,row->id)) fail("Duplicate input ID");
        double a,b,norm=0;
        if (nj_number(nj_get(feat,"logit_a"),&a) || nj_number(nj_get(feat,"logit_b"),&b) ||
            !isfinite((float)a) || !isfinite((float)b) || jov_readout_vector(nj_get(feat,"hidden"),row->unit))
            fail("Invalid logits or feature vector");
        row->base=(float)a-(float)b;
        for (int j=0; j<JOV_WIDTH; j++) norm+=(double)row->unit[j]*row->unit[j];
        if (!isfinite(row->base) || fabs(norm-1)>1e-5) fail("Invalid margin or feature norm");
        if (expected) {
            const char *label=next_row(expected,NULL);
            if (!label || !nj_is(nj_get(label,"id"),row->id)) fail("Expected ID mismatch");
            row->family=nj_string(nj_get(label,"family"));
            row->concern=nj_is(nj_get(label,"expected"),"CONCERN");
            if (!row->family || (!row->concern && !nj_is(nj_get(label,"expected"),"CLEAN")))
                fail("Invalid expectation");
        } else {
            long long token;
            row->concern=nj_is(nj_get(input,"completion"),"A");
            if ((!row->concern && !nj_is(nj_get(input,"completion"),"B")) ||
                nj_int(nj_get(input,"completion_token_id"),&token) || token!=(row->concern?32:33))
                fail("Invalid training target");
        }
        n++;
    }
    if (!n || *features->cursor || (expected && *expected->cursor)) fail("Dataset lengths differ or empty");
    return n;
}

static double probability(double margin) {
    double e=exp(-fabs(margin));
    return margin>=0 ? 1/(1+e) : e/(1+e);
}

static void fit(jov_readout *head, example *rows) {
    double sum=0;
    for (int j=0; j<JOV_WIDTH; j++) {
        double center=0;
        for (int i=0; i<TRAIN_ROWS; i++) center+=rows[i].unit[j];
        head->center[j]=(float)(center/TRAIN_ROWS);
        for (int i=0; i<TRAIN_ROWS; i++) {
            float d=rows[i].unit[j]-head->center[j];
            sum+=(double)d*d;
        }
    }
    head->scale=(float)sqrt(sum/TRAIN_ROWS);
    if (!(head->scale>0)) fail("Degenerate training features");
    for (int i=0; i<TRAIN_ROWS; i++)
        for (int j=0; j<JOV_WIDTH; j++) rows[i].unit[j]=(rows[i].unit[j]-head->center[j])/head->scale;

    for (int step=0; step<=STEPS; step++) {
        float grad[JOV_WIDTH+1]={0}, next[JOV_WIDTH+1];
        double loss=0;
        int correct=0;
        for (int k=0; k<TRAIN_ROWS; k++) {
            /* A full permutation of the 128 rows, identical for each full batch. */
            example *r=rows+((73*k+17)%TRAIN_ROWS);
            float delta;
            if (nt_linear_values(head->weight,head->weight+JOV_WIDTH,r->unit,1,JOV_WIDTH,&delta))
                fail("NoTorch projected a non-finite training value");
            float z=r->base+delta;
            double signed_margin=r->concern?z:-z;
            loss+=fmax(0,-signed_margin)+log1p(exp(-fabs(signed_margin)));
            correct+=(z>=0)==r->concern;
            float error=(float)((probability(z)-r->concern)/TRAIN_ROWS);
            for (int j=0; j<JOV_WIDTH; j++) grad[j]+=error*r->unit[j];
            grad[JOV_WIDTH]+=error;
        }
        if (step==0 || step==STEPS)
            fprintf(stderr,"step=%d mean_cross_entropy=%.9f correct=%d/%d\n",step,loss/TRAIN_ROWS,correct,TRAIN_ROWS);
        if (step==STEPS) break;
        for (int j=0; j<JOV_WIDTH; j++) grad[j]+=l2*head->weight[j];
        if (nt_sgd_values(head->weight,grad,JOV_WIDTH+1,learning_rate,next)) fail("NoTorch SGD failed");
        memcpy(head->weight,next,sizeof(next));
    }
}

static void vector(const float *v) {
    putchar('[');
    for (int i=0; i<JOV_WIDTH; i++) printf(i?",%.9g":"%.9g",v[i]);
    putchar(']');
}

static void write_adapter(const jov_readout *head, const char *weights, const char *tokenizer,
                          const char *train_hash, const char *features_hash) {
    printf("{\"schema\":\"jovovich.readout/1\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",",weights,tokenizer);
    printf("\"train_sha256\":\"%s\",\"train_features_sha256\":\"%s\",",train_hash,features_hash);
    printf("\"steps\":%d,\"learning_rate\":%.9g,\"l2\":%.9g,\"scale\":%.9g,\"bias\":%.9g,",
           STEPS,learning_rate,l2,head->scale,head->weight[JOV_WIDTH]);
    fputs("\"center\":",stdout);vector(head->center);
    fputs(",\"weight\":",stdout);vector(head->weight);puts("}");
}

static void compare(example *rows, int n, const jov_readout *head, const char *digest,
                    const lines *inputs, const lines *features, const lines *expected) {
    int base=0, adapted=0, lost_concerns=0;
    for (int i=0; i<n; i++) {
        example *r=rows+i;
        if (jov_readout_margin(head,r->unit,r->base,r->adapted_probs)) fail("Invalid readout projection");
        r->base_probs[0]=r->base;
        softmax(r->base_probs,2);
        softmax(r->adapted_probs,2);
        int was_concern=r->base_probs[0]>=r->base_probs[1];
        int is_concern=r->adapted_probs[0]>=r->adapted_probs[1];
        base+=was_concern==r->concern;
        adapted+=is_concern==r->concern;
        lost_concerns+=r->concern && was_concern && !is_concern;
    }
    printf("{\"schema\":\"jovovich.readout-score/1\",\"readout_sha256\":\"%s\",\n",digest);
    printf("\"inputs_sha256\":\"%s\",\"features_sha256\":\"%s\",\"expected_sha256\":\"%s\",\n",
           inputs->hash,features->hash,expected->hash);
    printf("\"rows\":%d,\"base_correct\":%d,\"readout_correct\":%d,\"lost_correct_concerns\":%d,\"cases\":[\n",
           n,base,adapted,lost_concerns);
    for (int i=0; i<n; i++) {
        example *r=rows+i;
        putchar('{');json_field(stdout,"id",r->id);putchar(',');json_field(stdout,"family",r->family);
        printf(",\"expected\":\"%s\",\"base_concern_probability\":%.9g,\"readout_concern_probability\":%.9g,"
               "\"base\":\"%s\",\"readout\":\"%s\"}%s\n",r->concern?"CONCERN":"CLEAN",r->base_probs[0],
               r->adapted_probs[0],r->base_probs[0]>=r->base_probs[1]?"CONCERN":"CLEAN",
               r->adapted_probs[0]>=r->adapted_probs[1]?"CONCERN":"CLEAN",i+1<n?",":"");
    }
    puts("]}");
}

/* Fixed experiment layout produced by tools/run_readout.sh. */
static lines in_directory(const char *dir, const char *name) {
    size_t len=strlen(dir)+strlen(name)+2;
    char *path=malloc(len);
    if (!path) fail("Cannot allocate path");
    snprintf(path,len,"%s/%s",dir,name);
    lines data=open_lines(path);
    free(path);
    return data;
}

typedef struct {
    int correct[3], pair_count, higher[2], matrix[4][4], ties[2];
    double shift[2];
    int classes[2];
} diagnostics;

static void individual(diagnostics *d, const example *r, double bias) {
    d->correct[0]+=(r->base>=0)==r->concern;
    d->correct[1]+=(r->base+bias>=0)==r->concern;
    d->correct[2]+=(r->adjusted>=0)==r->concern;
    d->shift[r->concern]+=r->adjusted-r->base;
    d->classes[r->concern]++;
}

static void pair(diagnostics *d, const example *clean, const example *broken) {
    if (clean->concern || !broken->concern) fail("Expected CLEAN, CONCERN pair order");
    d->pair_count++;
    int before=2*(clean->base>=0)+(broken->base>=0);
    int after=2*(clean->adjusted>=0)+(broken->adjusted>=0);
    d->matrix[before][after]++;
    d->higher[0]+=broken->base>clean->base;
    d->higher[1]+=broken->adjusted>clean->adjusted;
    d->ties[0]+=broken->base==clean->base;
    d->ties[1]+=broken->adjusted==clean->adjusted;
}

static void emit_diagnostics(const diagnostics *d) {
    printf("{\"correct_base_offset_head\":[%d,%d,%d],\"mean_head_shift_clean_concern\":[%.8g,%.8g]",
           d->correct[0],d->correct[1],d->correct[2],d->shift[0]/d->classes[0],d->shift[1]/d->classes[1]);
    if (d->pair_count) {
        printf(",\"pairs\":%d,\"violation_ranked_higher\":[%d,%d],\"ranking_ties\":[%d,%d],\"transitions\":[",
               d->pair_count,d->higher[0],d->higher[1],d->ties[0],d->ties[1]);
        for (int j=0;j<4;j++) printf("%s[%d,%d,%d,%d]",j?",":"",d->matrix[j][0],d->matrix[j][1],d->matrix[j][2],d->matrix[j][3]);
        putchar(']');
    }
    putchar('}');
}

/* The intercept-only control minimizes the same unregularized bias loss. */
static double fit_offset(const example *rows, int n) {
    double lo=-128, hi=128;
    for (int step=0;step<64;step++) {
        double b=(lo+hi)/2, grad=0;
        for (int i=0;i<n;i++) grad+=probability(rows[i].base+b)-rows[i].concern;
        if (grad>0) hi=b; else lo=b;
    }
    return (lo+hi)/2;
}

static int audit_method(const char *corpus, const char *dir, const char *swapped_path,
                        const char *adapter, const char *weights, const char *tokenizer) {
    jov_readout head;
    char digest[65];
    if (jov_readout_load(&head,adapter,weights,tokenizer,digest)) fail("Invalid audit checkpoint");
    char *manifest=nj_load("examples/semantic-20261107/manifest.json",NULL);
    const char *hashes=nj_get(manifest,"sha256");
    lines audit=in_directory(corpus,"audit.jsonl");
    if (!nj_is(nj_get(hashes,"audit.jsonl"),audit.hash)) fail("Unrecognized pair metadata");
    const char *suites[]={"train","transfer","legacy"};
    diagnostics totals[3][3]={0}; /* All, boundary, guard. */
    double bias=0;
    int swap_correct=0, swap_concerns=0, same_letter=0, same_verdict=0, averaged_correct=0;
    char swapped_hash[65];
    for (int s=0;s<3;s++) {
        const char *source=s==2?"examples/quality-20261106":corpus;
        const char *input_name=s==0?"train.jsonl":s==1?"eval-inputs.jsonl":"inputs.jsonl";
        lines inputs=in_directory(source,input_name), expected={0};
        if (s!=2 && !nj_is(nj_get(hashes,input_name),inputs.hash)) fail("Unexpected semantic split");
        if (s) expected=in_directory(source,s==1?"eval-expected.jsonl":"expected.jsonl");
        if (s==1 && !nj_is(nj_get(hashes,"eval-expected.jsonl"),expected.hash)) fail("Unexpected semantic labels");
        char feature_name[32];
        snprintf(feature_name,sizeof(feature_name),"%s.features",suites[s]);
        lines features=in_directory(dir,feature_name);
        example *rows=calloc(MAX_ROWS,sizeof(*rows));
        if (!rows) fail("Cannot allocate audit rows");
        int n=load_examples(rows,&inputs,&features,s?&expected:NULL,weights,tokenizer);
        if (n!=(s==0?128:s==1?64:38)) fail("Incomplete audit split");
        if (!s) bias=fit_offset(rows,n);
        char *pair_id=NULL;
        for (int i=0;i<n;i++) {
            example *r=rows+i;
            if (jov_readout_margin(&head,r->unit,r->base,&r->adjusted)) fail("Invalid projection");
            individual(&totals[s][0],r,bias);
            if (s==2) continue;
            char *meta=next_row(&audit,NULL);
            if (!meta || !nj_is(nj_get(meta,"id"),r->id) || !nj_is(nj_get(meta,"expected"),r->concern?"CONCERN":"CLEAN"))
                fail("Invalid pair metadata");
            int family=nj_is(nj_get(meta,"family"),"boundary")?1:2;
            if (family==2 && !nj_is(nj_get(meta,"family"),"guard")) fail("Unexpected family");
            individual(&totals[s][family],r,bias);
            if (i%2==0) {
                pair_id=nj_string(nj_get(meta,"pair_id"));
                if (!pair_id) fail("Missing pair ID");
            } else {
                if (!nj_is(nj_get(meta,"pair_id"),pair_id)) fail("Mismatched pair ID");
                pair(&totals[s][0],r-1,r);
                pair(&totals[s][family],r-1,r);
                free(pair_id);
            }
        }
        if (s==1) {
            lines swap=open_lines(swapped_path), si=in_directory(source,input_name), se=in_directory(source,"eval-expected.jsonl");
            if (!strcmp(swap.hash,features.hash)) fail("Identical original and swapped feature streams");
            memcpy(swapped_hash,swap.hash,sizeof(swapped_hash));
            example *rev=calloc(MAX_ROWS,sizeof(*rev));
            if (!rev || load_examples(rev,&si,&swap,&se,weights,tokenizer)!=n) fail("Malformed swapped-order run");
            for (int i=0;i<n;i++) {
                /* In the swapped prompt, B is CONCERN. Ties still pick token A. */
                int original=rows[i].base>=0, swapped=rev[i].base<0;
                same_letter+=original==!swapped;
                same_verdict+=original==swapped;
                swap_correct+=swapped==rows[i].concern;
                swap_concerns+=swapped;
                averaged_correct+=((rows[i].base-rev[i].base)>=0)==rows[i].concern;
                free(rev[i].id);free(rev[i].family);
            }
            free(rev);free(swap.data);free(si.data);free(se.data);
        }
        for (int i=0;i<n;i++) {free(rows[i].id);free(rows[i].family);}
        free(rows);free(inputs.data);free(expected.data);free(features.data);
    }
    if (*audit.cursor) fail("Extra semantic audit rows");
    printf("{\"schema\":\"jovovich.readout-diagnostics/1\",\"readout_sha256\":\"%s\",\n",digest);
    printf("\"intercept_only\":%.10g,\"pair_states\":[\"CLEAN/CLEAN\",\"CLEAN/CONCERN\",\"CONCERN/CLEAN\",\"CONCERN/CONCERN\"],\n",bias);
    for (int s=0;s<3;s++) {
        json_string(stdout,suites[s]);fputs(":{\"all\":",stdout);emit_diagnostics(&totals[s][0]);
        if (s!=2) {
            fputs(",\"boundary\":",stdout);emit_diagnostics(&totals[s][1]);
            fputs(",\"guard\":",stdout);emit_diagnostics(&totals[s][2]);
        }
        puts("},");
    }
    printf("\"order_control_base\":{\"swapped_features_sha256\":\"%s\",\"swapped_correct\":%d,\"swapped_concerns\":%d,"
           "\"same_letter\":%d,\"same_semantic_verdict\":%d,\"averaged_semantic_margin_correct\":%d}}\n",
           swapped_hash,swap_correct,swap_concerns,same_letter,same_verdict,averaged_correct);
    free(manifest);free(audit.data);
    return fflush(stdout)==EOF;
}

int main(int argc, char **argv) {
    int training=argc==4 && !strcmp(argv[1],"fit");
    int audit=argc==6 && !strcmp(argv[1],"audit");
    if (!training && !audit && !(argc==6 && !strcmp(argv[1],"score")))
        fail("Usage: jovovich-readout fit TRAIN FEATURES | score INPUTS FEATURES EXPECTED ADAPTER | audit CORPUS_DIR RUN_DIR SWAPPED_FEATURES ADAPTER");
    char *model=nj_load("models/onejev-0.8b.json",NULL);
    char *weights=nj_string(nj_get(model,"weights_sha256")), *tokenizer=nj_string(nj_get(model,"tokenizer_sha256"));
    if (!weights || !tokenizer) fail("Cannot read OneJev manifest");
    if (audit) {
        int rc=audit_method(argv[2],argv[3],argv[4],argv[5],weights,tokenizer);
        free(model);free(weights);free(tokenizer);return rc;
    }
    lines inputs=open_lines(argv[2]), features=open_lines(argv[3]), expected={0};
    jov_readout head={0};
    char digest[65];
    if (training) {
        char *manifest=nj_load("examples/semantic-20261107/manifest.json",NULL);
        if (!nj_is(nj_get(nj_get(manifest,"sha256"),"train.jsonl"),inputs.hash)) fail("Expected the pinned training split");
        free(manifest);
    } else {
        expected=open_lines(argv[4]);
        if (jov_readout_load(&head,argv[5],weights,tokenizer,digest)) fail("Cannot load compatible readout");
    }
    example *rows=calloc(MAX_ROWS,sizeof(*rows));
    if (!rows) fail("Cannot allocate examples");
    int n=load_examples(rows,&inputs,&features,training?NULL:&expected,weights,tokenizer);
    if (training) {
        if (n!=TRAIN_ROWS) fail("Wrong training size");
        fit(&head,rows);
        write_adapter(&head,weights,tokenizer,inputs.hash,features.hash);
    } else compare(rows,n,&head,digest,&inputs,&features,&expected);
    for (int i=0; i<n; i++) {free(rows[i].id);free(rows[i].family);}
    free(rows);free(model);free(weights);free(tokenizer);
    free(features.data);free(inputs.data);free(expected.data);
    return fflush(stdout)==EOF;
}
