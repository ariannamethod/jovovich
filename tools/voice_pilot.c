/* Teacher-forced output-only SFT and unconstrained greedy audition on frozen OneJev. */
#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "harness/arch.h"
#include "examples/bpe.h"
#include "model_bytes.h"
#include "report_json.h"
#include "json.h"
#include "notorch.h"
#include <math.h>
#include <stdint.h>

enum { D=32, WIDTH=D+1, MAX_ACTIVE=512, MAX_ROWS=64, MAX_TARGET=65, MAX_PROMPT=2048, LIMIT=32, STEPS=200 };
typedef struct {
    char *id, *state, *target;
    int tokens[MAX_TARGET], length;
} packet;
typedef struct {
    float feature[WIDTH], base[MAX_ACTIVE], target_base;
    double log_other;
    int target;
} position;
typedef struct {
    int n, ids[MAX_ACTIVE], *index;
    float params[MAX_ACTIVE*WIDTH];
} adapter;
typedef struct {
    void *model;
    bpe_tokenizer *tokenizer;
    nt_dims dims;
    float *logits, feature[WIDTH];
    int end, captured, selecting;
    const char *policy;
} engine;

static void fail(const char *s) { fprintf(stderr,"Voice pilot: %s\n",s); exit(1); }

static int ascii_field(const char *s) {
    if (!s || !*s || strstr(s,"<|")) return 0;
    for (const unsigned char *p=(const unsigned char*)s; *p; p++)
        if ((*p<32 && *p!='\n') || *p>126) return 0;
    return 1;
}

static int read_rows(const char *path, packet *rows, engine *e, int blind) {
    FILE *f=fopen(path,"rb");
    if (!f) fail("cannot open packets");
    size_t total=0;
    int bad=0,n=0;
    char *s;
    while ((s=report_json_row(f,&total,&bad,65536,4*1024*1024))) {
        if (n==MAX_ROWS) fail("too many packets");
        packet *p=&rows[n++];
        p->id=nj_string(nj_get(s,"id"));
        p->state=nj_string(nj_get(s,"state"));
        if (!p->id || strlen(p->id)!=64 || strspn(p->id,"0123456789abcdef")!=64 ||
            !ascii_field(p->state))
            fail("invalid packet");
        if (blind) {
            if (nj_get(s,"target") || nj_get(s,"references")) fail("audition expects target-free packets");
            free(s);
            continue;
        }
        p->target=nj_string(nj_get(s,"target"));
        if (!ascii_field(p->target) || strchr(p->target,'\n')) fail("invalid target");
        int k=bpe_encode_raw(e->tokenizer,p->target,p->tokens,MAX_TARGET);
        if (k<1 || k>=MAX_TARGET) fail("reference outside token bounds");
        if (e->selecting) {
            if (k!=1 || (strcmp(p->target,"A") && strcmp(p->target,"B"))) fail("expected one A/B label");
            p->length=1;
        } else {
            p->tokens[k]=e->end;
            p->length=k+1;
        }
        free(s);
    }
    if (bad || !n || ferror(f)) fail("incomplete packet stream");
    fclose(f); return n;
}

static uint32_t mix(uint32_t v) {
    v^=v>>16; v*=UINT32_C(0x7feb352d); v^=v>>15; v*=UINT32_C(0x846ca68b); return v^(v>>16);
}

/* One fixed signed projection of the final residual. Only output coefficients learn. */
static int capture(void *ctx,int layer,int pos,int n,int width,float *residual) {
    (void)pos;
    engine *e=ctx;
    if (layer!=e->dims.n_layers-1) return 0;
    if (width!=1024 || n<1) return 1;
    const float *last=residual+(size_t)(n-1)*width;
    double sums[D]={0},norm=0;
    for (int j=0;j<width;j++) {
        uint32_t h=mix((uint32_t)j+1);
        sums[h%D]+=(h>>31) ? -last[j] : last[j];
    }
    for (int j=0;j<D;j++) norm+=sums[j]*sums[j];
    if (!isfinite(norm) || norm<=0) return 1;
    double scale=sqrt(D/norm);
    for (int j=0;j<D;j++) e->feature[j]=(float)(sums[j]*scale);
    e->feature[D]=1; e->captured=1; return 0;
}

static void read_logits(engine *e,kv_cache *kv,int *ids,int n,int pos) {
    e->captured=0;
    if (nt_arch_qwen35.forward_residual(e->model,kv,ids,n,pos,e->logits,capture,e) || !e->captured)
        fail("NoTorch forward failed");
}

static kv_cache *start(engine *e,const packet *p,int *pos,int room) {
    if (am_set_var_text("voice_state",p->state) || am_exec_file(e->policy)) fail("AML voice prompt");
    const char *prompt=am_get_var_text("voice_prompt");
    int ids[MAX_PROMPT];
    int n=prompt?bpe_encode_special(e->tokenizer,prompt,ids,MAX_PROMPT):0;
    if (n<1 || n>=MAX_PROMPT) fail("voice prompt outside token bounds");
    kv_cache *kv=nt_arch_qwen35.kv_new(e->model,n+room);
    if (!kv) fail("cannot allocate cache");
    for (int at=0;at<n;at+=32) {
        int take=n-at<32?n-at:32;
        if (at+take==n) read_logits(e,kv,ids+at,take,at);
        else if (nt_arch_qwen35.forward(e->model,kv,ids+at,take,at,NULL)) fail("prefill");
    }
    *pos=n; return kv;
}

static void observe(engine *e,const adapter *a,int target,position *z) {
    memcpy(z->feature,e->feature,sizeof(z->feature));
    z->target=a->index[target]; z->target_base=e->logits[target];
    for (int i=0;i<a->n;i++) z->base[i]=e->logits[a->ids[i]];
    double peak=-INFINITY,sum=0;
    for (int i=0;i<e->dims.vocab;i++) if (a->index[i]<0 && e->logits[i]>peak) peak=e->logits[i];
    for (int i=0;i<e->dims.vocab;i++) if (a->index[i]<0) sum+=exp((double)e->logits[i]-peak);
    z->log_other=peak+log(sum);
    if (!isfinite(z->log_other) || !isfinite(z->target_base)) fail("non-finite logits");
}

static int collect(engine *e,const adapter *a,const packet *rows,int n,position *positions) {
    int used=0;
    for (int i=0;i<n;i++) {
        const packet *p=rows+i;
        int pos;
        kv_cache *kv=start(e,p,&pos,p->length);
        for (int j=0;j<p->length;j++) {
            int token=p->tokens[j];
            observe(e,a,token,&positions[used++]);
            if (j+1<p->length) read_logits(e,kv,&token,1,pos++);
        }
        nt_arch_qwen35.kv_free(e->model,kv);
    }
    return used;
}

static float offset(const adapter *a,int i,const float *feature) {
    float v=0;
    for (int j=0;j<WIDTH;j++) v+=a->params[i*WIDTH+j]*feature[j];
    return v;
}

/* All untouched vocabulary rows contribute their exact frozen partition mass. */
static double nll(const adapter *a,const position *data,int n,float *grad) {
    double loss=0;
    for (int k=0;k<n;k++) {
        const position *p=data+k;
        double z[MAX_ACTIVE],peak=p->log_other;
        for (int i=0;i<a->n;i++) {
            z[i]=p->base[i]+offset(a,i,p->feature);
            if (z[i]>peak) peak=z[i];
        }
        double sum=exp(p->log_other-peak);
        for (int i=0;i<a->n;i++) sum+=exp(z[i]-peak);
        double log_z=peak+log(sum);
        loss+=log_z-(p->target<0?p->target_base:z[p->target]);
        if (grad) for (int i=0;i<a->n;i++) {
            double residual=(exp(z[i]-log_z)-(p->target==i))/n;
            for (int j=0;j<WIDTH;j++) grad[i*WIDTH+j]+=(float)(residual*p->feature[j]);
        }
    }
    if (!isfinite(loss)) fail("non-finite loss");
    return loss/n;
}

static void fit(adapter *a,const position *data,int n,float rate,adapter *last_four) {
    int size=a->n*WIDTH;
    float *g=calloc((size_t)size,sizeof(*g)),*next=malloc((size_t)size*sizeof(*next));
    if (!g || !next) fail("optimizer allocation");
    for (int step=0;step<STEPS;step++) {
        memset(g,0,(size_t)size*sizeof(*g));
        nll(a,data,n,g);
        for (int j=0;j<size;j++) g[j]+=0.002f*a->params[j];
        if (nt_sgd_values(a->params,g,size,rate,next)) fail("NoTorch SGD");
        memcpy(a->params,next,(size_t)size*sizeof(*next));
        if (last_four && step>=STEPS-4) last_four[step-(STEPS-4)]=*a;
    }
    free(g);free(next);
}

static void generate(FILE *out,engine *e,const adapter *a,const packet *p) {
    int pos,ids[LIMIT],used=0,stopped=0;
    kv_cache *kv=start(e,p,&pos,LIMIT);
    fputs("{\"utf8_hex\":\"",out);
    for (int j=0;j<LIMIT;j++) {
        if (a) for (int i=0;i<a->n;i++) e->logits[a->ids[i]]+=offset(a,i,e->feature);
        int best=0;
        for (int i=0;i<e->dims.vocab;i++) {
            if (!isfinite(e->logits[i])) fail("non-finite generation score");
            if (e->logits[i]>e->logits[best]) best=i;
        }
        ids[used++]=best;
        if (bpe_is_eog(e->tokenizer,best) || best==e->end) {stopped=1;break;}
        int cap=bpe_decode_token_capacity(e->tokenizer,best);
        char *bytes=cap>0?malloc((size_t)cap):NULL;
        if (!bytes) fail("token decode allocation");
        int len=bpe_decode_token(e->tokenizer,best,bytes,cap);
        if (len<=0) fail("empty output token");
        for (int b=0;b<len;b++) fprintf(out,"%02x",(unsigned char)bytes[b]);
        free(bytes);
        if (j+1<LIMIT) read_logits(e,kv,&best,1,pos++);
    }
    nt_arch_qwen35.kv_free(e->model,kv);
    fprintf(out,"\",\"stop\":\"%s\",\"token_ids\":[",stopped?"eog":"cap");
    for (int j=0;j<used;j++) fprintf(out,j?",%d":"%d",ids[j]);
    fputs("]}",out);
}

static double letter_probability(const position *p,const adapter *a,int index_a,int index_b) {
    double margin=(double)p->base[index_a]-p->base[index_b];
    if (a) margin+=offset(a,index_a,p->feature)-offset(a,index_b,p->feature);
    return 1.0/(1.0+exp(-margin));
}

/* A same-panel diagnostic requested after the registered selector chose A on every row. */
static void stability(FILE *out,adapter *a,const position *train,int n,const position *held,int m,int ia,int ib) {
    const float rates[]={0.25f,0.025f};
    adapter *tail=calloc(4,sizeof(*tail));
    if (!tail) fail("optimizer trace allocation");
    fputs(",\"optimizer_tail\":[",out);
    for (int r=0;r<2;r++) {
        memset(a->params,0,sizeof(a->params));
        fit(a,train,n,rates[r],tail);
        for (int k=0;k<4;k++) {
            int chose_a=0;
            for (int i=0;i<n;i++) chose_a+=letter_probability(train+i,&tail[k],ia,ib)>=0.5;
            fprintf(out,"%s{\"rate\":%.4g,\"step\":%d,\"train_nll\":%.12g,\"train_chose_a\":%d,\"heldout_p_a\":[",
                    r || k?",":"",rates[r],STEPS-3+k,nll(&tail[k],train,n,NULL),chose_a);
            for (int i=0;i<m;i++) fprintf(out,i?",%.17g":"%.17g",letter_probability(held+i,&tail[k],ia,ib));
            fputs("]}",out);
        }
    }
    fputc(']',out); free(tail);
}

static void digest(const char *path,char out[65]) {
    if (jov_model_file_hash(path,out)) fail("cannot hash a required file");
}

static void baseline(FILE *out,engine *e,const packet *rows,int n,
                     const char *wh,const char *th,const char *test_hash,const char *aml_hash) {
    fprintf(out,"{\"schema\":\"jovovich.voice-baseline/1\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",",wh,th);
    fprintf(out,"\"heldout_sha256\":\"%s\",\"prompt_policy_sha256\":\"%s\",\"audition\":[",test_hash,aml_hash);
    for (int i=0;i<n;i++) {
        fprintf(out,"%s{\"id\":\"%s\",\"base\":",i?",":"",rows[i].id);
        generate(out,e,NULL,rows+i);
        fputc('}',out);
    }
    fputs("]}\n",out);
}

int main(int argc,char **argv) {
    int frozen=argc==5 && !strcmp(argv[1],"--baseline");
    int diagnosing=argc==6 && !strcmp(argv[1],"--select-stability");
    int selecting=diagnosing || (argc==6 && !strcmp(argv[1],"--select"));
    if (selecting) { argv++; argc--; }
    if (argc!=5) {fprintf(stderr,"Usage: voice-pilot [--select|--select-stability] ORIGINAL.gguf TOKENIZER.gguf TRAIN.jsonl HELDOUT.jsonl\n       voice-pilot --baseline ORIGINAL.gguf TOKENIZER.gguf HELDOUT.jsonl\n");return 2;}
    const char *policy=selecting?"aml/voice-select.aml":"aml/voice-prompt.aml";
    char wh[65],th[65],train_hash[65],test_hash[65],aml_hash[65];
    const char *weights=argv[frozen?2:1], *tokenizer=argv[frozen?3:2];
    digest(weights,wh);digest(tokenizer,th);digest(argv[4],test_hash);
    if (!frozen) digest(argv[3],train_hash);
    digest(policy,aml_hash);
    char *manifest=nj_load("models/onejev-0.8b.json",NULL);
    if (!manifest || !nj_is(nj_get(manifest,"weights_sha256"),wh) || !nj_is(nj_get(manifest,"tokenizer_sha256"),th))
        fail("model or tokenizer differs from the original release");
    free(manifest);
    gguf_file *gg=gguf_open(weights);
    engine e={.policy=policy,.selecting=selecting};
    e.model=gg?nt_arch_qwen35.load(gg,&e.dims):NULL;
    e.tokenizer=bpe_load(tokenizer);
    if (!e.model || !e.tokenizer || e.dims.vocab<=0) fail("cannot open native model and tokenizer");
    e.end=bpe_token_id(e.tokenizer,"<|im_end|>");
    e.logits=malloc((size_t)e.dims.vocab*sizeof(float));
    adapter a={0};
    a.index=malloc((size_t)e.dims.vocab*sizeof(*a.index));
    if (!e.logits || !a.index || e.end<0 || e.end>=e.dims.vocab) fail("invalid model shape");
    for (int i=0;i<e.dims.vocab;i++) a.index[i]=-1;
    packet train[MAX_ROWS]={0},test[MAX_ROWS]={0};
    int nt=frozen?0:read_rows(argv[3],train,&e,0);
    int nv=read_rows(argv[4],test,&e,frozen);
    for (int i=0;i<nt+nv;i++) {
        const packet *p=i<nt?train+i:test+i-nt;
        for (int j=0;j<i;j++) {
            const packet *prior=j<nt?train+j:test+j-nt;
            if (!strcmp(p->id,prior->id) || !strcmp(p->state,prior->state)) fail("duplicate packet across or within splits");
        }
        for (int k=0;k<p->length;k++) {
            int id=p->tokens[k];
            if (id<0 || id>=e.dims.vocab) fail("invalid target token");
            if (i<nt && a.index[id]<0) {
                if (a.n==MAX_ACTIVE) fail("training vocabulary exceeds the pilot limit");
                a.index[id]=a.n; a.ids[a.n++]=id;
            }
        }
    }
    FILE *out=tmpfile();
    if (!out) fail("cannot buffer audition");
    am_init();am_persistent_mode(1);
    if (frozen) {
        baseline(out,&e,test,nv,wh,th,test_hash,aml_hash);
        goto finish;
    }
    int index_a=-1,index_b=-1;
    if (selecting) {
        int token_a=bpe_token_id(e.tokenizer,"A"), token_b=bpe_token_id(e.tokenizer,"B");
        if (a.n!=2 || token_a<0 || token_b<0 || token_a>=e.dims.vocab || token_b>=e.dims.vocab)
            fail("selector requires both A and B training labels");
        index_a=a.index[token_a]; index_b=a.index[token_b];
        if (index_a<0 || index_b<0) fail("selector label mismatch");
    }
    position *training=calloc((size_t)nt*MAX_TARGET,sizeof(*training)),*held=calloc((size_t)nv*MAX_TARGET,sizeof(*held));
    if (!training || !held) fail("training allocation");
    int n=collect(&e,&a,train,nt,training), m=collect(&e,&a,test,nv,held);
    double train_before=nll(&a,training,n,NULL),held_before=nll(&a,held,m,NULL);
    fit(&a,training,n,0.25f,NULL);
    double train_after=nll(&a,training,n,NULL),held_after=nll(&a,held,m,NULL);
    fprintf(out,"{\"schema\":\"%s\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",",selecting?"jovovich.voice-selection/1":"jovovich.voice-pilot/1",wh,th);
    fprintf(out,"\"train_sha256\":\"%s\",\"heldout_sha256\":\"%s\",\"prompt_policy_sha256\":\"%s\",",train_hash,test_hash,aml_hash);
    fprintf(out,"\"train_tokens\":%d,\"heldout_tokens\":%d,\"train_nll\":[%.12g,%.12g],\"heldout_nll\":[%.12g,%.12g],",n,m,train_before,train_after,held_before,held_after);
    fprintf(out,"\"steps\":%d,\"learned_parameters\":%d,\"adapter\":[",STEPS,a.n*WIDTH);
    for (int i=0;i<a.n;i++) {
        fprintf(out,"%s{\"token\":%d,\"weight_and_bias\":[",i?",":"",a.ids[i]);
        for (int j=0;j<WIDTH;j++) fprintf(out,j?",%.9g":"%.9g",a.params[i*WIDTH+j]);
        fputs("]}",out);
    }
    fputs("],\"audition\":[",out);
    for (int i=0;i<nv;i++) {
        fprintf(out,"%s{\"id\":\"%s\",\"base\":",i?",":"",test[i].id);
        if (selecting) {
            fprintf(out,"%.17g,\"fitted\":%.17g",letter_probability(held+i,NULL,index_a,index_b),
                    letter_probability(held+i,&a,index_a,index_b));
        } else {
            generate(out,&e,NULL,test+i); fputs(",\"fitted\":",out); generate(out,&e,&a,test+i);
        }
        fputc('}',out);
    }
    fputc(']',out);
    if (diagnosing) stability(out,&a,training,n,held,m,index_a,index_b);
    fputs("}\n",out);
    free(training);free(held);
finish:
    if (ferror(out) || fseek(out,0,SEEK_SET)) fail("cannot finish audition");
    char buf[8192];size_t got;
    while ((got=fread(buf,1,sizeof(buf),out))) if(fwrite(buf,1,got,stdout)!=got) fail("write failed");
    if(ferror(out) || fflush(stdout)) fail("write failed");
    fclose(out);
    for(int i=0;i<nt+nv;i++) {
        packet *p=i<nt?train+i:test+i-nt;
        free(p->id);free(p->state);free(p->target);
    }
    free(a.index);free(e.logits);
    am_persistent_clear();am_persistent_mode(0);bpe_free(e.tokenizer);nt_arch_qwen35.free(e.model);gguf_close(gg);
    return 0;
}
