/* Per-layer frozen readout. One forward pass per sequence captures the residual
 * state at the decision position after EVERY decoder block, plus the final
 * post-norm z. Tokenization, prompt input format, decision position and the
 * JVRF1 output format are the frozen-readout ones, reused rather than restated:
 * this file adds only the multi-layer capture and one matrix file per depth.
 * stdout carries exactly the frozen extractor's per-row token trace, so a run
 * can be compared line for line against the published record.
 */
#define READOUT_MAIN extract_layers_unused_main
#include "extract_readout.c"

typedef struct { int position, layers, width, *seen; float *z; } layer_capture;

static int layer_hook(void *ctx,int layer,int pos,int n,int width,float *residual) {
    layer_capture *c=ctx;
    if(layer<0||layer>=c->layers||width!=c->width||n<1)return NT_E_ARG;
    if(c->position<pos||c->position-pos>=n)return NT_OK;
    if(c->seen[layer]++)return NT_E_ARG;
    memcpy(c->z+(size_t)layer*c->width,residual+(size_t)(c->position-pos)*width,
           (size_t)width*sizeof(float));
    return NT_OK;
}

/* No weight is modified here. The post-layer callback reports the residual
 * stream after block l, so depth l is read exactly as the model leaves it. */
static void layer_capture_ids(llama_model *m,nt_dims dims,const int *ids,int n,int position,float *z) {
    if(n<1||n>m->gf->ctx_len||position<0||position>=n)readout_die("invalid causal capture bounds");
    kv_cache *kv=kv_new(dims.n_layers,n,dims.kv_dim);
    if(!kv||!kv->k||!kv->v)readout_die("KV allocation failed");
    int *seen=calloc((size_t)m->n_layers,sizeof(int));
    if(!seen)readout_die("capture counter allocation failed");
    layer_capture c={position,m->n_layers,m->embed,seen,z};
    for(int pos=0;pos<n;) {
        int chunk=n-pos; if(chunk>NT_PREFILL_CHUNK)chunk=NT_PREFILL_CHUNK;
        int rc=nt_arch_llama.forward_residual(m,kv,ids+pos,chunk,pos,NULL,layer_hook,&c);
        if(rc!=NT_OK)readout_die(nt_strerror(rc));
        pos+=chunk;
    }
    kv_free(kv);
    for(int l=0;l<m->n_layers;l++)
        if(seen[l]!=1)readout_die("capture must observe exactly one position per layer");
    free(seen);
    rmsnorm(z+(size_t)m->n_layers*m->embed,z+(size_t)(m->n_layers-1)*m->embed,
            m->out_norm,m->embed,m->rms_eps);
    for(int l=0;l<=m->n_layers;l++)for(int j=0;j<m->embed;j++)
        if(!isfinite(z[(size_t)l*m->embed+j]))readout_die("nonfinite feature");
}

static FILE *layer_open(const char *dir,const char *name,int count,int width) {
    char path[1024];
    if(snprintf(path,sizeof(path),"%s/%s",dir,name)>=(int)sizeof(path))readout_die("output path too long");
    int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);
    if(fd<0)readout_die("each feature file must be a new writable file");
    FILE *f=fdopen(fd,"wb");
    if(!f)readout_die("cannot open feature stream");
    if(fwrite("JVRF1\0\0\0",1,8,f)!=8)readout_die("cannot write feature header");
    readout_u32(f,(uint32_t)count); readout_u32(f,(uint32_t)width);
    return f;
}

int main(int argc,char **argv) {
    if(argc<4||argc>5) {
        fprintf(stderr,"usage: %s BASE.gguf PROMPTS.bin OUTPUT_DIR [THREADS]\n",argv[0]);
        return 2;
    }
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
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);
    if(!m||!m->out_norm)readout_die("cannot load frozen model");
    int depths=m->n_layers+1;
    FILE **out=calloc((size_t)depths,sizeof(FILE*));
    float *z=malloc((size_t)depths*m->embed*sizeof(float));
    if(!out||!z)readout_die("feature allocation failed");
    for(int l=0;l<m->n_layers;l++) {
        char name[32];snprintf(name,sizeof(name),"features-l%02d.bin",l);
        out[l]=layer_open(argv[3],name,count,m->embed);
    }
    out[m->n_layers]=layer_open(argv[3],"features-postnorm.bin",count,m->embed);
    fprintf(stderr,"layers=%d depths=%d width=%d rows=%d\n",m->n_layers,depths,m->embed,count);
    for(int i=0;i<count;i++) {
        layer_capture_ids(m,dims,rows[i].ids,rows[i].n_ids,rows[i].n_ids-1,z);
        for(int l=0;l<depths;l++)
            if(fwrite(z+(size_t)l*m->embed,sizeof(float),(size_t)m->embed,out[l])!=(size_t)m->embed)
                readout_die("cannot write feature row");
        readout_trace(&rows[i],i,m->embed,0);
        fprintf(stderr,"layer-readout %d/%d input_tokens=%d width=%d depths=%d\n",
                i+1,count,rows[i].n_ids,m->embed,depths);
    }
    for(int l=0;l<depths;l++)if(fclose(out[l]))readout_die("cannot finalize features");
    free(out);free(z);
    nt_arch_llama.free(m);
    readout_free(rows,count);bpe_free(tok);gguf_close(gf);return 0;
}
