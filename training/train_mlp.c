/* Last-decoder-MLP LoRA SFT. All numerical work uses native notorch C.
 * Frozen: embeddings, attention, preceding blocks, norms and output head.
 * The last MLP cannot affect any attention cache. Temporarily zeroing its
 * down projection exposes its exact post-attention input through the existing
 * post-layer hook; the original projection and bias are restored after capture.
 * Cached gate/up base products are constant, but gradients pass through the
 * adapted SwiGLU, down projection, final norm and frozen vocabulary projection.
 */
#include "harness/arch_models.h"
#include "examples/bpe.h"
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MLP_MAX_TOKENS 4096
#define MLP_RANK 16
#define MLP_SEED 20260929

typedef struct { nt_tensor *z, *xn, *gate, *up, *targets, *bias; int n; } mlp_batch;
typedef struct { char *system, *prompt, *answer; mlp_batch cache; int *ids, n_ids, start; } mlp_example;
typedef struct {
    int E, F, V, layer;
    nt_tensor *wg, *wu, *wd, *head, *norm, *ffn_norm, *bias;
    nt_lora_pair adapters[3];
} mlp_bank;
typedef struct { int example, token; } token_row;
typedef struct { int layer, start; nt_tensor *out; } mlp_capture;

static void mlp_die(const char *s) { fprintf(stderr,"train-mlp: %s\n",s); exit(1); }
static int checked(int i) { if(i<0)mlp_die("tape operation failed"); return i; }
static nt_tensor *tensor(int rows,int cols) {
    nt_tensor *t=nt_tensor_new2d(rows,cols);if(!t)mlp_die("tensor allocation failed");return t;
}
static uint32_t mlp_u32(FILE *f) {
    unsigned char b[4];if(fread(b,1,4,f)!=4)mlp_die("truncated dataset");
    return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;
}
static char *mlp_text(FILE *f) {
    uint32_t n=mlp_u32(f);if(n>1<<20)mlp_die("dataset field exceeds 1 MiB");
    char *s=calloc((size_t)n+1,1);if(!s||fread(s,1,n,f)!=n)mlp_die("cannot read dataset field");
    if(memchr(s,0,n))mlp_die("NUL in dataset text");
    return s;
}
static mlp_example *mlp_data(const char *path,int *count) {
    FILE *f=fopen(path,"rb");unsigned char magic[8];
    if(!f||fread(magic,1,8,f)!=8||memcmp(magic,"JVDS\1\0\0\0",8))mlp_die("invalid JVDS dataset");
    uint32_t n=mlp_u32(f);if(n<1||n>10000)mlp_die("invalid example count");*count=(int)n;
    mlp_example *rows=calloc(n,sizeof(*rows));if(!rows)mlp_die("dataset allocation failed");
    for(int i=0;i<*count;i++) {
        if(mlp_u32(f)!=0)mlp_die("SFT-only trainer refuses DPO rows; prepare an SFT dataset");
        rows[i].system=mlp_text(f);rows[i].prompt=mlp_text(f);rows[i].answer=mlp_text(f);
        char *rejected=mlp_text(f);if(*rejected)mlp_die("SFT row has a rejected completion");free(rejected);
        if(!*rows[i].answer)mlp_die("empty completion");
    }
    if(fgetc(f)!=EOF)mlp_die("trailing dataset bytes");
    fclose(f);return rows;
}
static int mlp_encode(bpe_tokenizer *tok,int *ids,int n,const char *s) {
    int k=bpe_encode_raw(tok,s,ids+n,MLP_MAX_TOKENS-n);
    if(k<0||n+k>=MLP_MAX_TOKENS-2)mlp_die("example exceeds token capacity; no truncation");
    return n+k;
}
static int mlp_role(bpe_tokenizer *tok,int *ids,int n,int begin,const char *role,const char *s,int end) {
    ids[n++]=begin;n=mlp_encode(tok,ids,n,role);n=mlp_encode(tok,ids,n,"\n");
    n=mlp_encode(tok,ids,n,s);ids[n++]=end;return mlp_encode(tok,ids,n,"\n");
}
static void tokenize(mlp_example *e,bpe_tokenizer *tok) {
    int begin=bpe_token_id(tok,"<|im_start|>"),end=bpe_token_id(tok,"<|im_end|>");
    if(begin<0||end<0)mlp_die("missing ChatML tokens");
    e->ids=malloc(MLP_MAX_TOKENS*sizeof(int));if(!e->ids)mlp_die("token allocation failed");
    int n=mlp_role(tok,e->ids,0,begin,"system",e->system,end);
    n=mlp_role(tok,e->ids,n,begin,"user",e->prompt,end);
    e->ids[n++]=begin;n=mlp_encode(tok,e->ids,n,"assistant\n");int prompt=n;
    n=mlp_encode(tok,e->ids,n,e->answer);e->ids[n++]=end;
    e->n_ids=n;e->start=prompt-1;e->cache.n=n-prompt;
    e->cache.targets=tensor(e->cache.n,1);
    for(int t=0;t<e->cache.n;t++)e->cache.targets->data[t]=(float)e->ids[prompt+t];
}
static int capture_mlp(void *ctx,int layer,int pos,int n,int width,float *residual) {
    mlp_capture *c=ctx;if(layer!=c->layer)return NT_OK;
    if(width!=c->out->shape[1])return NT_E_ARG;
    for(int t=0;t<n;t++) {
        int row=pos+t-c->start;if(row>=0&&row<c->out->shape[0])
            memcpy(c->out->data+(size_t)row*width,residual+(size_t)t*width,(size_t)width*sizeof(float));
    }
    return NT_OK;
}
static void capture_sequence(llama_model *m,nt_dims dims,const mlp_example *e,nt_tensor *out) {
    kv_cache *kv=kv_new(dims.n_layers,e->n_ids,dims.kv_dim);
    if(!kv||!kv->k||!kv->v)mlp_die("KV allocation failed");
    mlp_capture c={m->n_layers-1,e->start,out};
    for(int pos=0;pos<e->n_ids-1;) {
        int n=e->n_ids-1-pos;if(n>NT_PREFILL_CHUNK)n=NT_PREFILL_CHUNK;
        int rc=nt_arch_llama.forward_residual(m,kv,e->ids+pos,n,pos,NULL,capture_mlp,&c);
        if(rc!=NT_OK)mlp_die(nt_strerror(rc));
        pos+=n;
    }
    kv_free(kv);
}
static nt_tensor *load_matrix(gguf_file *gf,const char *name,int rows,int cols) {
    int ti=gguf_find_tensor(gf,name);
    if(ti<0||gf->tensors[ti].ndim!=2||gf->tensors[ti].shape[0]!=(uint64_t)cols||gf->tensors[ti].shape[1]!=(uint64_t)rows)
        mlp_die("missing or wrongly shaped frozen matrix");
    nt_tensor *w=tensor(rows,cols);free(w->data);w->data=gguf_dequant(gf,ti);
    if(!w->data)mlp_die("matrix dequantization failed");
    return w;
}
static void bank_init(mlp_bank *b,llama_model *m) {
    b->E=m->embed;b->F=m->ffn;b->V=m->vocab;b->layer=m->n_layers-1;char name[128];
    snprintf(name,sizeof(name),"blk.%d.ffn_gate.weight",b->layer);b->wg=load_matrix(m->gf,name,b->F,b->E);
    snprintf(name,sizeof(name),"blk.%d.ffn_up.weight",b->layer);b->wu=load_matrix(m->gf,name,b->F,b->E);
    snprintf(name,sizeof(name),"blk.%d.ffn_down.weight",b->layer);b->wd=load_matrix(m->gf,name,b->E,b->F);
    b->head=load_matrix(m->gf,m->has_output_weight?"output.weight":"token_embd.weight",b->V,b->E);
    b->norm=tensor(1,b->E);b->ffn_norm=tensor(1,b->E);
    memcpy(b->norm->data,m->out_norm,(size_t)b->E*sizeof(float));
    memcpy(b->ffn_norm->data,m->layers[b->layer].ffn_norm,(size_t)b->E*sizeof(float));
    if(m->layers[b->layer].ffn_down_bias) {
        b->bias=tensor(1,b->E);memcpy(b->bias->data,m->layers[b->layer].ffn_down_bias,(size_t)b->E*sizeof(float));
    }
    for(int j=0;j<3;j++)if(nt_lora_init(&b->adapters[j],j==2?b->F:b->E,j==2?b->E:b->F,MLP_RANK,2*MLP_RANK))mlp_die("LoRA allocation failed");
}
static void prepare_cache(mlp_bank *b,mlp_batch *s) {
    s->xn=tensor(s->n,b->E);
    for(int t=0;t<s->n;t++)rmsnorm(s->xn->data+(size_t)t*b->E,s->z->data+(size_t)t*b->E,b->ffn_norm->data,b->E,1e-6f);
    nt_tape_start();int x=checked(nt_tape_param_frozen(s->xn));
    int g=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wg)),x,s->n));
    int u=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wu)),x,s->n));
    s->gate=nt_tensor_ref(nt_tape_get()->entries[g].output);s->up=nt_tensor_ref(nt_tape_get()->entries[u].output);
    nt_tape_clear();
}
static int delta(nt_lora_pair *a,int x,int n,int training,int *indices) {
    int ai=checked(training?nt_tape_param(a->A):nt_tape_param_frozen(a->A));
    int bi=checked(training?nt_tape_param(a->B):nt_tape_param_frozen(a->B));
    if(indices){indices[0]=ai;indices[1]=bi;}
    return checked(nt_scale(checked(nt_seq_linear(bi,checked(nt_seq_linear(ai,x,n)),n)),a->scaling));
}
static int mlp_forward(mlp_bank *b,mlp_batch *s,int training,int *residual,int *logits,int *indices) {
    int x=checked(nt_tape_param_frozen(s->xn)),z=checked(nt_tape_param_frozen(s->z));
    int g=checked(nt_add(checked(nt_tape_param_frozen(s->gate)),delta(&b->adapters[0],x,s->n,training,indices)));
    int u=checked(nt_add(checked(nt_tape_param_frozen(s->up)),delta(&b->adapters[1],x,s->n,training,indices?indices+2:NULL)));
    int h=checked(nt_swiglu(g,u));
    int d=checked(nt_add(checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wd)),h,s->n)),delta(&b->adapters[2],h,s->n,training,indices?indices+4:NULL)));
    int r=checked(nt_add(z,d));if(s->bias)r=checked(nt_add(r,checked(nt_tape_param_frozen(s->bias))));
    int y=checked(nt_seq_rmsnorm(r,checked(nt_tape_param_frozen(b->norm)),s->n,b->E));
    int l=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->head)),y,s->n));
    if(residual)*residual=r;
    if(logits)*logits=l;
    return checked(nt_seq_cross_entropy(l,checked(nt_tape_param_frozen(s->targets)),s->n,b->V));
}
static mlp_batch gather(mlp_bank *b,mlp_example *rows,const token_row *order,int n) {
    mlp_batch s={.n=n};s.z=tensor(n,b->E);s.xn=tensor(n,b->E);s.gate=tensor(n,b->F);s.up=tensor(n,b->F);s.targets=tensor(n,1);
    if(b->bias)s.bias=tensor(n,b->E);
    for(int t=0;t<n;t++) {
        mlp_batch *c=&rows[order[t].example].cache;int p=order[t].token;
        memcpy(s.z->data+(size_t)t*b->E,c->z->data+(size_t)p*b->E,(size_t)b->E*sizeof(float));
        memcpy(s.xn->data+(size_t)t*b->E,c->xn->data+(size_t)p*b->E,(size_t)b->E*sizeof(float));
        memcpy(s.gate->data+(size_t)t*b->F,c->gate->data+(size_t)p*b->F,(size_t)b->F*sizeof(float));
        memcpy(s.up->data+(size_t)t*b->F,c->up->data+(size_t)p*b->F,(size_t)b->F*sizeof(float));
        s.targets->data[t]=c->targets->data[p];if(s.bias)memcpy(s.bias->data+(size_t)t*b->E,b->bias->data,(size_t)b->E*sizeof(float));
    }
    return s;
}
static void batch_free(mlp_batch *s) {
    nt_tensor_free(s->z);nt_tensor_free(s->xn);nt_tensor_free(s->gate);nt_tensor_free(s->up);nt_tensor_free(s->targets);nt_tensor_free(s->bias);memset(s,0,sizeof(*s));
}
static void zero_probe(mlp_bank *b,llama_model *m,mlp_example *rows,nt_tensor *reference) {
    int n=reference->shape[0];if(n>4)n=4;token_row order[4];for(int t=0;t<n;t++)order[t]=(token_row){0,t};
    mlp_batch s=gather(b,rows,order,n);nt_tape_start();int ri,li;mlp_forward(b,&s,0,&ri,&li,NULL);
    float *actual_r=nt_tape_get()->entries[ri].output->data,*actual_l=nt_tape_get()->entries[li].output->data;
    float *x=malloc((size_t)b->E*sizeof(float)),*ref_l=malloc((size_t)b->V*sizeof(float));if(!x||!ref_l)mlp_die("probe allocation failed");
    float re=0,rs=0,le=0,ls=0;int argmax_equal=1;
    const wt *head=m->has_output_weight?&m->out_weight:&m->tok_emb;
    for(int t=0;t<n;t++) {
        float *ref_r=reference->data+(size_t)t*b->E;
        for(int j=0;j<b->E;j++){re=fmaxf(re,fabsf(actual_r[(size_t)t*b->E+j]-ref_r[j]));rs=fmaxf(rs,fabsf(ref_r[j]));}
        rmsnorm(x,ref_r,m->out_norm,b->E,m->rms_eps);qmv(ref_l,head,x);int ai=0,bi=0;
        for(int j=0;j<b->V;j++) {
            float y=actual_l[(size_t)t*b->V+j];if(!isfinite(y)||!isfinite(ref_l[j]))mlp_die("nonfinite zero-adapter probe");
            le=fmaxf(le,fabsf(y-ref_l[j]));ls=fmaxf(ls,fabsf(ref_l[j]));
            if(y>actual_l[(size_t)t*b->V+ai])ai=j;
            if(ref_l[j]>ref_l[bi])bi=j;
        }
        argmax_equal&=ai==bi;
    }
    fprintf(stderr,"zero-adapter probe rows=%d residual_max_abs=%.8g residual_scale=%.8g logits_max_abs=%.8g logits_scale=%.8g argmax_equal=%d\n",n,re,rs,le,ls,argmax_equal);
    if(re>0.001f*(1+rs)||le>0.001f*(1+ls)||!argmax_equal)mlp_die("zero-adapter reconstruction disagrees with original forward");
    free(x);free(ref_l);nt_tape_clear();batch_free(&s);
}
static void snapshot(mlp_bank *b,const char *prefix) {
    const char *suffixes[]={"gate","up","down"};nt_tensor *base[]={b->wg,b->wu,b->wd};
    for(int j=0;j<3;j++) {
        char path[4096],name[128];snprintf(name,sizeof(name),"blk.%d.ffn_%s.weight",b->layer,suffixes[j]);const char *names[]={name};
        if(snprintf(path,sizeof(path),"%s.%s.lora",prefix,suffixes[j])>=(int)sizeof(path))mlp_die("snapshot path too long");
        if(access(path,F_OK)==0)mlp_die("snapshot exists; use a new output prefix");
        if(nt_lora_save(&b->adapters[j],1,1,names,path))mlp_die("adapter save failed");
        nt_tensor *merged=nt_tensor_clone(base[j]);if(!merged)mlp_die("merge allocation failed");
        nt_lora_pair *a=&b->adapters[j];nt_lora_merge_into(merged->data,base[j]->data,a,a->in_dim,a->out_dim);
        /* Check the merge through an independent matvec composition. */
        float *x=malloc((size_t)a->in_dim*sizeof(float)),*lo=malloc((size_t)a->rank*sizeof(float));
        float *old=malloc((size_t)a->out_dim*sizeof(float)),*change=malloc((size_t)a->out_dim*sizeof(float)),*out=malloc((size_t)a->out_dim*sizeof(float));
        if(!x||!lo||!old||!change||!out)mlp_die("merge probe allocation failed");
        for(int k=0;k<a->in_dim;k++)x[k]=0.01f*(float)((k%19)-9);
        nt_blas_matvec(old,base[j]->data,x,a->out_dim,a->in_dim);nt_blas_matvec(lo,a->A->data,x,a->rank,a->in_dim);
        nt_blas_matvec(change,a->B->data,lo,a->out_dim,a->rank);nt_blas_matvec(out,merged->data,x,a->out_dim,a->in_dim);
        float err=0,scale=0;for(int k=0;k<a->out_dim;k++) {
            float want=old[k]+a->scaling*change[k];
            if(!isfinite(want)||!isfinite(out[k]))mlp_die("nonfinite merged projection probe");
            err=fmaxf(err,fabsf(out[k]-want));scale=fmaxf(scale,fabsf(want));
        }
        if(!isfinite(err)||err>0.001f*(1+scale))mlp_die("merged MLP projection failed parity probe");
        for(int k=0;k<merged->len;k++)if(!isfinite(merged->data[k]))mlp_die("nonfinite merged weight");
        if(snprintf(path,sizeof(path),"%s.%s.f32",prefix,suffixes[j])>=(int)sizeof(path))mlp_die("snapshot path too long");
        FILE *f=fopen(path,"wbx");if(!f)mlp_die("cannot create merged tensor (path may exist)");
        if(fwrite(merged->data,sizeof(float),(size_t)merged->len,f)!=(size_t)merged->len||fclose(f))mlp_die("merged tensor write failed");
        fprintf(stderr,"saved %s merge_max_abs=%.8g\n",path,err);
        free(x);free(lo);free(old);free(change);free(out);nt_tensor_free(merged);
    }
}
static double mean_ce(mlp_bank *b,mlp_example *rows,token_row *order,int total,int batch,
                      int count,int *correct_tokens,int *exact_examples) {
    double sum=0;int *errors=calloc((size_t)count,sizeof(int));
    if(!errors)mlp_die("score allocation failed");
    *correct_tokens=0;*exact_examples=0;
    for(int p=0;p<total;p+=batch) {
        int n=total-p;if(n>batch)n=batch;mlp_batch s=gather(b,rows,order+p,n);nt_tape_start();
        int li;int ce=mlp_forward(b,&s,0,NULL,&li,NULL);float v=nt_tape_get()->entries[ce].output->data[0];
        if(!isfinite(v))mlp_die("nonfinite evaluation loss");
        float *logits=nt_tape_get()->entries[li].output->data;
        for(int t=0;t<n;t++) {
            float *l=logits+(size_t)t*b->V;int predicted=0;
            for(int j=1;j<b->V;j++)if(l[j]>l[predicted])predicted=j;
            if(predicted==(int)s.targets->data[t])(*correct_tokens)++;
            else errors[order[p+t].example]++;
        }
        sum+=(double)n*v;nt_tape_clear();batch_free(&s);
    }
    for(int i=0;i<count;i++)if(!errors[i])(*exact_examples)++;
    free(errors);
    return sum/total;
}
static int number(const char *s,int lo,int hi) {
    char *end;errno=0;long n=strtol(s,&end,10);if(errno||end==s||*end||n<lo||n>hi)mlp_die("invalid integer argument");return (int)n;
}
int main(int argc,char **argv) {
    if(argc<4||argc>8){fprintf(stderr,"usage: %s BASE.gguf SFT.bin PREFIX [EPOCHS LR TOKEN_BATCH SAVE_EVERY]\n",argv[0]);return 2;}
    int epochs=argc>4?number(argv[4],0,100):3,batch=argc>6?number(argv[6],1,128):16;
    int save_every=argc>7?number(argv[7],0,100):1;
    char *end=NULL;float lr=argc>5?strtof(argv[5],&end):0.00005f;if(!(lr>0)||!isfinite(lr)||(end&&(*end||end==argv[5])))mlp_die("invalid learning rate");
    uint16_t endian=1;if(*(unsigned char*)&endian!=1)mlp_die("raw F32 export requires a little-endian host");
    /* The tape differentiates the fixed dequantized matrices, not activation rounding. */
    if(setenv("NT_NO_I8","1",1))mlp_die("cannot set floating activation mode");
    int count;mlp_example *rows=mlp_data(argv[2],&count);gguf_file *gf=gguf_open(argv[1]);if(!gf)mlp_die("cannot open GGUF");
    if(strcmp(gf->arch,"qwen2"))mlp_die("this SFT prototype requires qwen2 (ChatML, no thinking prefix)");
    if(gf->n_layers<1||fabsf(gf->rms_eps-1e-6f)>1e-12f)mlp_die("requires layers and exact model RMSNorm epsilon 1e-6");
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);bpe_tokenizer *tok=bpe_load(argv[1]);if(!m||!tok)mlp_die("cannot load model/tokenizer");
    if(!m->layers[m->n_layers-1].ffn_norm)mlp_die("missing final MLP normalization weight");
    nt_seed(MLP_SEED);srand(MLP_SEED);mlp_bank bank={0};bank_init(&bank,m);
    int total=0;for(int i=0;i<count;i++){tokenize(&rows[i],tok);if(rows[i].n_ids>gf->ctx_len)mlp_die("example exceeds model context");if(total>INT_MAX-rows[i].cache.n)mlp_die("too many tokens");total+=rows[i].cache.n;}
    nt_tensor *reference=tensor(rows[0].cache.n,m->embed);capture_sequence(m,dims,&rows[0],reference);
    int last=m->n_layers-1;wt original=m->layers[last].wdown;float *bias=m->layers[last].ffn_down_bias;
    float *zero=calloc((size_t)m->embed*m->ffn,sizeof(float));if(!zero)mlp_die("zero projection allocation failed");
    m->layers[last].wdown=(wt){.f32=zero,.dtype=0,.rows=m->embed,.cols=m->ffn};m->layers[last].ffn_down_bias=NULL;
    double started=now_ms();
    for(int i=0;i<count;i++) {
        rows[i].cache.z=tensor(rows[i].cache.n,m->embed);capture_sequence(m,dims,&rows[i],rows[i].cache.z);prepare_cache(&bank,&rows[i].cache);
        fprintf(stderr,"cache %d/%d tokens=%d elapsed=%.1fs\n",i+1,count,rows[i].cache.n,(now_ms()-started)/1000);
    }
    m->layers[last].wdown=original;m->layers[last].ffn_down_bias=bias;free(zero);
    zero_probe(&bank,m,rows,reference);nt_tensor_free(reference);
    token_row *order=malloc((size_t)total*sizeof(*order));if(!order)mlp_die("shuffle allocation failed");int p=0;
    for(int i=0;i<count;i++)for(int t=0;t<rows[i].cache.n;t++)order[p++]=(token_row){i,t};
    long params=0;for(int j=0;j<3;j++)params+=bank.adapters[j].A->len+bank.adapters[j].B->len;
    int correct_tokens,exact_examples;
    double initial=mean_ce(&bank,rows,order,total,batch,count,&correct_tokens,&exact_examples);
    printf("{\"stage\":\"sft_initial\",\"mean_token_ce\":%.8f,\"examples\":%d,\"tokens\":%d,\"rank\":16,\"alpha\":32,\"layer\":%d,\"trainable_parameters\":%ld,\"seed\":%d,\"teacher_forced_correct_tokens\":%d,\"teacher_forced_exact_examples\":%d}\n",initial,count,total,last,params,MLP_SEED,correct_tokens,exact_examples);fflush(stdout);
    for(int ep=1;ep<=epochs;ep++) {
        for(int i=total-1;i>0;i--){int j=rand()%(i+1);token_row tmp=order[i];order[i]=order[j];order[j]=tmp;}
        double sum=0,epoch_start=now_ms();
        for(int start=0;start<total;start+=batch) {
            int n=total-start;if(n>batch)n=batch;mlp_batch s=gather(&bank,rows,order+start,n);nt_tape_start();
            int ce=mlp_forward(&bank,&s,1,NULL,NULL,NULL);float loss=nt_tape_get()->entries[ce].output->data[0];if(!isfinite(loss))mlp_die("nonfinite SFT loss");
            nt_tape_backward(ce);float norm=nt_tape_clip_grads(1.0f);if(!isfinite(norm))mlp_die("nonfinite gradients");nt_tape_adam_step(lr);nt_tape_clear();batch_free(&s);sum+=(double)n*loss;
        }
        double held=mean_ce(&bank,rows,order,total,batch,count,&correct_tokens,&exact_examples);
        printf("{\"stage\":\"sft\",\"epoch\":%d,\"online_mean_token_ce\":%.8f,\"mean_token_ce\":%.8f,\"teacher_forced_correct_tokens\":%d,\"teacher_forced_exact_examples\":%d,\"seconds\":%.3f}\n",ep,sum/total,held,correct_tokens,exact_examples,(now_ms()-epoch_start)/1000);fflush(stdout);
        if(save_every&&(ep%save_every==0||ep==epochs)) {
            char prefix[4000];if(snprintf(prefix,sizeof(prefix),"%s.epoch%02d",argv[3],ep)>=(int)sizeof(prefix))mlp_die("output prefix too long");snapshot(&bank,prefix);
        }
    }
    snapshot(&bank,argv[3]);
    nt_tape_start();for(int j=0;j<3;j++){nt_tape_param(bank.adapters[j].A);nt_tape_param(bank.adapters[j].B);}nt_tape_destroy();
    for(int j=0;j<3;j++)nt_lora_free(&bank.adapters[j]);
    nt_tensor_free(bank.wg);nt_tensor_free(bank.wu);nt_tensor_free(bank.wd);nt_tensor_free(bank.head);nt_tensor_free(bank.norm);nt_tensor_free(bank.ffn_norm);nt_tensor_free(bank.bias);
    for(int i=0;i<count;i++){free(rows[i].system);free(rows[i].prompt);free(rows[i].answer);free(rows[i].ids);batch_free(&rows[i].cache);}free(order);free(rows);
    bpe_free(tok);nt_arch_llama.free(m);gguf_close(gf);return 0;
}
