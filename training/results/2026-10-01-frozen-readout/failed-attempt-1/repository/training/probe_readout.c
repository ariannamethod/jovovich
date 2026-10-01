/* Independent gates for the prompt-only extractor. This audit executable may
 * read gold completions solely to compare with the existing trainer cache.
 * The production extractor never opens an SFT dataset. Audit the first two
 * prompt-only rows, finding their exact system/user counterparts in SFT.bin.
 */
#define READOUT_MAIN readout_extractor_main
#include "extract_readout.c"
#undef READOUT_MAIN

typedef struct { int bitwise,pass; double max_abs,max_ref,relative_l2; } readout_diff;
static readout_diff readout_compare(const float *a,const float *b,int n) {
    readout_diff d={.bitwise=!memcmp(a,b,(size_t)n*sizeof(float))};
    double err2=0,ref2=0;
    for(int j=0;j<n;j++) {
        if(!isfinite(a[j])||!isfinite(b[j]))readout_die("nonfinite parity input");
        double e=(double)a[j]-b[j];err2+=e*e;ref2+=(double)b[j]*b[j];
        d.max_abs=fmax(d.max_abs,fabs(e));d.max_ref=fmax(d.max_ref,fabs(b[j]));
    }
    d.relative_l2=sqrt(err2/fmax(ref2,1e-30));
    d.pass=d.relative_l2<=1e-5&&d.max_abs<=1e-4*(1+d.max_ref);return d;
}
static void readout_print_diff(const char *name,readout_diff d) {
    printf("\"%s\":{\"pass\":%s,\"bitwise_equal\":%s,\"max_abs\":%.17g,"
           "\"max_reference_abs\":%.17g,\"relative_l2\":%.17g}",name,d.pass?"true":"false",
           d.bitwise?"true":"false",d.max_abs,d.max_ref,d.relative_l2);
}
static readout_diff readout_reconstruct(llama_model *m,nt_dims dims,const readout_row *r,const float *z) {
    int E=m->embed,F=m->ffn,last=m->n_layers-1;
    float *xn=calloc((size_t)E,sizeof(float)),*g=calloc((size_t)F,sizeof(float)),
          *u=calloc((size_t)F,sizeof(float)),*down=calloc((size_t)E,sizeof(float)),
          *actual=calloc((size_t)E,sizeof(float));
    if(!xn||!g||!u||!down||!actual)readout_die("reconstruction allocation failed");
    readout_capture_ids(m,dims,r->ids,r->n_ids,r->n_ids-1,actual,0);
    rmsnorm(xn,z,m->layers[last].ffn_norm,E,m->rms_eps);
    qmv(g,&m->layers[last].wgate,xn);qmv(u,&m->layers[last].wup,xn);
    for(int j=0;j<F;j++)g[j]=(g[j]/(1.0f+expf(-g[j])))*u[j];
    qmv(down,&m->layers[last].wdown,g);
    for(int j=0;j<E;j++){down[j]=z[j]+down[j];if(m->layers[last].ffn_down_bias)down[j]+=m->layers[last].ffn_down_bias[j];}
    readout_diff d=readout_compare(down,actual,E);
    free(xn);free(g);free(u);free(down);free(actual);return d;
}

int main(int argc,char **argv) {
    if(argc<4||argc>5){fprintf(stderr,"usage: %s BASE.gguf PROMPTS.bin SFT.bin [THREADS]\n",argv[0]);return 2;}
    int threads=argc>4?number(argv[4],1,16):4;
    char s[16];snprintf(s,sizeof(s),"%d",threads);
    if(setenv("NT_NO_I8","1",1)||setenv("NT_QMV_THREADS",s,1))readout_die("cannot set native execution mode");
    int count,full_count;readout_row *rows=readout_data(argv[2],&count);
    mlp_example *full=mlp_data(argv[3],&full_count);
    if(count<2)readout_die("audit requires at least two prompt rows");
    gguf_file *gf=gguf_open(argv[1]);
    if(!gf||strcmp(gf->arch,"qwen2")||gf->n_layers<1||!isfinite(gf->rms_eps)||fabsf(gf->rms_eps-1e-6f)>1e-12f)
        readout_die("audit requires qwen2 with RMS epsilon 1e-6");
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);bpe_tokenizer *tok=bpe_load(argv[1]);
    if(!m||!tok||!m->layers[m->n_layers-1].ffn_norm)readout_die("cannot load audit model");
    int pass=1;
    for(int i=0;i<2;i++) {
        readout_row *r=&rows[i];readout_tokenize(r,tok);
        mlp_example *e=NULL;int match=-1;
        for(int j=0;j<full_count;j++)if(!strcmp(r->system,full[j].system)&&!strcmp(r->user,full[j].prompt)) {
            if(e)readout_die("ambiguous full trainer counterpart");
            e=&full[j];match=j;
        }
        if(!e)readout_die("missing full trainer counterpart");
        tokenize(e,tok);
        if(e->start+1!=r->prompt_tokens||e->cache.n<5||r->n_ids>e->n_ids||
           memcmp(e->ids,r->ids,(size_t)r->n_ids*sizeof(int)))readout_die("trainer and prompt-only token prefixes differ");
        float *z=calloc((size_t)m->embed,sizeof(float)),*future=calloc((size_t)m->embed,sizeof(float));
        if(!z||!future)readout_die("audit feature allocation failed");
        readout_capture_ids(m,dims,r->ids,r->n_ids,r->n_ids-1,z,1);
        int last=m->n_layers-1;wt original=m->layers[last].wdown;float *bias=m->layers[last].ffn_down_bias;
        float *zero=calloc((size_t)m->embed*m->ffn,sizeof(float));if(!zero)readout_die("audit zero allocation failed");
        m->layers[last].wdown=(wt){.f32=zero,.dtype=0,.rows=m->embed,.cols=m->ffn};m->layers[last].ffn_down_bias=NULL;
        e->cache.z=tensor(e->cache.n,m->embed);capture_sequence(m,dims,e,e->cache.z);
        m->layers[last].wdown=original;m->layers[last].ffn_down_bias=bias;free(zero);
        readout_diff trainer=readout_compare(z,e->cache.z->data+(size_t)3*m->embed,m->embed);
        /* A fixed alternate future begins with the opposite class token. Its
         * extra length crosses chunk boundaries; none may affect the feature. */
        int extra=NT_PREFILL_CHUNK+7,n=r->n_ids+extra;
        int *perturbed=malloc((size_t)n*sizeof(int));if(!perturbed)readout_die("future allocation failed");
        memcpy(perturbed,r->ids,(size_t)r->n_ids*sizeof(int));
        int target=e->ids[r->n_ids];
        if(target!=66582&&target!=788)readout_die("audit row lacks expected class target");
        perturbed[r->n_ids]=target==66582?788:66582;
        for(int j=1;j<extra;j++)perturbed[r->n_ids+j]=readout_prefix[j%3];
        readout_capture_ids(m,dims,perturbed,n,r->n_ids-1,future,1);
        readout_diff suffix=readout_compare(z,future,m->embed),reconstruction=readout_reconstruct(m,dims,r,z);
        pass&=trainer.pass&&suffix.pass&&reconstruction.pass;
        printf("{\"row\":%d,\"trainer_row\":%d,\"prompt_tokens\":%d,\"input_tokens\":%d,"
               "\"capture_position\":%d,\"width\":%d,\"nt_no_i8\":true,\"prefix_exact\":true,"
               "\"relative_l2_limit\":1e-5,\"max_abs_rule\":\"1e-4*(1+max_reference_abs)\",",
               i,match,r->prompt_tokens,r->n_ids,r->n_ids-1,m->embed);
        readout_print_diff("full_trainer_cache",trainer);putchar(',');readout_print_diff("changed_future",suffix);
        putchar(',');readout_print_diff("original_residual_reconstruction",reconstruction);puts("}");fflush(stdout);
        free(z);free(future);free(perturbed);
    }
    for(int i=0;i<full_count;i++){free(full[i].system);free(full[i].prompt);free(full[i].answer);free(full[i].ids);batch_free(&full[i].cache);}
    free(full);readout_free(rows,count);bpe_free(tok);nt_arch_llama.free(m);gguf_close(gf);return pass?0:1;
}
