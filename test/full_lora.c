/* Engineering regression tests for the actual full-layer training path. */
#define FULL_LORA_NO_MAIN
#include "../training/train_full.c"
#include <assert.h>

#define REQUIRE(x) do { if(!(x)){fprintf(stderr,"full LoRA test line %d: %s\n",__LINE__,#x);abort();} } while(0)
static int test_gpu=0;
static const char *test_stage="startup";
static void near_at(float a,float b,float eps,int line) {
    if(!isfinite(a)||!isfinite(b)||fabsf(a-b)>eps) {
        fprintf(stderr,"full LoRA numerical failure: stage=%s line=%d actual=%.9g expected=%.9g abs_delta=%.9g tolerance=%.9g gpu=%d\n",test_stage,line,a,b,fabsf(a-b),eps,nt_get_gpu_mode());
        abort();
    }
}
#define near(a,b,eps) near_at((a),(b),(eps),__LINE__)
static void stage(const char *name) { test_stage=name;fprintf(stderr,"full LoRA test: %s\n",name);fflush(stderr); }
static void cpu_written(nt_tensor *t) {
#ifdef USE_CUDA
    t->gpu_valid=0;t->cpu_dirty=0;
#else
    (void)t;
#endif
}
static void fill(nt_tensor *t,float scale,int seed) { for(int i=0;i<t->len;i++)t->data[i]=scale*sinf((i+1)*.73f+seed*1.31f);cpu_written(t); }
static void reset_tape(void) { nt_tape_destroy(); }

static void rotary(void) {
    stage("rotary Qwen layout");
    enum {T=3,H=2,D=8,N=T*H*D};float original[N],rotated[N];
    nt_tensor *x=vec(N);fill(x,.7f,3);memcpy(original,x->data,sizeof original);
    for(int t=0;t<T;t++)permute(x->data+t*H*D,H*D,1,D,0);
    nt_tape_start();int y=nt_rope_freq(frozen(x),T,D,1000000.f);memcpy(rotated,value(y)->data,sizeof rotated);
    for(int t=0;t<T;t++)permute(rotated+t*H*D,H*D,1,D,1);
    for(int t=0;t<T;t++)for(int h=0;h<H;h++)for(int j=0;j<D/2;j++) {
        int a=(t*H+h)*D+j,b=a+D/2;float angle=t*powf(1000000.f,-2.f*j/D);
        near(rotated[a],original[a]*cosf(angle)-original[b]*sinf(angle),2e-7f);
        near(rotated[b],original[a]*sinf(angle)+original[b]*cosf(angle),2e-7f);
    }
    for(int t=0;t<T;t++)permute(x->data+t*H*D,H*D,1,D,1);
    REQUIRE(!memcmp(x->data,original,sizeof original));reset_tape();nt_tensor_free(x);
}

static void grouped_attention(void) {
    stage("GQA CPU reference versus repeated-KV forward/backward");
    enum {T=4,H=4,K=2,D=4,Q=H*D,KD=K*D};
    nt_tensor *p[3]={vec(T*Q),vec(T*KD),vec(T*KD)},*repeat=nt_tensor_new2d(Q,KD),*targets=vec(T);
    for(int j=0;j<3;j++)fill(p[j],.7f,j);
    for(int h=0;h<H;h++)for(int d=0;d<D;d++)repeat->data[(h*D+d)*KD+(h/(H/K))*D+d]=1;
    for(int t=0;t<T;t++)targets->data[t]=t+1;
    float outputs[T*Q],grads[3][T*Q];
    for(int variant=0;variant<2;variant++) {
        nt_set_gpu_mode(variant?test_gpu:0);
        nt_tape_start();int ix[3];for(int j=0;j<3;j++)ix[j]=nt_tape_param(p[j]);int y;
        if(!variant)y=nt_gqa_causal_attention(ix[0],ix[1],ix[2],T,D,H,K);
        else {int k=nt_seq_linear(frozen(repeat),ix[1],T),v=nt_seq_linear(frozen(repeat),ix[2],T);y=nt_mh_causal_attention(ix[0],k,v,T,D);}
        if(!variant)memcpy(outputs,value(y)->data,sizeof outputs);else for(int i=0;i<T*Q;i++)near(value(y)->data[i],outputs[i],2e-6f);
        int loss=nt_seq_cross_entropy(y,frozen(targets),T,Q);nt_tape_backward(loss);
        for(int j=0;j<3;j++){nt_tensor *g=nt_tape_get()->entries[ix[j]].grad;REQUIRE(g);nt_tensor_sync_cpu(g);
            if(!variant)memcpy(grads[j],g->data,g->len*sizeof(float));else for(int i=0;i<g->len;i++)near(g->data[i],grads[j][i],2e-6f);}
        reset_tape();
    }
    for(int j=0;j<3;j++)nt_tensor_free(p[j]);
    nt_tensor_free(repeat);nt_tensor_free(targets);
}

static full_model tiny(int layers) {
    full_model m={.L=2,.E=8,.F=12,.V=11,.H=2,.K=1,.HD=4,.Q=8,.KD=4,.rank=2};
    m.L=layers;
    m.gf=mem(sizeof(*m.gf));m.gf->rope_freq_base=1000000.f;
    m.emb=nt_tensor_new2d(m.V,m.E);m.head=nt_tensor_new2d(m.V,m.E);m.norm=vec(m.E);
    fill(m.emb,.6f,1);fill(m.head,.4f,7);for(int i=0;i<m.E;i++)m.norm->data[i]=1;
    m.w=mem(m.L*TARGETS*sizeof(*m.w));m.lora=mem(m.L*TARGETS*sizeof(*m.lora));m.an=mem(m.L*sizeof(*m.an));m.fn=mem(m.L*sizeof(*m.fn));m.bias=mem(m.L*3*sizeof(*m.bias));
    for(int l=0;l<m.L;l++) {
        m.an[l]=vec(m.E);m.fn[l]=vec(m.E);for(int i=0;i<m.E;i++)m.an[l]->data[i]=m.fn[l]->data[i]=1;
        for(int j=0;j<TARGETS;j++){int z=l*TARGETS+j,in=j==6?m.F:m.E,out=j==1||j==2?m.KD:j==4||j==5?m.F:m.E;
            m.w[z]=nt_tensor_new2d(out,in);fill(m.w[z],.15f,z+3);REQUIRE(!nt_lora_init(&m.lora[z],in,out,m.rank,4));
            if(j<3){m.bias[l*3+j]=vec(out);fill(m.bias[l*3+j],.03f,z);}}
    }
    m.repeat=nt_tensor_new2d(m.Q,m.KD);for(int h=0;h<m.H;h++)for(int d=0;d<m.HD;d++)m.repeat->data[(h*m.HD+d)*m.KD+d]=1;
    return m;
}
static void slots(full_model *m) {
    nt_tape *t=nt_tape_get();int n=0;for(int i=0;i<t->count;i++)if(t->entries[i].slot>=0){int s=t->entries[i].slot;REQUIRE(s==n++);REQUIRE(t->entries[i].output==(s%2?m->lora[s/2].B:m->lora[s/2].A));}
    REQUIRE(n==m->L*TARGETS*2&&t->n_params==n);
}
static float step_model(full_model *m,full_example *e) {
    stage("optimizer step and frozen gradient clipping");
    nt_tape_start();int li=loss_for(m,e);float loss=value(li)->data[0];slots(m);nt_tape_backward(li);gradients(m);
    double norm2=0;nt_tape *t=nt_tape_get();int injected=0;
    for(int i=0;i<t->count;i++){nt_tape_entry *entry=&t->entries[i];if(entry->slot>=0&&entry->grad){nt_tensor_sync_cpu(entry->grad);for(int k=0;k<entry->grad->len;k++)norm2+=(double)entry->grad->data[k]*entry->grad->data[k];}
        if(!injected&&entry->is_param&&entry->frozen){if(entry->grad)nt_tensor_free(entry->grad);entry->grad=vec(entry->output->len);nt_tensor_fill(entry->grad,10000);injected=1;}}
    REQUIRE(injected);float norm=clip_adapters(1e10f);near(norm,(float)sqrt(norm2),1e-5f*(1+(float)sqrt(norm2)));
    for(int i=0;i<t->count;i++)if(t->entries[i].is_param&&t->entries[i].frozen)REQUIRE(!t->entries[i].grad);
    REQUIRE(isfinite(clip_adapters(1)));REQUIRE(nt_tape_chuck_step_action(.003f,loss,NULL,NULL)==NT_CHUCK_OK);return loss;
}
static void same_file(const char *a,const char *b) {
    FILE *x=fopen(a,"rb"),*y=fopen(b,"rb");REQUIRE(x&&y);for(;;){int u=fgetc(x),v=fgetc(y);REQUIRE(u==v);if(u==EOF)break;}fclose(x);fclose(y);
}
static void training_resume(void) {
    stage("assistant mask and next-token shift");
    nt_seed(20261020);full_model m=tiny(2);int ids[]={1,2,3,4,5,6};full_example e={ids,6,3};
    nt_tape_start();int logits=forward(&m,ids,5);float expected=0;nt_tensor *v=value(logits);
    for(int t=3;t<5;t++){double sum=0;for(int j=0;j<m.V;j++)sum+=exp(v->data[t*m.V+j]);expected+=(float)(log(sum)-v->data[t*m.V+ids[t+1]])/2;}
    nt_tape_start();int li=loss_for(&m,&e);near(value(li)->data[0],expected,1e-6f);
    nt_tape_backward(li);slots(&m);
    /* Centered differences cover every B matrix, through both transformer blocks. */
    stage("full-model B gradient finite differences");
    float analytic[14];for(int z=0;z<14;z++){int best=-1;for(int i=0;i<nt_tape_get()->count;i++)if(nt_tape_get()->entries[i].output==m.lora[z].B)best=i;REQUIRE(best>=0);nt_tensor *grad=nt_tape_get()->entries[best].grad;nt_tensor_sync_cpu(grad);analytic[z]=grad->data[0];}
    for(int z=0;z<14;z++){float *p=&m.lora[z].B->data[0];*p=.002f;cpu_written(m.lora[z].B);nt_tape_start();float plus=value(loss_for(&m,&e))->data[0];*p=-.002f;cpu_written(m.lora[z].B);nt_tape_start();float minus=value(loss_for(&m,&e))->data[0];*p=0;cpu_written(m.lora[z].B);fprintf(stderr,"finite difference layer=%d target=%s numerical=%.9g analytic=%.9g\n",z/7,names[z%7],(plus-minus)/.004f,analytic[z]);near((plus-minus)/.004f,analytic[z],3e-4f);}
    step_model(&m,&e);
    char dir[]="/tmp/jovovich-full-lora-XXXXXX";REQUIRE(mkdtemp(dir));char save[1024],a[1024],b[1024];snprintf(save,sizeof save,"%s/save",dir);snprintf(a,sizeof a,"%s/a",dir);snprintf(b,sizeof b,"%s/b",dir);REQUIRE(!mkdir(save,0700)&&!mkdir(a,0700)&&!mkdir(b,0700));
    adapter_io(&m,save,1);optimizer_io(&m,save,1,1);float first=step_model(&m,&e);adapter_io(&m,a,1);optimizer_io(&m,a,1,2);
    /* Reload both adapters and the complete optimizer on an already advanced tape. */
    adapter_io(&m,save,0);REQUIRE(optimizer_io(&m,save,0,0)==1);float second=step_model(&m,&e);REQUIRE(first==second);adapter_io(&m,b,1);optimizer_io(&m,b,1,2);
    for(int j=0;j<=TARGETS;j++){char x[1200],y[1200];if(j<TARGETS){snprintf(x,sizeof x,"%s/%s.lora",a,names[j]);snprintf(y,sizeof y,"%s/%s.lora",b,names[j]);}else{snprintf(x,sizeof x,"%s/optimizer.bin",a);snprintf(y,sizeof y,"%s/optimizer.bin",b);}same_file(x,y);unlink(x);unlink(y);}
    for(int j=0;j<=TARGETS;j++){char x[1200];if(j<TARGETS)snprintf(x,sizeof x,"%s/%s.lora",save,names[j]);else snprintf(x,sizeof x,"%s/optimizer.bin",save);unlink(x);}rmdir(a);rmdir(b);rmdir(save);rmdir(dir);reset_tape();
}
static void export_roundtrip(void) {
    stage("168-matrix export setup");
    full_model fixture=tiny(24);enum {N=3+24*12};nt_tensor *tensors[N];char labels[N][100];int n=0;
    tensors[n]=fixture.emb;strcpy(labels[n++],"token_embd.weight");tensors[n]=fixture.head;strcpy(labels[n++],"output.weight");tensors[n]=fixture.norm;strcpy(labels[n++],"output_norm.weight");
    for(int l=0;l<24;l++) {
        for(int j=0;j<TARGETS;j++){tensors[n]=fixture.w[l*TARGETS+j];snprintf(labels[n++],100,"blk.%d.%s.weight",l,names[j]);}
        for(int j=0;j<3;j++){tensors[n]=fixture.bias[l*3+j];snprintf(labels[n++],100,"blk.%d.%s.bias",l,names[j]);}
        tensors[n]=fixture.an[l];snprintf(labels[n++],100,"blk.%d.attn_norm.weight",l);tensors[n]=fixture.fn[l];snprintf(labels[n++],100,"blk.%d.ffn_norm.weight",l);
    }
    REQUIRE(n==N);char dir[]="/tmp/jovovich-full-export-XXXXXX";REQUIRE(mkdtemp(dir));char source[1024],target[1024];snprintf(source,sizeof source,"%s/source.gguf",dir);snprintf(target,sizeof target,"%s/merged.gguf",dir);
    gguf_writer *w=gguf_write_open(source);REQUIRE(w);
    REQUIRE(!gguf_write_kv_str(w,"general.architecture","qwen2"));REQUIRE(!gguf_write_kv_str(w,"test.provenance","preserve this metadata"));
    REQUIRE(!gguf_write_kv_u32(w,"qwen2.block_count",24));REQUIRE(!gguf_write_kv_u32(w,"qwen2.embedding_length",8));REQUIRE(!gguf_write_kv_u32(w,"qwen2.feed_forward_length",12));REQUIRE(!gguf_write_kv_u32(w,"qwen2.attention.head_count",2));REQUIRE(!gguf_write_kv_u32(w,"qwen2.attention.head_count_kv",1));REQUIRE(!gguf_write_kv_f32(w,"qwen2.attention.layer_norm_rms_epsilon",1e-6f));REQUIRE(!gguf_write_kv_f32(w,"qwen2.rope.freq_base",1000000.f));
    for(int i=0;i<n;i++){nt_tensor *t=tensors[i];uint64_t shape[2]={(uint64_t)t->len,1};if(t->ndim==2){shape[0]=t->shape[1];shape[1]=t->shape[0];}REQUIRE(!gguf_write_tensor_decl(w,labels[i],t->ndim,shape,GGUF_TYPE_F32));}
    for(int i=0;i<n;i++)REQUIRE(!gguf_write_tensor_f32(w,labels[i],tensors[i]->data,tensors[i]->len));
    REQUIRE(!gguf_write_close(w));
    full_model m=load_model(source,2);for(int z=0;z<168;z++){fill(m.lora[z].A,.02f,z);fill(m.lora[z].B,.03f,z+6);}
    int ids[]={1,2,3};nt_tape_start();float logits[33];memcpy(logits,value(forward(&m,ids,3))->data,sizeof logits);reset_tape();
    export_model(&m,source,target);full_model merged=load_model(target,2);gguf_file *a=m.gf,*b=merged.gf;REQUIRE(a->n_tensors==b->n_tensors&&a->kv_end==b->kv_end);
    FILE *fa=fopen(source,"rb"),*fb=fopen(target,"rb");REQUIRE(fa&&fb);for(uint64_t i=0;i<a->kv_end;i++)REQUIRE(fgetc(fa)==fgetc(fb));fclose(fa);fclose(fb);
    stage("168-matrix export weights and untouched metadata");
    int changed=0;for(int i=0;i<n;i++){int adapted=-1;for(int z=0;z<168;z++)if(m.ti[z]==i)adapted=z;gguf_tensor_info *ai=&a->tensors[i],*bi=&b->tensors[i];
        REQUIRE(!strcmp(ai->name,bi->name));REQUIRE(!memcmp(ai->shape,bi->shape,sizeof ai->shape));
        if(adapted<0){REQUIRE(ai->dtype==bi->dtype);REQUIRE(!memcmp(a->data+ai->offset,b->data+bi->offset,gguf_type_size(ai->dtype,ai->n_elements)));}
        else {changed++;REQUIRE(bi->dtype==GGUF_TYPE_F32);nt_lora_pair *p=&m.lora[adapted];nt_tensor *base=m.w[adapted];float *expected=mem(base->len*sizeof(float));
            for(int row=0;row<base->shape[0];row++)for(int col=0;col<base->shape[1];col++){double sum=0;for(int k=0;k<m.rank;k++)sum+=(double)p->B->data[row*m.rank+k]*p->A->data[k*base->shape[1]+col];expected[row*base->shape[1]+col]=base->data[row*base->shape[1]+col]+2*(float)sum;}
            if(adapted%7<2)permute(expected,base->shape[0],base->shape[1],m.HD,1);
            float *actual=gguf_dequant(b,i);REQUIRE(actual);for(int j=0;j<base->len;j++)near(expected[j],actual[j],2e-7f);free(expected);free(actual);}
    }
    stage("merged GGUF inference logits");
    REQUIRE(changed==168);nt_tape_start();nt_tensor *v=value(forward(&merged,ids,3));for(int i=0;i<33;i++)near(logits[i],v->data[i],3e-6f);reset_tape();unlink(source);unlink(target);rmdir(dir);
}
int main(int argc,char **argv) {
    REQUIRE(argc==1||(argc==2&&!strcmp(argv[1],"--cuda")));test_gpu=argc==2;
#ifdef USE_CUDA
    if(test_gpu){training_gpu();REQUIRE(nt_get_gpu_mode());}
#else
    REQUIRE(!test_gpu);
#endif
    rotary();grouped_attention();training_resume();export_roundtrip();puts("full LoRA: rotary, GQA backward, mask/shift, gradients, frozen clipping, slots, exact Chuck resume and 168-matrix GGUF export PASS");return 0;
}
