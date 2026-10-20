/* Qwen2.5 all-layer LoRA SFT. Numerical operations and Chuck are NoTorch.
 * All seven attention/MLP projections in every block receive adapters.
 * Q/K rows are interleaved on load for nt_rope_freq and restored on export.
 * GQA repeats K/V using a frozen linear map, so GPU MHA and its backward
 * preserve the exact grouped-query computation without a second engine.
 */
#define _POSIX_C_SOURCE 200809L
#include "notorch.h"
#include "gguf.h"
#include "examples/bpe.h"
#include "harness/arch.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define TARGETS 7
#define TOKEN_LIMIT 8192
static const char *names[TARGETS] = {"attn_q", "attn_k", "attn_v", "attn_output", "ffn_gate", "ffn_up", "ffn_down"};
typedef struct {
    gguf_file *gf;
    int L,E,F,V,H,K,HD,Q,KD,rank;
    nt_tensor *emb,*norm,*head,*repeat;
    nt_tensor **w,**an,**fn,**bias;
    nt_lora_pair *lora;
    int *ti;
} full_model;
typedef struct {int *ids,n,start;} full_example;
static void die(const char *s) {fprintf(stderr,"train-full: %s\n",s);exit(1);}
static int ck(int x) {if(x<0)die("NoTorch operation failed");return x;}
static void *mem(size_t n) {void *p=calloc(1,n);if(!p)die("allocation failed");return p;}
#ifdef USE_CUDA
static void training_gpu(void) {
    /* NoTorch's default cuBLAS mode permits TF32. This trainer's parity and
     * optimizer contract is F32, so set NVIDIA's override before CUDA init. */
    if(setenv("NVIDIA_TF32_OVERRIDE","0",1))die("cannot select F32 CUDA arithmetic");
    extern int gpu_init(void);if(gpu_init())die("CUDA initialization failed");
    nt_set_gpu_mode(1);
}
#endif
static void read_exact(FILE *f,void *p,size_t n) {if(fread(p,1,n,f)!=n)die("truncated input");}
static void write_exact(FILE *f,const void *p,size_t n) {if(fwrite(p,1,n,f)!=n)die("write failed");}
static void close_sync(FILE *f) {if(fflush(f)||fsync(fileno(f))||fclose(f))die("checkpoint flush failed");}
static nt_tensor *vec(int n) {nt_tensor *t=nt_tensor_new(n);if(!t)die("tensor allocation failed");return t;}
static int frozen(nt_tensor *t) {return ck(nt_tape_param_frozen(t));}
static nt_tensor *value(int i) {if(i<0)die("missing tape output");nt_tensor *t=nt_tape_get()->entries[i].output;nt_tensor_sync_cpu(t);return t;}
static uint32_t word(FILE *f) {uint32_t n;read_exact(f,&n,4);return n;}
static int integer(const char *s,int lo,int hi) {char *e;errno=0;long n=strtol(s,&e,10);if(errno||!*s||*e||n<lo||n>hi)die("invalid integer option");return (int)n;}
static char *field(FILE *f) {uint32_t n=word(f);if(n>1048576)die("dataset field too large");char *s=mem(n+1);read_exact(f,s,n);if(memchr(s,0,n))die("NUL in dataset");return s;}
static int enc(bpe_tokenizer *tok,int *ids,int n,const char *s) {int k=bpe_encode_raw(tok,s,ids+n,TOKEN_LIMIT-n);if(k<0||n+k>=TOKEN_LIMIT-2)die("example exceeds context; no truncation");return n+k;}
static int role(bpe_tokenizer *tok,int *ids,int n,int bos,int eos,const char *who,const char *s) {
    ids[n++]=bos;n=enc(tok,ids,n,who);n=enc(tok,ids,n,"\n");n=enc(tok,ids,n,s);ids[n++]=eos;return enc(tok,ids,n,"\n");
}
static full_example *dataset(const char *path,bpe_tokenizer *tok,int *count) {
    FILE *f=fopen(path,"rb");if(!f)die("cannot read dataset");char magic[8];read_exact(f,magic,8);
    if(memcmp(magic,"JVDS\1\0\0\0",8))die("not a JVDS dataset");
    *count=(int)word(f);if(*count<1||*count>100000)die("invalid dataset count");
    int bos=bpe_token_id(tok,"<|im_start|>"),eos=bpe_token_id(tok,"<|im_end|>");if(bos<0||eos<0)die("missing Qwen ChatML tokens");
    full_example *rows=mem(sizeof(*rows)*(size_t)*count);
    for(int i=0;i<*count;i++) {
        if(word(f)!=0)die("SFT-only data required");
        char *s=field(f),*u=field(f),*a=field(f),*r=field(f);if(!*a||*r)die("invalid SFT answer");
        rows[i].ids=mem(TOKEN_LIMIT*sizeof(int));int *ids=rows[i].ids;
        int n=role(tok,ids,0,bos,eos,"system",s);n=role(tok,ids,n,bos,eos,"user",u);
        ids[n++]=bos;n=enc(tok,ids,n,"assistant\n");rows[i].start=n-1;
        n=enc(tok,ids,n,a);ids[n++]=eos;rows[i].n=n;
        free(s);free(u);free(a);free(r);
    }
    if(fgetc(f)!=EOF)die("trailing dataset bytes");
    fclose(f);return rows;
}
static nt_tensor *load_tensor(gguf_file *g,const char *name,int optional) {
    int i=gguf_find_tensor(g,name);if(i<0){if(optional)return NULL;fprintf(stderr,"missing %s\n",name);die("missing tensor");}
    gguf_tensor_info *d=&g->tensors[i];if(d->ndim<1||d->ndim>2||d->n_elements>INT32_MAX)die("unsupported tensor shape");
    nt_tensor *t=d->ndim==2?nt_tensor_new2d((int)d->shape[1],(int)d->shape[0]):vec((int)d->shape[0]);
    if(!t)die("tensor allocation failed");
    float *p=gguf_dequant(g,i);if(!p)die("dequantization failed");
    memcpy(t->data,p,d->n_elements*sizeof(float));free(p);return t;
}
/* forward permutation: new[2*i]=old[i], new[2*i+1]=old[i+HD/2]. */
static void permute(float *p,int rows,int cols,int hd,int inverse) {
    if(rows%hd||hd%2)die("invalid rotary dimensions");
    float *tmp=mem((size_t)rows*cols*sizeof(float));
    for(int h=0;h<rows/hd;h++)for(int j=0;j<hd;j++) {
        int a=h*hd+j,b=h*hd+j/2+(j%2)*(hd/2);
        memcpy(tmp+(size_t)(inverse?b:a)*cols,p+(size_t)(inverse?a:b)*cols,(size_t)cols*sizeof(float));
    }
    memcpy(p,tmp,(size_t)rows*cols*sizeof(float));free(tmp);
}
static full_model load_model(const char *path,int rank) {
    full_model m={0};m.gf=gguf_open(path);if(!m.gf||strcmp(m.gf->arch,"qwen2"))die("Qwen2 GGUF required");
    gguf_file *g=m.gf;m.L=g->n_layers;m.E=g->embed_dim;m.F=g->ffn_dim;m.H=g->n_heads;m.K=g->n_kv_heads;m.rank=rank;
    if(m.L<1||m.H<1||m.K<1||m.H%m.K||m.L*14>NT_TAPE_MAX_PARAMS||fabsf(g->rms_eps-1e-6f)>1e-10f)die("unsupported Qwen configuration");
    m.emb=load_tensor(g,"token_embd.weight",0);m.V=m.emb->shape[0];m.norm=load_tensor(g,"output_norm.weight",0);
    m.head=load_tensor(g,"output.weight",1);if(!m.head){m.head=m.emb;nt_tensor_ref(m.head);}
    m.w=mem(m.L*TARGETS*sizeof(*m.w));m.ti=mem(m.L*TARGETS*sizeof(*m.ti));m.lora=mem(m.L*TARGETS*sizeof(*m.lora));
    m.an=mem(m.L*sizeof(*m.an));m.fn=mem(m.L*sizeof(*m.fn));m.bias=mem(m.L*3*sizeof(*m.bias));
    for(int l=0;l<m.L;l++) {
        char name[128];snprintf(name,sizeof name,"blk.%d.attn_norm.weight",l);m.an[l]=load_tensor(g,name,0);
        snprintf(name,sizeof name,"blk.%d.ffn_norm.weight",l);m.fn[l]=load_tensor(g,name,0);
        if(m.an[l]->len!=m.E||m.fn[l]->len!=m.E)die("norm dimensions disagree");
        for(int j=0;j<TARGETS;j++) {
            int z=l*TARGETS+j;snprintf(name,sizeof name,"blk.%d.%s.weight",l,names[j]);m.w[z]=load_tensor(g,name,0);m.ti[z]=gguf_find_tensor(g,name);
            nt_tensor *w=m.w[z];if(w->ndim!=2)die("matrix required");
            if(l==0&&j==0){m.Q=w->shape[0];m.HD=m.Q/m.H;m.KD=m.HD*m.K;if(m.Q%m.H||m.HD%2)die("invalid head dimensions");}
            int in=j==6?m.F:(j==3?m.Q:m.E),out=(j==1||j==2)?m.KD:(j==4||j==5)?m.F:j==0?m.Q:m.E;
            if(w->shape[0]!=out||w->shape[1]!=in)die("projection dimensions disagree");
            if(j<2)permute(w->data,out,in,m.HD,0);
            if(nt_lora_init(&m.lora[z],in,out,rank,rank*2.0f))die("LoRA allocation failed");
            if(j<3){snprintf(name,sizeof name,"blk.%d.%s.bias",l,names[j]);m.bias[l*3+j]=load_tensor(g,name,0);
                if(m.bias[l*3+j]->len!=out)die("bias dimensions disagree");
                if(j<2)permute(m.bias[l*3+j]->data,out,1,m.HD,0);}
        }
        snprintf(name,sizeof name,"blk.%d.ffn_down.bias",l);if(gguf_find_tensor(g,name)>=0)die("shifted base is unsupported");
    }
    if(m.emb->shape[1]!=m.E||m.head->shape[0]!=m.V||m.head->shape[1]!=m.E||m.norm->len!=m.E)die("embedding/head dimensions disagree");
    m.repeat=nt_tensor_new2d(m.Q,m.KD);if(!m.repeat)die("GQA map allocation failed");
    for(int h=0;h<m.H;h++)for(int d=0;d<m.HD;d++)m.repeat->data[(size_t)(h*m.HD+d)*m.KD+(h/(m.H/m.K))*m.HD+d]=1;
    size_t total=0;for(int i=0;i<m.L*TARGETS;i++)total+=m.lora[i].A->len+m.lora[i].B->len;
    printf("{\"event\":\"model\",\"layers\":%d,\"targets_per_layer\":7,\"rank\":%d,\"trainable_parameters\":%zu}\n",m.L,rank,total);fflush(stdout);
    return m;
}
static int project(full_model *m,int l,int j,int x,int T) {int z=l*TARGETS+j;return ck(nt_lora_forward(frozen(m->w[z]),&m->lora[z],x,T));}
static int forward(full_model *m,const int *ids,int T) {
    nt_tensor *emb=vec(T*m->E);
    for(int t=0;t<T;t++){if(ids[t]<0||ids[t]>=m->V)die("token out of vocabulary");memcpy(emb->data+(size_t)t*m->E,m->emb->data+(size_t)ids[t]*m->E,m->E*sizeof(float));}
    int x=frozen(emb);nt_tensor_free(emb);
    for(int l=0;l<m->L;l++) {
        int n=ck(nt_seq_rmsnorm(x,frozen(m->an[l]),T,m->E));
        int q=ck(nt_add(project(m,l,0,n,T),frozen(m->bias[l*3])));
        int k=ck(nt_add(project(m,l,1,n,T),frozen(m->bias[l*3+1])));
        int v=ck(nt_add(project(m,l,2,n,T),frozen(m->bias[l*3+2])));
        q=ck(nt_rope_freq(q,T,m->HD,m->gf->rope_freq_base));k=ck(nt_rope_freq(k,T,m->HD,m->gf->rope_freq_base));
        k=ck(nt_seq_linear(frozen(m->repeat),k,T));v=ck(nt_seq_linear(frozen(m->repeat),v,T));
        int a=ck(nt_mh_causal_attention(q,k,v,T,m->HD));x=ck(nt_add(x,project(m,l,3,a,T)));
        n=ck(nt_seq_rmsnorm(x,frozen(m->fn[l]),T,m->E));
        int gate=project(m,l,4,n,T),up=project(m,l,5,n,T);
        int hidden=ck(nt_mul(ck(nt_silu(gate)),up));x=ck(nt_add(x,project(m,l,6,hidden,T)));
    }
    x=ck(nt_seq_rmsnorm(x,frozen(m->norm),T,m->E));return ck(nt_seq_linear(frozen(m->head),x,T));
}
static int loss_for(full_model *m,const full_example *e) {
    int T=e->n-1;nt_tensor *target=vec(T),*mask=vec(T);
    for(int t=0;t<T;t++){target->data[t]=(float)e->ids[t+1];mask->data[t]=t>=e->start?1:0;}
    int target_i=frozen(target),mask_i=frozen(mask);nt_tensor_free(target);nt_tensor_free(mask);
    int logits=forward(m,e->ids,T);return ck(nt_seq_cross_entropy_masked(logits,target_i,mask_i,T,m->V));
}
static void adapter_io(full_model *m,const char *dir,int save) {
    for(int j=0;j<TARGETS;j++){
        nt_lora_pair *p=mem(m->L*sizeof(*p));for(int l=0;l<m->L;l++)p[l]=m->lora[l*TARGETS+j];
        char path[2048];snprintf(path,sizeof path,"%s/%s.lora",dir,names[j]);const char *n[]={names[j]};
        int rc=save?nt_lora_save(p,m->L,1,n,path):nt_lora_load(p,m->L,1,n,path);free(p);if(rc)die("adapter I/O failed");
        if(save){int fd=open(path,O_RDONLY);if(fd<0||fsync(fd)||close(fd))die("adapter flush failed");}
    }
}
static int optimizer_io(full_model *m,const char *dir,int save,int step) {
    char path[2048];snprintf(path,sizeof path,"%s/optimizer.bin",dir);FILE *f=fopen(path,save?"wb":"rb");if(!f)die("optimizer I/O failed");
    nt_tape *tp=nt_tape_get();int n=m->L*TARGETS*2;uint32_t header[4]={0x4a564f31,1,(uint32_t)n,(uint32_t)step};
    uint32_t rng=nt_chuck_rng_get();
    if(save){write_exact(f,header,sizeof header);write_exact(f,&tp->chuck,sizeof tp->chuck);write_exact(f,&rng,4);}
    else {read_exact(f,header,sizeof header);if(header[0]!=0x4a564f31||header[1]!=1||header[2]!=(uint32_t)n||header[3]>INT32_MAX)die("incompatible optimizer checkpoint");step=(int)header[3];read_exact(f,&tp->chuck,sizeof tp->chuck);read_exact(f,&rng,4);if(nt_chuck_rng_set(rng))die("invalid Chuck RNG");}
    for(int i=0;i<n;i++){
        nt_lora_pair *p=&m->lora[i/2];int len=i%2?p->B->len:p->A->len;nt_adam_state *as=&tp->adam[i];
        uint32_t h[3]={(uint32_t)len,(uint32_t)as->t,as->m?1:0};
        if(save){write_exact(f,h,sizeof h);write_exact(f,&tp->chuck_params[i],sizeof tp->chuck_params[i]);}
        else {read_exact(f,h,sizeof h);if(h[0]!=(uint32_t)len||h[1]>INT32_MAX||h[2]>1)die("invalid optimizer slot");as->t=(int)h[1];read_exact(f,&tp->chuck_params[i],sizeof tp->chuck_params[i]);}
        if(h[2])for(int j=0;j<2;j++){
            nt_tensor **t=j?&as->v:&as->m;
            if(save){if(!*t)die("missing optimizer moment");nt_tensor_sync_cpu(*t);write_exact(f,(*t)->data,len*sizeof(float));}
            else {if(*t)nt_tensor_free(*t);*t=vec(len);read_exact(f,(*t)->data,len*sizeof(float));for(int k=0;k<len;k++)if(!isfinite((*t)->data[k]))die("nonfinite optimizer moment");}
        }
    }
    if(save)close_sync(f);else{if(fgetc(f)!=EOF)die("trailing optimizer bytes");fclose(f);}return step;
}
static void checkpoint(full_model *m,const char *root,int step) {
    char path[2048],tmp[2048],file[2200];snprintf(path,sizeof path,"%s/step-%06d",root,step);snprintf(tmp,sizeof tmp,"%s/step-%06d.tmp",root,step);
    if(mkdir(tmp,0700))die("checkpoint directory already exists or cannot be created");
    adapter_io(m,tmp,1);optimizer_io(m,tmp,1,step);
    snprintf(file,sizeof file,"%s/state.json",tmp);FILE *f=fopen(file,"w");if(!f)die("checkpoint state failed");
    fprintf(f,"{\"step\":%d,\"layers\":%d,\"rank\":%d,\"alpha\":%d,\"optimizer\":\"chuck\",\"qk_layout\":\"interleaved\"}\n",step,m->L,m->rank,m->rank*2);close_sync(f);
    if(rename(tmp,path))die("checkpoint rename failed");
    printf("{\"event\":\"checkpoint\",\"step\":%d,\"path\":\"%s\"}\n",step,path);fflush(stdout);
    if(getenv("JOVOVICH_REQUIRE_ACK")) {char line[80],expected[80];snprintf(expected,sizeof expected,"ACK %d\n",step);if(!fgets(line,sizeof line,stdin)||strcmp(line,expected))die("checkpoint archive ACK missing");}
}
static uint32_t shuffle_word(uint32_t *x){*x^=*x<<13;*x^=*x>>17;*x^=*x<<5;return *x;}
static void order_for(int *order,int n,int epoch) {for(int i=0;i<n;i++)order[i]=i;uint32_t state=20261020u+(uint32_t)epoch*7919u;for(int i=n-1;i>0;i--){int j=(int)(shuffle_word(&state)%(uint32_t)(i+1));int v=order[i];order[i]=order[j];order[j]=v;}}
static void gradients(full_model *m) {
    nt_tape *tp=nt_tape_get();int found=0;double by_target[TARGETS]={0};
    for(int l=0;l<m->L;l++)for(int j=0;j<TARGETS;j++){
        nt_tensor *p=m->lora[l*TARGETS+j].B;double sq=0;int seen=0;
        for(int k=0;k<tp->count;k++)if(tp->entries[k].output==p&&tp->entries[k].grad){nt_tensor *g=tp->entries[k].grad;nt_tensor_sync_cpu(g);for(int z=0;z<g->len;z++){if(!isfinite(g->data[z]))die("nonfinite adapter gradient");sq+=(double)g->data[z]*g->data[z];}seen++;}
        if(seen!=1||sq<=0)die("adapter target received no gradient");
        by_target[j]+=sq;found++;
    }
    printf("{\"event\":\"gradient_flow\",\"active_projections\":%d,\"target_norms\":[",found);
    for(int j=0;j<TARGETS;j++)printf("%s%.9g",j?",":"",sqrt(by_target[j]));
    puts("]}");fflush(stdout);
}
/* Frozen leaves can receive a gradient from some tape operations. They are
 * not optimizer parameters and must not contribute to the clipping norm. */
static float clip_adapters(float limit) {
    nt_tape *tp=nt_tape_get();
    for(int i=0;i<tp->count;i++) {
        nt_tape_entry *e=&tp->entries[i];
        if(e->is_param&&e->frozen&&e->grad){nt_tensor_free(e->grad);e->grad=NULL;}
    }
    return nt_tape_clip_grads(limit);
}
static void parity_with(full_model *m,gguf_file *reference,const int *ids,int T) {
    /* Compare the same F32 activations. The inference default additionally
     * quantizes activations for int8 dot products, which training does not. */
    const char *setting=getenv("NT_NO_I8");char *saved=setting?strdup(setting):NULL;
    if(setting&&!saved)die("allocation failed");
    if(setenv("NT_NO_I8","1",1))die("cannot set reference precision");
    nt_dims dims;void *base=nt_arch_llama.load(reference,&dims);if(!base)die("harness load failed");
    if(dims.vocab!=m->V)die("reference vocabulary differs");
    if(saved){if(setenv("NT_NO_I8",saved,1))die("cannot restore precision");free(saved);}
    else if(unsetenv("NT_NO_I8"))die("cannot restore precision");
    kv_cache *kv=kv_new(dims.n_layers,T+1,dims.kv_dim);if(!kv)die("KV allocation failed");float *ref=mem(m->V*sizeof(float));
    if(nt_arch_llama.forward(base,kv,ids,T,0,ref))die("harness forward failed");
    nt_tape_start();int out=forward(m,ids,T);nt_tensor *got=value(out);double delta=0,scale=0,max=0;int ai=0,bi=0;
    for(int i=0;i<m->V;i++){float a=got->data[(T-1)*m->V+i],b=ref[i];if(!isfinite(a)||!isfinite(b))die("nonfinite parity logit");double d=(double)a-b;delta+=d*d;scale+=(double)b*b;if(fabs(d)>max)max=fabs(d);if(a>got->data[(T-1)*m->V+ai])ai=i;if(b>ref[bi])bi=i;}
    double relative=sqrt(delta/fmax(scale,1e-30));printf("{\"event\":\"forward_parity\",\"tokens\":%d,\"relative_l2\":%.9g,\"max_abs\":%.9g,\"argmax_equal\":%s}\n",T,relative,max,ai==bi?"true":"false");fflush(stdout);
    if(relative>0.001||max>0.03||ai!=bi)die("trainer and inference logits disagree");
    nt_tape_clear();kv_free(kv);nt_arch_llama.free(base);free(ref);
}
static void parity(full_model *m,const int *ids,int T) {parity_with(m,m->gf,ids,T);}
/* Export all adapted projections, preserving original tokenizer/metadata and
 * untouched tensor bytes. Directory offsets/dtypes are the only header edits. */
static void copy_bytes(FILE *in,FILE *out,uint64_t pos,uint64_t n){if(fseeko(in,(off_t)pos,SEEK_SET))die("GGUF seek failed");char buf[65536];while(n){size_t z=n<sizeof buf?(size_t)n:sizeof buf;read_exact(in,buf,z);write_exact(out,buf,z);n-=z;}}
static void export_model(full_model *m,const char *source,const char *path) {
    gguf_file *g=m->gf;const gguf_kv *align=gguf_get_kv(g,"general.alignment");if(align&&align->val.u32!=32)die("unsupported GGUF alignment");
    FILE *in=fopen(source,"rb");int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);if(!in||fd<0)die("cannot create export");FILE *out=fdopen(fd,"wb");if(!out)die("cannot open export stream");
    uint64_t *positions=mem(g->n_tensors*sizeof(uint64_t)),*offsets=mem(g->n_tensors*sizeof(uint64_t));int *which=mem(g->n_tensors*sizeof(int));
    for(uint64_t i=0;i<g->n_tensors;i++)which[i]=-1;
    for(int j=0;j<m->L*TARGETS;j++)which[m->ti[j]]=j;
    if(fseeko(in,(off_t)g->kv_end,SEEK_SET))die("directory seek failed");
    uint64_t cursor=0;
    for(uint64_t i=0;i<g->n_tensors;i++) {uint64_t n;read_exact(in,&n,8);if(n>127||fseeko(in,(off_t)n,SEEK_CUR))die("invalid tensor name");uint32_t ndim=word(in);if(ndim<1||ndim>4||fseeko(in,ndim*8,SEEK_CUR))die("invalid tensor directory");positions[i]=(uint64_t)ftello(in);if(fseeko(in,12,SEEK_CUR))die("invalid tensor directory");offsets[i]=cursor;uint64_t bytes=which[i]>=0?g->tensors[i].n_elements*4:gguf_type_size(g->tensors[i].dtype,g->tensors[i].n_elements);if(!bytes)die("unsupported tensor dtype");cursor=(cursor+bytes+31)&~UINT64_C(31);}
    copy_bytes(in,out,0,g->data_offset);
    for(uint64_t i=0;i<g->n_tensors;i++){uint32_t type=which[i]>=0?GGUF_TYPE_F32:g->tensors[i].dtype;if(fseeko(out,(off_t)positions[i],SEEK_SET))die("export seek failed");write_exact(out,&type,4);write_exact(out,&offsets[i],8);}
    if(fseeko(out,(off_t)g->data_offset,SEEK_SET))die("export seek failed");
    for(uint64_t i=0;i<g->n_tensors;i++) {
        int z=which[i];if(z>=0){nt_tensor *w=m->w[z];float *merged=mem(w->len*sizeof(float));nt_lora_merge_into(merged,w->data,&m->lora[z],w->shape[1],w->shape[0]);if(z%TARGETS<2)permute(merged,w->shape[0],w->shape[1],m->HD,1);for(int k=0;k<w->len;k++)if(!isfinite(merged[k]))die("nonfinite export weight");write_exact(out,merged,w->len*sizeof(float));free(merged);}
        else copy_bytes(in,out,g->data_offset+g->tensors[i].offset,gguf_type_size(g->tensors[i].dtype,g->tensors[i].n_elements));
        long pos=ftell(out);if(pos<0)die("export position failed");unsigned char zero[32]={0};write_exact(out,zero,(size_t)(-(uint64_t)pos&31));
    }
    close_sync(out);fclose(in);free(positions);free(offsets);free(which);printf("{\"event\":\"exported\",\"projections\":%d}\n",m->L*TARGETS);
}
#ifndef FULL_LORA_NO_MAIN
int main(int argc,char **argv) {
    if(argc<2)die("usage: train-full base.gguf curriculum.bin output_dir epochs lr [rank] [resume_dir]; or --check base.gguf curriculum.bin; or --export base.gguf checkpoint_dir output.gguf [rank]; or --verify-export base.gguf checkpoint_dir output.gguf curriculum.bin [rank]");
    int verify=!strcmp(argv[1],"--verify-export");
    if(verify) {
        if(argc<6||argc>7)die("invalid export verification arguments");
        nt_seed(20261020);full_model m=load_model(argv[2],argc==7?integer(argv[6],1,128):16);
        adapter_io(&m,argv[3],0);gguf_file *ref=gguf_open(argv[4]);if(!ref)die("cannot read exported model");
        bpe_tokenizer *tok=bpe_load(argv[2]);if(!tok)die("cannot load tokenizer");int count=0;
        full_example *data=dataset(argv[5],tok,&count);
        /* Export verification must include the complete real example; a short
         * identity prefix does not exercise review-context rotary positions. */
        parity_with(&m,ref,data[0].ids,data[0].n-1);return 0;
    }
    int check=!strcmp(argv[1],"--check"),exporting=!strcmp(argv[1],"--export");
    if((check&&argc!=4)||(exporting&&(argc<5||argc>6))||(!check&&!exporting&&(argc<6||argc>8)))die("invalid arguments");
    nt_seed(20261020);int rank=exporting?(argc==6?integer(argv[5],1,128):16):(!check&&argc>6?integer(argv[6],1,128):16);
    const char *base=(check||exporting)?argv[2]:argv[1];full_model m=load_model(base,rank);
    if(exporting){adapter_io(&m,argv[3],0);export_model(&m,base,argv[4]);return 0;}
    bpe_tokenizer *tok=bpe_load(base);if(!tok)die("cannot load tokenizer");int count=0;
    full_example *data=dataset(check?argv[3]:argv[2],tok,&count);
#ifdef USE_CUDA
    if(!getenv("JOVOVICH_CPU"))training_gpu();
#endif
    if(check){int T=data[0].n-1;if(T>64)T=64;parity(&m,data[0].ids,T);return 0;}
    const char *root=argv[3];if(strspn(root,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/.")!=strlen(root))die("output path must use simple ASCII characters");
    if(mkdir(root,0700))die("fresh output directory required");
    int epochs=integer(argv[4],1,100);char *end;float lr=strtof(argv[5],&end);if(!*argv[5]||*end||!isfinite(lr)||lr<=0||lr>0.01)die("invalid learning rate");
    int steps=epochs*count,start=0;if(argc==8){adapter_io(&m,argv[7],0);start=optimizer_io(&m,argv[7],0,0);if(start>=steps)die("resume step beyond schedule");}
    if(start==0)parity(&m,data[0].ids,data[0].n>65?64:data[0].n-1);
    printf("{\"event\":\"training\",\"examples\":%d,\"epochs\":%d,\"steps\":%d,\"start\":%d,\"lr\":%.9g,\"gpu\":%s}\n",count,epochs,steps,start,lr,nt_get_gpu_mode()?"true":"false");
    checkpoint(&m,root,start);int *order=mem(count*sizeof(int));int prev_epoch=-1;
    for(int step=start;step<steps;step++) {
        int epoch=step/count;if(epoch!=prev_epoch){order_for(order,count,epoch);prev_epoch=epoch;}
        int row=order[step%count];nt_tape_start();int li=loss_for(&m,&data[row]);float loss=value(li)->data[0];if(!isfinite(loss))die("nonfinite loss");
        nt_tape_backward(li);if(step==start)gradients(&m);
        float norm=clip_adapters(1.0f);if(!isfinite(norm))die("nonfinite gradient norm");
        int warm=steps/20;if(warm<1)warm=1;float factor=step<warm?(float)(step+1)/warm:0.1f+0.45f*(1.0f+cosf(3.14159265358979323846f*(step-warm)/(steps-warm)));
        if(nt_tape_chuck_step_action(lr*factor,loss,NULL,NULL)!=NT_CHUCK_OK)die("Chuck update failed");
        printf("{\"event\":\"step\",\"step\":%d,\"epoch\":%d,\"row\":%d,\"tokens\":%d,\"loss\":%.9g,\"gradient_norm\":%.9g,\"lr\":%.9g}\n",step+1,epoch+1,row,data[row].n-1,loss,norm,lr*factor);fflush(stdout);
        if((step+1)%25==0||step+1==steps)checkpoint(&m,root,step+1);
    }
    puts("{\"event\":\"completed\"}");fflush(stdout);return 0;
}
#endif
