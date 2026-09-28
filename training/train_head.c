/* JOVOVICH output-head LoRA: frozen Qwen2 decoder, native notorch SFT then DPO.
 * Completion-only teacher forcing. Final hidden states and base logits are
 * cached once; all adapter math, cross entropy, gradients and Adam are notorch.
 * This trains output.weight only; the decoder and input embedding stay frozen.
 * The DPO reference is a frozen snapshot of the post-SFT policy, represented by
 * its exact per-completion log probabilities on the fixed preference dataset.
 *
 * Usage: train_head BASE.gguf DATA.bin OUTPUT_PREFIX [SFT_EPOCHS DPO_EPOCHS LR]
 * Outputs: PREFIX.sft.lora, PREFIX.lora, PREFIX.head.f32 (for merge_head).
 */
#include "harness/arch_models.h"
#include "examples/bpe.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_TOKENS 2048
#define RANK 8
#define BETA 0.1f

typedef struct { nt_tensor *x, *logits, *targets; int n; float ref_ce; } sequence;
typedef struct { int kind; char *system, *prompt, *chosen, *rejected; sequence c, r; } example;
typedef struct { llama_model *model; sequence *seq; int start; } capture;
static void die(const char *what) { fprintf(stderr, "train: %s\n", what); exit(1); }
static uint32_t read_u32(FILE *f) {
    unsigned char b[4];
    if (fread(b, 1, 4, f) != 4) die("truncated dataset");
    return (uint32_t)b[0] | (uint32_t)b[1]<<8 | (uint32_t)b[2]<<16 | (uint32_t)b[3]<<24;
}
static char *read_text(FILE *f) {
    uint32_t n = read_u32(f);
    if (n > 1<<20) die("dataset field exceeds 1 MiB");
    char *s = calloc((size_t)n+1, 1);
    if (!s || fread(s,1,n,f) != n) die("dataset field could not be read");
    return s;
}
static example *load_data(const char *path, int *count) {
    FILE *f = fopen(path,"rb"); unsigned char magic[8];
    if (!f || fread(magic,1,8,f)!=8 || memcmp(magic,"JVDS\1\0\0\0",8)) die("invalid JVDS dataset");
    *count = (int)read_u32(f);
    if (*count < 1 || *count > 10000) die("invalid example count");
    example *rows = calloc((size_t)*count,sizeof(*rows));
    if (!rows) die("dataset allocation failed");
    for (int i=0;i<*count;i++) {
        rows[i].kind = (int)read_u32(f);
        if (rows[i].kind != 0 && rows[i].kind != 1) die("invalid example kind");
        rows[i].system=read_text(f); rows[i].prompt=read_text(f);
        rows[i].chosen=read_text(f); rows[i].rejected=read_text(f);
        if (!*rows[i].chosen || (rows[i].kind && !*rows[i].rejected)) die("empty completion");
    }
    if (fgetc(f) != EOF) die("trailing bytes in dataset");
    fclose(f); return rows;
}
static int add_text(bpe_tokenizer *tok, int *ids, int n, const char *s) {
    int count = bpe_encode_raw(tok,s,ids+n,MAX_TOKENS-n);
    if (count < 0 || n+count >= MAX_TOKENS-1) die("example exceeds token capacity; do not truncate silently");
    return n+count;
}
static int role(bpe_tokenizer *tok,int *ids,int n,int im_start,const char *name,const char *content,int im_end) {
    ids[n++]=im_start; n=add_text(tok,ids,n,name); n=add_text(tok,ids,n,"\n");
    n=add_text(tok,ids,n,content); ids[n++]=im_end; return add_text(tok,ids,n,"\n");
}
static int capture_final(void *ctx,int layer,int pos,int n,int width,float *residual) {
    capture *c=ctx; if (layer != c->model->n_layers-1) return NT_OK;
    for (int row=0;row<n;row++) {
        int j=pos+row-c->start;
        if (j>=0 && j<c->seq->n)
            rmsnorm(c->seq->x->data+(size_t)j*width,residual+(size_t)row*width,
                    c->model->out_norm,width,c->model->rms_eps);
    }
    return NT_OK;
}
static void cache_sequence(llama_model *m,nt_dims dims,bpe_tokenizer *tok,const example *ex,const char *answer,sequence *seq) {
    int ids[MAX_TOKENS], n=0;
    int begin=bpe_token_id(tok,"<|im_start|>"),end=bpe_token_id(tok,"<|im_end|>");
    if (begin<0 || end<0) die("Qwen ChatML tokens are missing");
    n=role(tok,ids,n,begin,"system",ex->system,end);
    n=role(tok,ids,n,begin,"user",ex->prompt,end);
    ids[n++]=begin; n=add_text(tok,ids,n,"assistant\n");
    int prompt_n=n;
    n=add_text(tok,ids,n,answer); ids[n++]=end;
    seq->n=n-prompt_n;
    seq->x=nt_tensor_new2d(seq->n,m->embed);
    seq->logits=nt_tensor_new2d(seq->n,m->vocab);
    seq->targets=nt_tensor_new(seq->n);
    if (!seq->x || !seq->logits || !seq->targets) die("completion cache allocation failed");
    for (int t=0;t<seq->n;t++) seq->targets->data[t]=(float)ids[prompt_n+t];
    kv_cache *kv=kv_new(dims.n_layers,n,dims.kv_dim);
    if (!kv) die("KV allocation failed");
    capture ctx={m,seq,prompt_n-1};
    for (int pos=0;pos<n-1;) {
        int chunk=n-1-pos; if(chunk>32) chunk=32;
        int rc=nt_arch_llama.forward_residual(m,kv,ids+pos,chunk,pos,NULL,capture_final,&ctx);
        if (rc != NT_OK) die(nt_strerror(rc));
        pos+=chunk;
    }
    kv_free(kv);
    const wt *head=m->has_output_weight?&m->out_weight:&m->tok_emb;
    qmm(seq->logits->data,head,seq->x->data,seq->n);
    for (int i=0;i<seq->logits->len;i++) if(!isfinite(seq->logits->data[i])) die("nonfinite base logits");
}
static float value(int idx) {
    if(idx<0) die("tape operation failed");
    return nt_tape_get()->entries[idx].output->data[0];
}
/* Cached W*x plus the identical low-rank equation nt_lora_forward uses. */
static int loss(sequence *s,nt_lora_pair *adapter,int ai,int bi,int vocab) {
    int x=nt_tape_param_frozen(s->x),base=nt_tape_param_frozen(s->logits);
    int ax=nt_seq_linear(ai,x,s->n);
    int delta=nt_seq_linear(bi,ax,s->n);
    int logits=nt_add(base,nt_scale(delta,adapter->scaling));
    int targets=nt_tape_param_frozen(s->targets);
    int ce=nt_seq_cross_entropy(logits,targets,s->n,vocab);
    if(ce<0) die("cross entropy failed");
    return ce;
}
static float eval_ce(sequence *s,nt_lora_pair *a,int vocab) {
    nt_tape_start();
    int ai=nt_tape_param_frozen(a->A),bi=nt_tape_param_frozen(a->B);
    float ce=value(loss(s,a,ai,bi,vocab)); nt_tape_clear(); return ce;
}
static void save_adapter(const char *prefix,const char *suffix,nt_lora_pair *a) {
    char path[4096]; if(snprintf(path,sizeof(path),"%s%s",prefix,suffix)>=(int)sizeof(path)) die("output path too long");
    const char *names[]={"output.weight"};
    if(nt_lora_save(a,1,1,names,path)) die("could not save adapter");
    fprintf(stderr,"saved %s\n",path);
}
static void write_merged_head(llama_model *m,nt_lora_pair *a,const char *prefix,const sequence *probe) {
    const char *name=m->has_output_weight?"output.weight":"token_embd.weight";
    int ti=gguf_find_tensor(m->gf,name);
    float *head=gguf_dequant(m->gf,ti);
    if(!head) die("could not dequantize output head");
    float *before=malloc((size_t)m->vocab*sizeof(float));
    float *after=malloc((size_t)m->vocab*sizeof(float));
    float *delta=malloc((size_t)m->vocab*sizeof(float));
    float *low=malloc((size_t)a->rank*sizeof(float));
    if(!before || !after || !delta || !low) die("merge verification allocation failed");
    nt_blas_matvec(before,head,probe->x->data,m->vocab,m->embed);
    nt_blas_matvec(low,a->A->data,probe->x->data,a->rank,m->embed);
    nt_blas_matvec(delta,a->B->data,low,m->vocab,a->rank);
    nt_lora_merge_into(head,head,a,m->embed,m->vocab);
    nt_blas_matvec(after,head,probe->x->data,m->vocab,m->embed);
    float error=0,scale=0;
    for(int i=0;i<m->vocab;i++) {
        float expected=before[i]+a->scaling*delta[i];
        if(!isfinite(after[i]) || !isfinite(expected)) die("nonfinite merged head logits");
        error=fmaxf(error,fabsf(after[i]-expected)); scale=fmaxf(scale,fabsf(expected));
    }
    if(error>0.001f*(1+scale)) die("merged head does not match base plus LoRA");
    fprintf(stderr,"merged-head probe max_logit_error=%.8g\n",error);
    free(before);free(after);free(delta);free(low);
    char path[4096]; if(snprintf(path,sizeof(path),"%s.head.f32",prefix)>=(int)sizeof(path)) die("output path too long");
    FILE *out=fopen(path,"wb");
    size_t count=(size_t)m->embed*m->vocab;
    if(!out || fwrite(head,sizeof(float),count,out)!=count || fclose(out)) die("could not save merged head");
    free(head); fprintf(stderr,"saved %s (%zu floats)\n",path,count);
}
static void reset_optimizer(nt_lora_pair *a) {
    /* Re-register persistent slots so destroy also releases their Adam buffers. */
    nt_tape_start(); nt_tape_param(a->A); nt_tape_param(a->B); nt_tape_destroy();
}
static void shuffle(int *indices,int n) {
    for(int i=n-1;i>0;i--) { int j=rand()%(i+1),t=indices[i];indices[i]=indices[j];indices[j]=t; }
}
int main(int argc,char **argv) {
    if(argc<4 || argc>7) { fprintf(stderr,"usage: %s BASE.gguf DATA.bin OUTPUT_PREFIX [SFT_EPOCHS DPO_EPOCHS LR]\n",argv[0]);return 2; }
    int sft_epochs=argc>4?atoi(argv[4]):6,dpo_epochs=argc>5?atoi(argv[5]):3;
    float lr=argc>6?strtof(argv[6],NULL):0.0002f;
    if(sft_epochs<0 || dpo_epochs<0 || !(lr>0) || !isfinite(lr)) die("invalid epochs or learning rate");
    int count; example *rows=load_data(argv[2],&count);
    gguf_file *gf=gguf_open(argv[1]); if(!gf) die("could not open GGUF");
    if(strcmp(gf->arch,"qwen2")) die("this trainer expects the qwen2 family");
    nt_dims dims; llama_model *m=nt_arch_llama.load(gf,&dims);
    bpe_tokenizer *tok=bpe_load(argv[1]);
    if(!m || !tok) die("could not load Qwen body/tokenizer");
    nt_seed(20260928); srand(20260928);
    nt_lora_pair adapter;
    if(nt_lora_init(&adapter,m->embed,m->vocab,RANK,2*RANK)) die("adapter allocation failed");
    fprintf(stderr,"head LoRA rank=%d alpha=%d trainable=%d; frozen Qwen2 E=%d V=%d\n",RANK,2*RANK,adapter.A->len+adapter.B->len,m->embed,m->vocab);
    double start=now_ms(); long tokens=0;
    for(int i=0;i<count;i++) {
        cache_sequence(m,dims,tok,&rows[i],rows[i].chosen,&rows[i].c); tokens+=rows[i].c.n;
        if(rows[i].kind) {cache_sequence(m,dims,tok,&rows[i],rows[i].rejected,&rows[i].r);tokens+=rows[i].r.n;}
        fprintf(stderr,"cache %d/%d completion_tokens=%ld elapsed=%.1fs\n",i+1,count,tokens,(now_ms()-start)/1000);
    }
    int *order=malloc((size_t)count*sizeof(int)); if(!order) die("order allocation failed");
    for(int i=0;i<count;i++) order[i]=i;
    double sft_before=0; int nsft=0;
    for(int i=0;i<count;i++) if(!rows[i].kind){sft_before+=eval_ce(&rows[i].c,&adapter,m->vocab);nsft++;}
    printf("{\"stage\":\"sft_initial\",\"mean_example_ce\":%.8f,\"examples\":%d}\n",nsft?sft_before/nsft:0,nsft);fflush(stdout);
    for(int ep=0;ep<sft_epochs;ep++) {
        shuffle(order,count); double total=0;int n=0;
        for(int j=0;j<count;j++) {
            example *ex=&rows[order[j]];if(ex->kind)continue;
            nt_tape_start();int ai=nt_tape_param(adapter.A),bi=nt_tape_param(adapter.B);
            int ce=loss(&ex->c,&adapter,ai,bi,m->vocab);float v=value(ce);
            if(!isfinite(v))die("nonfinite SFT loss");
            nt_tape_backward(ce);nt_tape_clip_grads(1.0f);nt_tape_adam_step(lr);nt_tape_clear();total+=v;n++;
        }
        printf("{\"stage\":\"sft\",\"epoch\":%d,\"online_mean_ce\":%.8f}\n",ep+1,n?total/n:0);fflush(stdout);
    }
    save_adapter(argv[3],".sft.lora",&adapter);
    double sft_after=0;
    for(int i=0;i<count;i++) if(!rows[i].kind) sft_after+=eval_ce(&rows[i].c,&adapter,m->vocab);
    printf("{\"stage\":\"sft_final\",\"mean_example_ce\":%.8f}\n",nsft?sft_after/nsft:0);fflush(stdout);
    /* Save fixed post-SFT reference scores before the first DPO update. */
    for(int i=0;i<count;i++) if(rows[i].kind) {
        rows[i].c.ref_ce=eval_ce(&rows[i].c,&adapter,m->vocab);
        rows[i].r.ref_ce=eval_ce(&rows[i].r,&adapter,m->vocab);
    }
    reset_optimizer(&adapter); /* DPO starts a fresh optimizer, same policy weights. */
    for(int ep=0;ep<dpo_epochs;ep++) {
        shuffle(order,count);double total=0,margin_sum=0;int n=0;
        for(int j=0;j<count;j++) {
            example *ex=&rows[order[j]];if(!ex->kind)continue;
            nt_tape_start();int ai=nt_tape_param(adapter.A),bi=nt_tape_param(adapter.B);
            int ci=loss(&ex->c,&adapter,ai,bi,m->vocab),ri=loss(&ex->r,&adapter,ai,bi,m->vocab);
            float c=value(ci),r=value(ri);
            float margin=ex->c.n*(ex->c.ref_ce-c)-ex->r.n*(ex->r.ref_ce-r);
            float z=BETA*margin;
            float dpo=fmaxf(-z,0)+log1pf(expf(-fabsf(z)));
            float coeff=BETA/(1+expf(fmaxf(-80,fminf(80,z))));
            int weighted=nt_add(nt_scale(ci,coeff*ex->c.n),nt_scale(ri,-coeff*ex->r.n));
            if(!isfinite(dpo))die("nonfinite DPO loss");
            nt_tape_backward(weighted);nt_tape_clip_grads(1.0f);nt_tape_adam_step(lr*0.25f);nt_tape_clear();
            total+=dpo;margin_sum+=margin;n++;
        }
        printf("{\"stage\":\"dpo\",\"epoch\":%d,\"online_mean_loss\":%.8f,\"online_mean_margin\":%.8f}\n",ep+1,n?total/n:0,n?margin_sum/n:0);fflush(stdout);
    }
    double dpo_final=0,margin_final=0;int ndpo=0,preferred=0;
    for(int i=0;i<count;i++) if(rows[i].kind){
        float c=eval_ce(&rows[i].c,&adapter,m->vocab),r=eval_ce(&rows[i].r,&adapter,m->vocab);
        float margin=rows[i].c.n*(rows[i].c.ref_ce-c)-rows[i].r.n*(rows[i].r.ref_ce-r);
        float z=BETA*margin;dpo_final+=fmaxf(-z,0)+log1pf(expf(-fabsf(z)));margin_final+=margin;
        preferred+=margin>0;ndpo++;
    }
    printf("{\"stage\":\"dpo_final\",\"mean_loss\":%.8f,\"mean_margin\":%.8f,\"positive_margins\":%d,\"pairs\":%d}\n",ndpo?dpo_final/ndpo:0,ndpo?margin_final/ndpo:0,preferred,ndpo);fflush(stdout);
    save_adapter(argv[3],".lora",&adapter);write_merged_head(m,&adapter,argv[3],&rows[0].c);
    for(int i=0;i<count;i++) {
        free(rows[i].system);free(rows[i].prompt);free(rows[i].chosen);free(rows[i].rejected);
        nt_tensor_free(rows[i].c.x);nt_tensor_free(rows[i].c.logits);nt_tensor_free(rows[i].c.targets);
        if(rows[i].kind){nt_tensor_free(rows[i].r.x);nt_tensor_free(rows[i].r.logits);nt_tensor_free(rows[i].r.targets);}
    }
    reset_optimizer(&adapter);nt_lora_free(&adapter);bpe_free(tok);nt_arch_llama.free(m);gguf_close(gf);free(rows);free(order);
    return 0;
}
