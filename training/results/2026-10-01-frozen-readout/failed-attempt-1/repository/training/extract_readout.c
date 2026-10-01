/* Frozen causal final-MLP-input readout. No labels or completions enter here.
 * Input: JVRO1\0\0\0, u32LE rows, then length-prefixed UTF-8 system/user.
 * Output: JVRF1\0\0\0, u32LE rows, u32LE width, row-major f32LE features.
 * Each feature is z at prompt + the fixed common JSON prefix, immediately
 * before predicting the class-specific token. stdout contains exact input IDs.
 * Reuse the actual trainer's ChatML functions, not an approximate template.
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main
#include <fcntl.h>

static const int readout_prefix[] = {4913,3903,819};
typedef struct { char *system, *user; int *ids, prompt_tokens, n_ids; } readout_row;
typedef struct { int layer, position, seen; float *z; int width; } readout_capture;

static void readout_die(const char *s) { fprintf(stderr,"extract-readout: %s\n",s); exit(1); }

static readout_row *readout_data(const char *path,int *count) {
    FILE *f=fopen(path,"rb"); unsigned char magic[8];
    if(!f||fread(magic,1,8,f)!=8||memcmp(magic,"JVRO1\0\0\0",8))readout_die("invalid prompt-only input");
    uint32_t n=mlp_u32(f);
    if(n<1||n>10000)readout_die("invalid prompt row count");
    readout_row *rows=calloc(n,sizeof(*rows));
    if(!rows)readout_die("prompt allocation failed");
    for(uint32_t i=0;i<n;i++) {
        rows[i].system=mlp_text(f); rows[i].user=mlp_text(f);
        if(!*rows[i].system||!*rows[i].user)readout_die("empty system or user prompt");
    }
    if(fgetc(f)!=EOF||ferror(f))readout_die("trailing or unreadable input bytes");
    fclose(f); *count=(int)n; return rows;
}

static void readout_tokenize(readout_row *r,bpe_tokenizer *tok) {
    int begin=bpe_token_id(tok,"<|im_start|>"),end=bpe_token_id(tok,"<|im_end|>");
    if(begin<0||end<0)readout_die("missing ChatML tokens");
    int prefix[16],np=bpe_encode_raw(tok,"{\"findings\":",prefix,16);
    if(np!=3||memcmp(prefix,readout_prefix,sizeof(readout_prefix)))
        readout_die("model tokenizer does not match frozen common prefix");
    r->ids=malloc(MLP_MAX_TOKENS*sizeof(int));
    if(!r->ids)readout_die("token allocation failed");
    int n=mlp_role(tok,r->ids,0,begin,"system",r->system,end);
    n=mlp_role(tok,r->ids,n,begin,"user",r->user,end);
    r->ids[n++]=begin; n=mlp_encode(tok,r->ids,n,"assistant\n");
    r->prompt_tokens=n;
    if(n>MLP_MAX_TOKENS-3)readout_die("prompt leaves no room for common prefix");
    memcpy(r->ids+n,readout_prefix,sizeof(readout_prefix)); r->n_ids=n+3;
}

static int readout_hook(void *ctx,int layer,int pos,int n,int width,float *residual) {
    readout_capture *c=ctx;
    if(layer!=c->layer)return NT_OK;
    if(width!=c->width||n<1)return NT_E_ARG;
    if(c->position<pos||c->position-pos>=n)return NT_OK;
    if(c->seen++)return NT_E_ARG;
    memcpy(c->z,residual+(size_t)(c->position-pos)*width,(size_t)width*sizeof(float));
    return NT_OK;
}

/* The post-layer callback observes z exactly when the final down weight/bias
 * are zero. This cannot alter later attention KVs: final-layer attention
 * consumes the preceding layer, never the final layer's MLP output. */
static void readout_capture_ids(llama_model *m,nt_dims dims,const int *ids,int n,
                                int position,float *z,int zero_down) {
    if(n<1||n>m->gf->ctx_len||position<0||position>=n)readout_die("invalid causal capture bounds");
    int last=m->n_layers-1;
    wt original=m->layers[last].wdown;
    float *bias=m->layers[last].ffn_down_bias,*zero=NULL;
    if(zero_down) {
        zero=calloc((size_t)m->embed*m->ffn,sizeof(float));
        if(!zero)readout_die("zero projection allocation failed");
        m->layers[last].wdown=(wt){.f32=zero,.dtype=0,.rows=m->embed,.cols=m->ffn};
        m->layers[last].ffn_down_bias=NULL;
    }
    kv_cache *kv=kv_new(dims.n_layers,n,dims.kv_dim);
    if(!kv||!kv->k||!kv->v)readout_die("KV allocation failed");
    readout_capture c={last,position,0,z,m->embed};
    for(int pos=0;pos<n;) {
        int chunk=n-pos; if(chunk>NT_PREFILL_CHUNK)chunk=NT_PREFILL_CHUNK;
        int rc=nt_arch_llama.forward_residual(m,kv,ids+pos,chunk,pos,NULL,readout_hook,&c);
        if(rc!=NT_OK)readout_die(nt_strerror(rc));
        pos+=chunk;
    }
    kv_free(kv);
    m->layers[last].wdown=original; m->layers[last].ffn_down_bias=bias; free(zero);
    if(c.seen!=1)readout_die("capture must observe exactly one position");
    for(int j=0;j<m->embed;j++)if(!isfinite(z[j]))readout_die("nonfinite feature");
}

static void readout_u32(FILE *f,uint32_t n) {
    unsigned char b[4]={(unsigned char)n,(unsigned char)(n>>8),(unsigned char)(n>>16),(unsigned char)(n>>24)};
    if(fwrite(b,1,4,f)!=4)readout_die("cannot write feature file");
}
static void readout_trace(const readout_row *r,int i,int width,int tokenize_only) {
    printf("{\"row\":%d,\"prompt_tokens\":%d,\"input_tokens\":%d,\"capture_position\":%d,"
           "\"feature_width\":%d,\"tokenize_only\":%s,\"prefix_ids\":[4913,3903,819],\"input_ids\":[",
           i,r->prompt_tokens,r->n_ids,r->n_ids-1,width,tokenize_only?"true":"false");
    for(int t=0;t<r->n_ids;t++)printf("%s%d",t?",":"",r->ids[t]);
    puts("]}"); fflush(stdout);
    if(ferror(stdout))readout_die("cannot write token trace");
}
static void readout_free(readout_row *rows,int count) {
    for(int i=0;i<count;i++){free(rows[i].system);free(rows[i].user);free(rows[i].ids);}free(rows);
}

#ifndef READOUT_MAIN
#define READOUT_MAIN main
#endif
int READOUT_MAIN(int argc,char **argv) {
    if(argc<4||argc>5) {
        fprintf(stderr,"usage: %s BASE.gguf PROMPTS.bin FEATURES.bin [THREADS]\n"
                       "       %s BASE.gguf PROMPTS.bin --tokenize-only\n",argv[0],argv[0]);
        return 2;
    }
    int tokenize_only=!strcmp(argv[3],"--tokenize-only");
    int threads=argc>4?number(argv[4],1,16):4;
    char thread_text[16];snprintf(thread_text,sizeof(thread_text),"%d",threads);
    if(setenv("NT_NO_I8","1",1)||setenv("NT_QMV_THREADS",thread_text,1))readout_die("cannot set native execution mode");
    uint16_t endian=1;
    if(sizeof(float)!=4||*(unsigned char*)&endian!=1)readout_die("requires little-endian f32 host");
    int count;readout_row *rows=readout_data(argv[2],&count);
    gguf_file *gf=gguf_open(argv[1]);
    if(!gf||strcmp(gf->arch,"qwen2")||gf->n_layers<1||!isfinite(gf->rms_eps)||fabsf(gf->rms_eps-1e-6f)>1e-12f)
        readout_die("requires qwen2 with RMS epsilon 1e-6");
    bpe_tokenizer *tok=bpe_load(argv[1]);if(!tok)readout_die("cannot load model tokenizer");
    for(int i=0;i<count;i++) {
        readout_tokenize(&rows[i],tok);
        if(rows[i].n_ids>gf->ctx_len)readout_die("prompt exceeds model context; no truncation");
    }
    if(tokenize_only) {
        for(int i=0;i<count;i++)readout_trace(&rows[i],i,gf->embed_dim,1);
    } else {
        /* Exclusive output guards archived experiment files against overwrite. */
        int fd=open(argv[3],O_WRONLY|O_CREAT|O_EXCL,0600);
        if(fd<0)readout_die("feature output must be a new writable file");
        FILE *out=fdopen(fd,"wb");if(!out)readout_die("cannot open feature stream");
        nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);
        if(!m||!m->layers[m->n_layers-1].ffn_norm)readout_die("cannot load frozen model");
        float *z=malloc((size_t)m->embed*sizeof(float));if(!z)readout_die("feature allocation failed");
        if(fwrite("JVRF1\0\0\0",1,8,out)!=8)readout_die("cannot write feature header");
        readout_u32(out,(uint32_t)count);readout_u32(out,(uint32_t)m->embed);
        for(int i=0;i<count;i++) {
            readout_capture_ids(m,dims,rows[i].ids,rows[i].n_ids,rows[i].n_ids-1,z,1);
            if(fwrite(z,sizeof(float),(size_t)m->embed,out)!=(size_t)m->embed)readout_die("cannot write feature row");
            readout_trace(&rows[i],i,m->embed,0);
            fprintf(stderr,"readout %d/%d input_tokens=%d width=%d\n",i+1,count,rows[i].n_ids,m->embed);
        }
        if(fclose(out))readout_die("cannot finalize features");
        free(z);nt_arch_llama.free(m);
    }
    readout_free(rows,count);bpe_free(tok);gguf_close(gf);return 0;
}
