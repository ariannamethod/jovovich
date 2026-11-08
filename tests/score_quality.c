/* Score a complete native review run against separately stored expectations. */
#define _POSIX_C_SOURCE 200809L
#include "review.h"
#include "json.h"
#include "boundary_view.h"
#include "hash.h"
#include "report_json.h"
#include "model_manifest.h"
#include "ariannamethod.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/stat.h>
#include <unistd.h>
#include <math.h>

#define MAX_CASES 256
#define ROW_LIMIT 1048576
#define THRESHOLD_PATH "aml/text-threshold.aml"
#define WITNESS_SHA256 "57bf72d22f5e3b463ba0112d0b58a574ea281da409fe381e4346694618d9c96e"
#define THRESHOLD_SHA256 "786c19fe38c9f2a0c8b48c6c3d378c50991d5cdbd9599e63377fb058d98e30d5"
typedef struct {
    char *id,*split,*family,*expected,*predicted;
    const char *scored;
    int threshold_applied;
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
    if(n>ROW_LIMIT || memchr(*s,0,(size_t)n))return -1;
    const char*end=report_json_end(*s,0);return end && !*nj_ws(end)?1:-1;
}
static int validate(result*r,const char*expected,const char*input,const char*answer,const char*manifest,const char*prepare,const char*prepare_source,const char*trace_source,int index,int *policy) {
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
    if(nj_get(input,"trace_evidence") && !trace_source)bad=1;
    if(!bad)bad=jov_verify_boundary_view_source(answer,input,r->id,ctx,rule,change,prepare,prepare_source,trace_source,index,policy,NULL) || !same(answer,"question",am_get_var_text("question"));
    free(file);free(ctx);free(rule);free(change);free(model);free(revision);free(wh);free(th);return bad;
}
static void count(tally*t,const result*r) {
    t->total++;
    if(!strcmp(r->expected,r->scored))t->correct++;
    else if(!strcmp(r->expected,"CONCERN"))t->missed_concern++;
    else t->false_concern++;
}
static void totals(FILE*f,const tally*t) {
    fprintf(f,"{\"total\":%d,\"correct\":%d,\"missed_concern\":%d,\"false_concern\":%d}",t->total,t->correct,t->missed_concern,t->false_concern);
}
/* A digest and a consumer share one owned byte buffer, never two opens of
 * the supplied pathname. Reject non-regular sources without blocking on a FIFO. */
typedef struct {char *text; size_t size; char hash[65];} snapshot;
static int capture(const char *path,size_t limit,snapshot *s) {
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    if(fd<0)return 1;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size<=0 || (uintmax_t)st.st_size>limit) {
        close(fd);return 1;
    }
    FILE *f=fdopen(fd,"rb");
    if(!f){close(fd);return 1;}
    s->size=(size_t)st.st_size;
    s->text=malloc(s->size+1);
    int bad=!s->text || fread(s->text,1,s->size,f)!=s->size ||
        fgetc(f)!=EOF || ferror(f) || memchr(s->text,0,s->size);
    if(fclose(f))bad=1;
    if(bad)return 1;
    s->text[s->size]=0;
    return hash_bytes(s->text,s->size,s->hash);
}

/* The ordinary receipt is verified first. Only its admitted text witness
 * can activate this alternative decision in the evaluation report. */
static int score_threshold(result *r, const char *input, const char *answer, float threshold, const char *threshold_source) {
    r->scored = r->predicted;
    if (threshold < 0) return 0;
    const char *metric = nj_get(nj_get(input, "trace_evidence"), "metric");
    const char *witness = nj_get(nj_get(answer, "execution"), "trace_witness");
    if (!nj_is(metric, "text") || !nj_get(witness, "selected_mode")) return 0;
    float point[] = {(float)r->concern, threshold};
    if (am_set_var_array("text_point", point, 2) || am_exec_source(threshold_source,THRESHOLD_PATH)) return 1;
    const char *decision = am_get_var_text("text_verdict");
    if (!choice(decision)) return 1;
    r->scored = !strcmp(decision, "CONCERN") ? "CONCERN" : "CLEAN";
    r->threshold_applied = 1;
    return 0;
}

int main(int argc,char**argv) {
    const char *manifest_path = jov_manifest_option(&argc, argv);
    const char *expected_prompts=NULL;
    if(argc>=3 && !strcmp(argv[1],"--expect-prompts")) {
        expected_prompts=argv[2];
        if(strlen(expected_prompts)!=64 || strspn(expected_prompts,"0123456789abcdef")!=64)return 2;
        memmove(argv+1,argv+3,(size_t)(argc-2)*sizeof(*argv));
        argc-=2;
    }
    float threshold = -1;
    if (argc >= 3 && !strcmp(argv[1], "--text-threshold")) {
        char *end;
        errno = 0;
        double value = strtod(argv[2], &end);
        if (errno || end == argv[2] || *end || !isfinite(value) || value < 0 || value > 1) {
            fputs("Text threshold must be a finite probability from 0 to 1.\n",stderr);
            return 2;
        }
        threshold = (float)value;
        memmove(argv+1,argv+3,(size_t)(argc-2)*sizeof(*argv));
        argc -= 2;
    }
    if(!manifest_path || argc!=5){fprintf(stderr,"Usage: %s [--model onejev|onejev1.6] [--expect-prompts SHA256] [--text-threshold P] EXPECTED.jsonl INPUTS.jsonl ANSWERS.jsonl PREPARE.aml\n",argv[0]);return 2;}
    FILE *g=NULL,*i=NULL,*a=NULL;
    snapshot labels={0},inputs={0},prepare={0},threshold_policy={0},witness={0};
    char*manifest=nj_load(manifest_path,NULL),*gold=NULL,*input=NULL,*answer=NULL;size_t gc=0,ic=0,ac=0;
    char readout[65]={0};
    result rows[MAX_CASES]={{0}};tally all={0},development={0},transfer={0};int rc=1,n=0,read,policy=0;
    if(!manifest || capture(argv[1],MAX_CASES*ROW_LIMIT,&labels) || capture(argv[2],MAX_CASES*ROW_LIMIT,&inputs) ||
       capture(argv[4],ROW_LIMIT,&prepare) || (threshold>=0 && capture(THRESHOLD_PATH,ROW_LIMIT,&threshold_policy)))goto done;
    if(threshold>=0 && strcmp(threshold_policy.hash,THRESHOLD_SHA256)) {
        fputs("Unregistered AML policy for --text-threshold.\n",stderr);
        goto done;
    }
    const char *trace_source=NULL;
    if(!capture("aml/trace-witness.aml",ROW_LIMIT,&witness) && !strcmp(witness.hash,WITNESS_SHA256))
        trace_source=witness.text;
    g=fmemopen(labels.text,labels.size,"r");i=fmemopen(inputs.text,inputs.size,"r");a=fopen(argv[3],"rb");
    if(!g || !i || !a)goto done;
    /* Preserve the archived byte format for the two registered, self-contained
     * templates. Custom AML can read other files and can have effects. Execute
     * it once per answer and bind what it actually rendered to the report. */
    int bind_prompts=expected_prompts ||
        (strcmp(prepare.hash,"410776df9fdd36a7a30af78ae083033e716e4a3051bd0e899ceda4f1bdf0c0b3") &&
         strcmp(prepare.hash,"58bf64c5d81fb6e12a650833ceeb64d68aecfe27f4bcd2025605d4f5ac90823d"));
    char rendered[MAX_CASES][128],rendered_hash[65];
    am_init();am_persistent_mode(1);
    while((read=line(g,&gold,&gc))==1) {
        if(n==MAX_CASES || line(i,&input,&ic)!=1 || line(a,&answer,&ac)!=1 || report_readout(answer,n,readout) || validate(rows+n,gold,input,answer,manifest,argv[4],prepare.text,trace_source,n,&policy))goto done;
        if(bind_prompts) {
            const char *q=am_get_var_text("question"),*p=am_get_var_text("prompt");
            char qhash[65],phash[65];
            if(!q || !p || hash_bytes(q,strlen(q),qhash) || hash_bytes(p,strlen(p),phash))goto done;
            memcpy(rendered[n],qhash,64);memcpy(rendered[n]+64,phash,64);
        }
        if(score_threshold(rows+n,input,answer,threshold,threshold_policy.text))goto done;
        for(int j=0;j<n;j++)if(!strcmp(rows[n].id,rows[j].id))goto done;
        count(&all,rows+n);count(!strcmp(rows[n].split,"development")?&development:&transfer,rows+n);n++;
    }
    if(read<0 || !n || line(i,&input,&ic)!=0 || line(a,&answer,&ac)!=0)goto done;
    if(bind_prompts && (hash_bytes(rendered,(size_t)n*sizeof(*rendered),rendered_hash) ||
       (expected_prompts && strcmp(expected_prompts,rendered_hash)))) {
        fputs("Rendered AML prompts differ from their registered digest.\n",stderr);goto done;
    }
    fputs("{\"schema\":\"jovovich.quality-score/1\",",stdout);json_field(stdout,"inputs_sha256",inputs.hash);fputc(',',stdout);
    json_field(stdout,"expected_sha256",labels.hash);fputc(',',stdout);json_field(stdout,"prepare_sha256",prepare.hash);
    if(bind_prompts){fputc(',',stdout);json_field(stdout,"rendered_prompts_sha256",rendered_hash);}
    if(policy){fputc(',',stdout);json_field(stdout,"boundary_policy","signed-int-comparison/1");}
    if(*readout){fputc(',',stdout);json_field(stdout,"readout_sha256",readout);}
    if(threshold >= 0) {
        fprintf(stdout,",\"text_threshold\":%.17g,", (double)threshold);
        json_field(stdout,"threshold_policy_sha256",threshold_policy.hash);
    }
    fputs(",\"all\":",stdout);totals(stdout,&all);
    fputs(",\"development\":",stdout);totals(stdout,&development);fputs(",\"transfer\":",stdout);totals(stdout,&transfer);
    fputs(",\"cases\":[",stdout);
    for(int j=0;j<n;j++) {
        result*r=rows+j;if(j)fputc(',',stdout);fputc('{',stdout);
        json_field(stdout,"id",r->id);fputc(',',stdout);json_field(stdout,"split",r->split);fputc(',',stdout);json_field(stdout,"family",r->family);
        fputc(',',stdout);json_field(stdout,"expected",r->expected);fputc(',',stdout);json_field(stdout,"predicted",r->scored);
        if(threshold >= 0) {
            fputc(',',stdout);json_field(stdout,"raw_predicted",r->predicted);
            fprintf(stdout,",\"threshold_applied\":%s",r->threshold_applied ? "true" : "false");
        }
        fprintf(stdout,",\"probabilities\":{\"CONCERN\":%.17g,\"CLEAN\":%.17g}}",r->concern,r->clean);
    }
    fputs("]}\n",stdout);rc=ferror(stdout) || fflush(stdout);
done:
    if(rc)fprintf(stderr,"Invalid or incomplete quality run at case %d\n",n+1);
    if(g)fclose(g);
    if(i)fclose(i);
    if(a)fclose(a);
    for(int j=0;j<MAX_CASES;j++){free(rows[j].id);free(rows[j].split);free(rows[j].family);free(rows[j].expected);free(rows[j].predicted);}
    free(labels.text);free(inputs.text);free(prepare.text);free(threshold_policy.text);free(witness.text);
    free(gold);free(input);free(answer);free(manifest);am_persistent_mode(0);return rc?1:0;
}
