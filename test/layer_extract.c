#define LAYER_MAIN layer_extractor_main
#include "../training/extract_layers.c"
#undef LAYER_MAIN

#define REQUIRE(x) do { if(!(x)){fprintf(stderr,"layer fixture failed line %d: %s\n",__LINE__,#x);abort();} } while(0)

/* A deterministic causal fixture tests the collector independently of a GGUF.
 * Each layer's state accumulates only tokens up through its own position.
 * Real Qwen chunk/step and future invariance are the collector's --verify gate. */
static int fake_mode=0,fresh_caches=0;
static int fixture_forward(void *model,kv_cache *kv,const int *ids,int n,int pos,float *logits,
                           nt_residual_fn callback,void *user) {
    llama_model *m=model;REQUIRE(logits==NULL);
    REQUIRE(nt_check_call(kv,ids,n,pos,m->vocab,m->n_layers,m->kv_dim)==NT_OK);
    if(pos==0) {
        for(int i=0;i<kv->n_layers*kv->max_seq*kv->kv_dim;i++)REQUIRE(kv->k[i]==0&&kv->v[i]==0);
        fresh_caches++;
    }
    if(fake_mode==4)return NT_E_MEMORY;
    float *residual=malloc((size_t)n*m->embed*sizeof(float));REQUIRE(residual);
    int rc=NT_OK;
    for(int layer=0;layer<m->n_layers;layer++) {
        for(int t=0;t<n;t++) {
            int absolute=pos+t;size_t index=((size_t)layer*kv->max_seq+absolute)*kv->kv_dim;
            float previous=absolute?kv->k[index-kv->kv_dim]:0;
            float cumulative=previous+ids[t];kv->k[index]=cumulative;
            for(int j=0;j<m->embed;j++)residual[(size_t)t*m->embed+j]=cumulative+100*layer+j*.25f;
        }
        if(fake_mode==1&&layer==1)continue; /* Missing whole layer must fail. */
        if(fake_mode==3)for(int t=0;t<n;t++)residual[(size_t)t*m->embed]=NAN;
        rc=callback(user,layer,pos,n,m->embed,residual);
        if(rc!=NT_OK)break;
        if(fake_mode==2) {
            rc=callback(user,layer,pos,n,m->embed,residual);
            if(rc!=NT_OK)break;
        }
    }
    free(residual);return rc;
}

static void hooks_and_negative_gates(void) {
    float residual[]={10,11,20,21,30,31},out[12]={0};
    layer_capture c={.layers=3,.width=2,.input_tokens=8,.positions={2,5},.features=out};
    REQUIRE(layer_hook(&c,0,0,2,2,residual)==NT_OK); /* No capture yet. */
    REQUIRE(layer_hook(&c,0,1,3,2,residual)==NT_OK);
    REQUIRE(out[0]==20&&out[1]==21&&c.seen[0]==1);
    REQUIRE(layer_hook(&c,0,1,3,2,residual)==NT_E_STATE); /* Duplicate observation. */
    REQUIRE(layer_hook(&c,-1,1,3,2,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,3,1,3,2,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,1,1,3,3,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,1,-1,3,2,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,1,7,3,2,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,1,1,0,2,residual)==NT_E_ARG);
    REQUIRE(layer_hook(&c,1,1,3,2,NULL)==NT_E_ARG);
    residual[2]=INFINITY;
    REQUIRE(layer_hook(&c,1,1,3,2,residual)==NT_E_STATE&&c.seen[1]==0);
    residual[2]=20;
    REQUIRE(layer_hook(&c,1,4,3,2,residual)==NT_OK);
    REQUIRE(out[8]==20&&out[9]==21&&c.seen[4]==1); /* position-major, layer-major */
    REQUIRE(residual[0]==10&&residual[1]==11&&residual[2]==20); /* observer only */
    float zeros[12]={0},same[12]={0};
    layer_difference difference=layer_compare(zeros,same,3,2);REQUIRE(difference.pass&&difference.vectors==6);
    same[7]=1;REQUIRE(!layer_compare(zeros,same,3,2).pass);
    same[7]=NAN;REQUIRE(!layer_compare(zeros,same,3,2).pass);
}

static void capture_causality_and_failures(void) {
    gguf_file gf={.ctx_len=16};
    size_t model_size=sizeof(llama_model)+3*sizeof(((llama_model*)0)->layers[0]);
    llama_model *m=calloc(1,model_size);REQUIRE(m);
    m->gf=&gf;m->n_layers=3;m->embed=2;m->vocab=20;m->kv_dim=1;
    m->layers[0].wdown.rows=91;m->layers[1].wdown.cols=83;m->layers[2].wdown.dtype=17;
    unsigned char *saved=malloc(model_size);REQUIRE(saved);memcpy(saved,m,model_size);
    nt_dims dims={.n_layers=3,.kv_dim=1,.vocab=20};
    int ids[]={1,2,3,4,5,6},future[]={1,2,3,4,5,6,7,8};
    float chunked[12],stepped[12],extended[12];
    REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,4,chunked,fixture_forward)==NT_OK);
    REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,1,stepped,fixture_forward)==NT_OK);
    REQUIRE(!memcmp(chunked,stepped,sizeof(chunked)));
    for(int p=0;p<2;p++)for(int layer=0;layer<3;layer++)for(int j=0;j<2;j++)
        REQUIRE(chunked[(p*3+layer)*2+j]==(p?21:6)+100*layer+j*.25f);
    REQUIRE(layer_capture_ids(m,dims,future,8,2,5,4,extended,fixture_forward)==NT_OK);
    REQUIRE(!memcmp(chunked,extended,sizeof(chunked)));
    future[6]=19;future[7]=18;
    REQUIRE(layer_capture_ids(m,dims,future,8,2,5,3,extended,fixture_forward)==NT_OK);
    REQUIRE(!memcmp(chunked,extended,sizeof(chunked)));
    REQUIRE(fresh_caches==4);
    REQUIRE(!memcmp(saved,m,model_size)); /* No model field or projection modified. */
    REQUIRE(layer_capture_ids(m,dims,ids,6,2,6,4,extended,fixture_forward)==NT_E_ARG);
    REQUIRE(layer_capture_ids(m,dims,ids,6,2,2,4,extended,fixture_forward)==NT_E_ARG);
    REQUIRE(layer_capture_ids(m,dims,ids,17,2,5,4,extended,fixture_forward)==NT_E_ARG);
    REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,0,extended,fixture_forward)==NT_E_ARG);
    dims.n_layers=2;REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,4,extended,fixture_forward)==NT_E_ARG);dims.n_layers=3;
    ids[0]=20;REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,4,extended,fixture_forward)==NT_E_TOKEN);ids[0]=1;
    for(fake_mode=1;fake_mode<=4;fake_mode++) {
        int expected=fake_mode==4?NT_E_MEMORY:NT_E_STATE;
        REQUIRE(layer_capture_ids(m,dims,ids,6,2,5,4,extended,fixture_forward)==expected);
    }
    fake_mode=0;free(saved);free(m);
}

int main(void) {
    hooks_and_negative_gates();capture_causality_and_failures();
    puts("layer extraction: all layers/two positions, exact layout, fresh caches, chunk/step and future invariance, mutation and failure gates passed");
    return 0;
}
