/* Ordinary frozen Qwen post-block residuals, at two fixed causal positions.
 * Input: unchanged prompt-only JVRO1 (see extract_readout.c). One invocation
 * writes one source row so the caller can sync it before starting the next.
 * Output: JVRL1\0\0\0; u32LE rows=1,layers,positions=2,width; then u32LE
 * source_row,prompt_tokens,input_tokens,header_position,prefix_position;
 * then f32LE[positions][layers][width]. Layer IDs and positions are zero-based.
 * These are ordinary POST-BLOCK residuals, before the final output norm.
 * Unlike the older last-MLP-input z collector, NO model weight is modified.
 */
#define READOUT_MAIN readout_original_main
#include "extract_readout.c"
#undef READOUT_MAIN

#define LAYER_POSITIONS 2
#define LAYER_MAX 128
#define LAYER_VERIFY_ABS 1e-4
#define LAYER_VERIFY_REL 1e-5

typedef int (*layer_forward_fn)(void *,kv_cache *,const int *,int,int,float *,nt_residual_fn,void *);
typedef struct {
    int layers,width,input_tokens,positions[LAYER_POSITIONS];
    unsigned char seen[LAYER_POSITIONS*LAYER_MAX];
    float *features;
} layer_capture;
typedef struct { double max_abs,max_relative_l2; int vectors,pass; } layer_difference;

static void layer_die(const char *s) { fprintf(stderr,"extract-layers: %s\n",s);exit(1); }

static int layer_hook(void *ctx,int layer,int pos,int n,int width,float *residual) {
    layer_capture *c=ctx;
    if(!c||!residual||!c->features||c->layers<1||c->layers>LAYER_MAX||layer<0||layer>=c->layers||
       width<1||width!=c->width||n<1||pos<0||pos>=c->input_tokens||n>c->input_tokens-pos)
        return NT_E_ARG;
    for(int p=0;p<LAYER_POSITIONS;p++) {
        int offset=c->positions[p]-pos;
        if(offset<0||offset>=n)continue;
        int i=p*c->layers+layer;
        if(c->seen[i])return NT_E_STATE;
        const float *source=residual+(size_t)offset*width;
        for(int j=0;j<width;j++)if(!isfinite(source[j]))return NT_E_STATE;
        memcpy(c->features+(size_t)i*width,source,(size_t)width*sizeof(float));
        c->seen[i]=1;
    }
    return NT_OK;
}

/* The injectable forward is only for native fixtures; the CLI always passes
 * nt_arch_llama.forward_residual. Each call allocates a fresh empty KV cache. */
static int layer_capture_ids(llama_model *m,nt_dims dims,const int *ids,int n,
                             int header_position,int prefix_position,int chunk_size,
                             float *features,layer_forward_fn forward) {
    if(!m||!m->gf||!ids||!features||!forward||m->embed<1||m->n_layers<1||m->n_layers>LAYER_MAX||
       n<1||n>m->gf->ctx_len||header_position<0||header_position>=prefix_position||
       prefix_position>=n||chunk_size<1||chunk_size>NT_PREFILL_CHUNK||
       dims.n_layers!=m->n_layers||dims.kv_dim!=m->kv_dim||dims.vocab!=m->vocab||dims.kv_dim<1)
        return NT_E_ARG;
    for(int i=0;i<n;i++)if(ids[i]<0||ids[i]>=m->vocab)return NT_E_TOKEN;
    kv_cache *kv=kv_new(dims.n_layers,n,dims.kv_dim);
    if(!kv||!kv->k||!kv->v){kv_free(kv);return NT_E_MEMORY;}
    layer_capture c={.layers=m->n_layers,.width=m->embed,.input_tokens=n,
                     .positions={header_position,prefix_position},.features=features};
    int rc=NT_OK;
    for(int pos=0;pos<n;) {
        int chunk=n-pos;if(chunk>chunk_size)chunk=chunk_size;
        rc=forward(m,kv,ids+pos,chunk,pos,NULL,layer_hook,&c);
        if(rc!=NT_OK)break;
        pos+=chunk;
    }
    kv_free(kv);
    if(rc==NT_OK)for(int i=0;i<LAYER_POSITIONS*m->n_layers;i++)if(c.seen[i]!=1)return NT_E_STATE;
    return rc;
}

static layer_difference layer_compare(const float *reference,const float *other,int layers,int width) {
    layer_difference d={.vectors=LAYER_POSITIONS*layers,.pass=1};
    for(int i=0;i<d.vectors;i++) {
        double max_abs=0,square_diff=0,square_reference=0;
        for(int j=0;j<width;j++) {
            double a=reference[(size_t)i*width+j],b=other[(size_t)i*width+j];
            if(!isfinite(a)||!isfinite(b)){d.pass=0;return d;}
            double error=fabs(a-b);if(error>max_abs)max_abs=error;
            square_diff+=error*error;square_reference+=a*a;
        }
        double relative=sqrt(square_diff)/fmax(sqrt(square_reference),1e-30);
        if(max_abs>d.max_abs)d.max_abs=max_abs;
        if(relative>d.max_relative_l2)d.max_relative_l2=relative;
        if(max_abs>LAYER_VERIFY_ABS||relative>LAYER_VERIFY_REL)d.pass=0;
    }
    return d;
}

static void layer_verify(llama_model *m,nt_dims dims,const readout_row *r,const float *reference,
                         layer_difference differences[3]) {
    if(r->n_ids>m->gf->ctx_len-2)layer_die("verification requires room for two future tokens");
    size_t cells=(size_t)LAYER_POSITIONS*m->n_layers*m->embed;
    float *other=malloc(cells*sizeof(float));int *extended=malloc((size_t)(r->n_ids+2)*sizeof(int));
    if(!other||!extended)layer_die("verification allocation failed");
    memcpy(extended,r->ids,(size_t)r->n_ids*sizeof(int));
    extended[r->n_ids]=readout_prefix[0];extended[r->n_ids+1]=readout_prefix[1];
    for(int kind=0;kind<3;kind++) {
        if(kind==2)extended[r->n_ids]=readout_prefix[2];
        int n=kind?r->n_ids+2:r->n_ids;
        const int *ids=kind?extended:r->ids;
        int rc=layer_capture_ids(m,dims,ids,n,r->prompt_tokens-1,r->n_ids-1,
                                 kind?NT_PREFILL_CHUNK:1,other,nt_arch_llama.forward_residual);
        if(rc!=NT_OK)layer_die(nt_strerror(rc));
        differences[kind]=layer_compare(reference,other,m->n_layers,m->embed);
    }
    free(other);free(extended);
}

static void layer_trace(const readout_row *r,int row,const llama_model *m,int verify,int anchor,
                        const layer_difference differences[3]) {
    printf("{\"row\":%d,\"prompt_tokens\":%d,\"input_tokens\":%d,\"context_limit\":%d,"
           "\"feature_format\":\"JVRL1\",\"feature_shape\":[2,%d,%d],"
           "\"feature_order\":[\"position\",\"layer\",\"width\"],"
           "\"layer_boundary\":\"post_block_before_next_layer_or_final_output_norm\","
           "\"capture_positions\":[%d,%d],\"capture_names\":[\"assistant_header_end\",\"common_prefix_end\"],"
           "\"capture_token_ids\":[%d,%d],\"prefix_ids\":[4913,3903,819],"
           "\"ordinary_capture_weights_modified\":false,\"fresh_kv\":true,\"finite_features\":true,"
           "\"capture_counts\":[",row,r->prompt_tokens,r->n_ids,m->gf->ctx_len,m->n_layers,m->embed,
           r->prompt_tokens-1,r->n_ids-1,r->ids[r->prompt_tokens-1],r->ids[r->n_ids-1]);
    for(int i=0;i<LAYER_POSITIONS*m->n_layers;i++)printf("%s1",i?",":"");
    printf("],\"input_ids\":[");
    for(int i=0;i<r->n_ids;i++)printf("%s%d",i?",":"",r->ids[i]);
    printf("],\"anchor\":");
    if(anchor)printf("{\"feature_format\":\"JVRF1\",\"feature_shape\":[1,%d],"
                     "\"capture_position\":%d,\"layer\":%d,\"boundary\":\"pre_final_mlp\","
                     "\"fresh_kv\":true,\"temporary_zero_down\":true,\"down_bias_temporarily_disabled\":true,"
                     "\"projection_restored\":true}",m->embed,r->n_ids-1,m->n_layers-1);
    else printf("null");
    printf(",\"verification\":");
    if(!verify)printf("null");
    else {
        static const char *names[]={"token_step","future_append","future_change"};
        printf("{\"absolute_tolerance\":%.17g,\"relative_l2_tolerance\":%.17g,"
               "\"future_suffixes\":[[4913,3903],[819,3903]],\"comparisons\":[",LAYER_VERIFY_ABS,LAYER_VERIFY_REL);
        for(int i=0;i<3;i++)printf("%s{\"name\":\"%s\",\"vectors\":%d,\"max_abs\":%.17g,"
                                 "\"max_relative_l2\":%.17g,\"pass\":%s}",i?",":"",names[i],differences[i].vectors,
                                 differences[i].max_abs,differences[i].max_relative_l2,differences[i].pass?"true":"false");
        printf("]}");
    }
    puts("}");fflush(stdout);if(ferror(stdout))layer_die("cannot write trace");
}

#ifndef LAYER_MAIN
#define LAYER_MAIN main
#endif
int LAYER_MAIN(int argc,char **argv) {
    if(argc<5||argc>9) {
        fprintf(stderr,"usage: %s BASE.gguf PROMPTS.bin FEATURES.bin ROW [THREADS] [--verify] [--anchor ANCHOR.bin]\n",argv[0]);return 2;
    }
    int row=number(argv[4],0,9999),threads=4,verify=0;const char *anchor_path=NULL;
    for(int i=5;i<argc;i++) {
        if(!strcmp(argv[i],"--verify")){if(verify)layer_die("duplicate --verify");verify=1;}
        else if(!strcmp(argv[i],"--anchor")) {
            if(anchor_path||i+1>=argc)layer_die("--anchor needs exactly one new output path");
            anchor_path=argv[++i];
        }
        else if(i==5)threads=number(argv[i],1,16);
        else layer_die("unexpected argument");
    }
    char thread_text[16];snprintf(thread_text,sizeof(thread_text),"%d",threads);
    if(setenv("NT_NO_I8","1",1)||setenv("NT_QMV_THREADS",thread_text,1))layer_die("cannot set native execution mode");
    uint16_t endian=1;if(sizeof(float)!=4||*(unsigned char*)&endian!=1)layer_die("requires little-endian f32 host");
    int count;readout_row *rows=readout_data(argv[2],&count);
    if(row>=count)layer_die("source row is outside prompt dataset");
    gguf_file *gf=gguf_open(argv[1]);
    if(!gf||strcmp(gf->arch,"qwen2")||gf->n_layers!=24||gf->embed_dim!=896||
       !isfinite(gf->rms_eps)||fabsf(gf->rms_eps-1e-6f)>1e-12f)
        layer_die("requires Qwen2.5-Coder-0.5B shape: qwen2,24 layers,896 width,RMS epsilon 1e-6");
    bpe_tokenizer *tok=bpe_load(argv[1]);if(!tok)layer_die("cannot load model tokenizer");
    readout_row *r=&rows[row];readout_tokenize(r,tok);
    if(r->n_ids>gf->ctx_len)layer_die("prompt exceeds model context; no truncation");
    int fd=open(argv[3],O_WRONLY|O_CREAT|O_EXCL,0600);
    if(fd<0)layer_die("feature output must be a new writable file");
    FILE *out=fdopen(fd,"wb");if(!out)layer_die("cannot open feature stream");
    FILE *anchor_out=NULL;
    if(anchor_path) {
        int anchor_fd=open(anchor_path,O_WRONLY|O_CREAT|O_EXCL,0600);
        if(anchor_fd<0)layer_die("anchor output must be a new writable file");
        anchor_out=fdopen(anchor_fd,"wb");if(!anchor_out)layer_die("cannot open anchor stream");
    }
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);if(!m)layer_die("cannot load frozen model");
    size_t cells=(size_t)LAYER_POSITIONS*m->n_layers*m->embed;
    float *features=malloc(cells*sizeof(float));if(!features)layer_die("feature allocation failed");
    int rc=layer_capture_ids(m,dims,r->ids,r->n_ids,r->prompt_tokens-1,r->n_ids-1,
                            NT_PREFILL_CHUNK,features,nt_arch_llama.forward_residual);
    if(rc!=NT_OK)layer_die(nt_strerror(rc));
    layer_difference differences[3]={{0}};
    if(verify)layer_verify(m,dims,r,features,differences);
    /* Emit diagnostics on a failed numerical gate, but leave no valid feature
     * payload for a controller to mistake for a completed collection unit. */
    if(verify)for(int i=0;i<3;i++)if(!differences[i].pass) {
        layer_trace(r,row,m,verify,0,differences);layer_die("native verification gate failed");
    }
    if(anchor_out) {
        float *z=malloc((size_t)m->embed*sizeof(float));if(!z)layer_die("anchor allocation failed");
        readout_capture_ids(m,dims,r->ids,r->n_ids,r->n_ids-1,z,1);
        if(fwrite("JVRF1\0\0\0",1,8,anchor_out)!=8)layer_die("cannot write anchor header");
        readout_u32(anchor_out,1);readout_u32(anchor_out,(uint32_t)m->embed);
        if(fwrite(z,sizeof(float),(size_t)m->embed,anchor_out)!=(size_t)m->embed||
           fflush(anchor_out)||fsync(fileno(anchor_out))||fclose(anchor_out))layer_die("cannot finalize anchor");
        free(z);
    }
    if(fwrite("JVRL1\0\0\0",1,8,out)!=8)layer_die("cannot write feature header");
    readout_u32(out,1);readout_u32(out,(uint32_t)m->n_layers);readout_u32(out,LAYER_POSITIONS);readout_u32(out,(uint32_t)m->embed);
    readout_u32(out,(uint32_t)row);readout_u32(out,(uint32_t)r->prompt_tokens);readout_u32(out,(uint32_t)r->n_ids);
    readout_u32(out,(uint32_t)(r->prompt_tokens-1));readout_u32(out,(uint32_t)(r->n_ids-1));
    if(fwrite(features,sizeof(float),cells,out)!=cells||fflush(out)||fsync(fileno(out))||fclose(out))
        layer_die("cannot finalize feature row");
    layer_trace(r,row,m,verify,anchor_path!=NULL,differences);
    fprintf(stderr,"layers row=%d/%d input_tokens=%d shape=[2,%d,%d] verified=%s\n",
            row,count,r->n_ids,m->n_layers,m->embed,verify?"true":"false");
    free(features);nt_arch_llama.free(m);readout_free(rows,count);bpe_free(tok);gguf_close(gf);return 0;
}
