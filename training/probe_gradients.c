/* Local derivative control on real Qwen cached activations. No optimizer step.
 * The oracle is an independent double-precision implementation of the smooth
 * trainable suffix, using the trainer's stored float parameters and cache.
 * It does not differentiate the piecewise-rounded float32 program, and it
 * does not validate gradients through frozen attention or preceding layers.
 * Usage: BASE SFT PAIRS (initial|LORA_PREFIX) CONCERN_ROW CLEAN_ROW
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main

enum { GP_TARGETS=4, GP_PARAMS=6, GP_EPS=4 };
static const double gp_steps[GP_EPS]={.01,.003,.001,.0003};
static const double gp_abs=2e-7, gp_rel=.01, gp_signal=2e-5;
static nt_tensor *gp_parameter(mlp_bank *b,int j) {
    return j%2?b->adapters[j/2].B:b->adapters[j/2].A;
}
static double gp_dot(const float *w,const double *x,int n) {
    double a=0,b=0,c=0,d=0;int i=0;
    for(;i+3<n;i+=4){a+=(double)w[i]*x[i];b+=(double)w[i+1]*x[i+1];c+=(double)w[i+2]*x[i+2];d+=(double)w[i+3]*x[i+3];}
    for(;i<n;i++)a+=(double)w[i]*x[i];
    return (a+b)+(c+d);
}
static void gp_delta(const nt_lora_pair *a,const double *A,const double *B,
                     const double *x,double *out,double *low) {
    for(int r=0;r<a->rank;r++) {
        double v=0;for(int i=0;i<a->in_dim;i++)v+=A[(size_t)r*a->in_dim+i]*x[i];low[r]=v;
    }
    for(int j=0;j<a->out_dim;j++) {
        double v=0;for(int r=0;r<a->rank;r++)v+=B[(size_t)j*a->rank+r]*low[r];out[j]=v*(double)a->scaling;
    }
}
static double gp_oracle(mlp_bank *b,const mlp_batch *s,double **parameters,
                        const double *weights,double *ces,double *logits) {
    int E=b->E,F=b->F,V=b->V,R=b->adapters[0].rank;
    double *x=calloc((size_t)E,sizeof(double)),*gate=calloc((size_t)F,sizeof(double)),
           *up=calloc((size_t)F,sizeof(double)),*h=calloc((size_t)F,sizeof(double)),
           *down=calloc((size_t)E,sizeof(double)),*y=calloc((size_t)E,sizeof(double)),
           *low=calloc((size_t)R,sizeof(double)),*out=calloc((size_t)V,sizeof(double));
    if(!x||!gate||!up||!h||!down||!y||!low||!out)mlp_die("gradient oracle allocation failed");
    double total=0;
    for(int t=0;t<s->n;t++) {
        for(int i=0;i<E;i++)x[i]=s->xn->data[(size_t)t*E+i];
        gp_delta(&b->adapters[0],parameters[0],parameters[1],x,gate,low);
        gp_delta(&b->adapters[1],parameters[2],parameters[3],x,up,low);
        for(int j=0;j<F;j++) {
            double g=(double)s->gate->data[(size_t)t*F+j]+gate[j];
            double u=(double)s->up->data[(size_t)t*F+j]+up[j];
            double sig=g>=0?1/(1+exp(-g)):exp(g)/(1+exp(g));h[j]=g*sig*u;
        }
        gp_delta(&b->adapters[2],parameters[4],parameters[5],h,down,low);
        double sumsq=0;
        for(int j=0;j<E;j++) {
            y[j]=(double)s->z->data[(size_t)t*E+j]+gp_dot(b->wd->data+(size_t)j*F,h,F)+down[j];
            if(s->bias)y[j]+=(double)s->bias->data[(size_t)t*E+j];
            sumsq+=y[j]*y[j];
        }
        double scale=1/sqrt(sumsq/E+(double)1e-6f);
        for(int j=0;j<E;j++)y[j]*=scale*(double)b->norm->data[j];
        double maximum=-INFINITY;
        for(int v=0;v<V;v++){out[v]=gp_dot(b->head->data+(size_t)v*E,y,E);maximum=fmax(maximum,out[v]);}
        double denominator=0;for(int v=0;v<V;v++)denominator+=exp(out[v]-maximum);
        int target=(int)s->targets->data[t];double ce=maximum+log(denominator)-out[target];
        if(!isfinite(ce))mlp_die("nonfinite gradient oracle CE");
        if(ces)ces[t]=ce;
        if(logits)memcpy(logits+(size_t)t*V,out,(size_t)V*sizeof(double));
        total+=weights[t]*ce;
    }
    free(x);free(gate);free(up);free(h);free(down);free(y);free(low);free(out);return total;
}
static void gp_gradient(mlp_bank *b,mlp_batch *s,float **gradient,double *loss) {
    nt_tape_start();int ce=joint_loss(b,s,loss);nt_tape_backward(ce);
    nt_tape *tape=nt_tape_get();unsigned seen=0;
    for(int i=0;i<tape->count;i++) {
        nt_tape_entry *e=&tape->entries[i];if(!e->is_param||e->frozen)continue;
        int j=e->slot;
        if(j<0||j>=GP_PARAMS||(seen&(1u<<j))||e->output!=gp_parameter(b,j)||!e->grad||e->grad->len!=e->output->len)
            mlp_die("gradient parameter identity differs");
        seen|=1u<<j;
        for(int k=0;k<e->grad->len;k++) {
            if(!isfinite(e->grad->data[k]))mlp_die("nonfinite analytic gradient");
            gradient[j][k]=e->grad->data[k];
        }
    }
    if(seen!=63)mlp_die("missing gradient tensor");
    nt_tape_clear();
}
static void gp_capture(mlp_bank *b,llama_model *m,nt_dims dims,mlp_example *e) {
    int last=m->n_layers-1;wt original=m->layers[last].wdown;float *bias=m->layers[last].ffn_down_bias;
    float *zero=calloc((size_t)b->E*b->F,sizeof(float));if(!zero)mlp_die("gradient capture allocation failed");
    m->layers[last].wdown=(wt){.f32=zero,.dtype=0,.rows=b->E,.cols=b->F};m->layers[last].ffn_down_bias=NULL;
    e->cache.z=tensor(e->cache.n,b->E);capture_sequence(m,dims,e,e->cache.z);
    m->layers[last].wdown=original;m->layers[last].ffn_down_bias=bias;free(zero);prepare_cache(b,&e->cache);
}
static uint64_t gp_hash(uint64_t h,const void *ptr,size_t n) {
    const unsigned char *p=ptr;for(size_t i=0;i<n;i++){h^=p[i];h*=UINT64_C(1099511628211);}return h;
}
/* Local byte-change guard only; the execution receipt supplies SHA256 inputs. */
static uint64_t gp_identity(mlp_bank *b,mlp_batch *s) {
    nt_tensor *fixed[]={b->wg,b->wu,b->wd,b->head,b->norm,b->ffn_norm,b->bias,s->z,s->xn,s->gate,s->up,s->targets,s->bias,s->weights};
    uint64_t h=UINT64_C(14695981039346656037);
    for(unsigned j=0;j<sizeof(fixed)/sizeof(*fixed);j++)if(fixed[j])h=gp_hash(h,fixed[j]->data,(size_t)fixed[j]->len*sizeof(float));
    for(int j=0;j<GP_PARAMS;j++){nt_tensor *p=gp_parameter(b,j);h=gp_hash(h,p->data,(size_t)p->len*sizeof(float));}return h;
}
int main(int argc,char **argv) {
    if(argc!=7){fprintf(stderr,"usage: %s BASE SFT PAIRS (initial|LORA_PREFIX) CONCERN_ROW CLEAN_ROW\n",argv[0]);return 2;}
    if(setenv("NT_NO_I8","1",1))mlp_die("cannot set gradient activation mode");
    int count;mlp_example *rows=mlp_data(argv[2],&count);gguf_file *gf=gguf_open(argv[1]);
    if(!gf||strcmp(gf->arch,"qwen2")||gf->n_layers<1||!isfinite(gf->rms_eps)||fabsf(gf->rms_eps-1e-6f)>1e-12f)
        mlp_die("gradient probe requires qwen2 with epsilon 1e-6");
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);bpe_tokenizer *tok=bpe_load(argv[1]);
    if(!m||!tok||!m->layers[m->n_layers-1].ffn_norm)mlp_die("cannot load gradient model");
    nt_seed(MLP_SEED);srand(MLP_SEED);mlp_bank b={0};bank_init(&b,m);
    int initial=!strcmp(argv[4],"initial");const char *suffix[]={"gate","up","down"};
    if(!initial)for(int j=0;j<3;j++) {
        char path[4096],name[128];if(snprintf(path,sizeof(path),"%s.%s.lora",argv[4],suffix[j])>=(int)sizeof(path))mlp_die("adapter path too long");
        snprintf(name,sizeof(name),"blk.%d.ffn_%s.weight",b.layer,suffix[j]);const char *names[]={name};
        if(nt_lora_load(&b.adapters[j],1,1,names,path))mlp_die("cannot load gradient adapter");
    }
    int all=0;for(int i=0;i<count;i++) {
        tokenize(&rows[i],tok);
        if(rows[i].n_ids>gf->ctx_len)mlp_die("gradient example exceeds model context");
        all+=rows[i].cache.n;
    }
    b.average_tokens=(double)all/count;load_pairs_tokenized(&b,rows,count,argv[3],tok);int nd,nr;
    token_row *whole=joint_order(rows,count,&nd,&nr);free(whole);
    int a=number(argv[5],0,count-1),c=number(argv[6],0,count-1);
    if(a==c||!rows[a].decision_pair||rows[a].decision_pair!=rows[c].decision_pair||rows[c].decision_position<1)
        mlp_die("gradient rows must be a distinct mapped pair with a prefix");
    gp_capture(&b,m,dims,&rows[a]);gp_capture(&b,m,dims,&rows[c]);
    token_row order[GP_TARGETS]={{a,rows[a].decision_position},{c,rows[c].decision_position},{a,rows[a].cache.n-1},{c,0}};
    mlp_batch s=gather(&b,rows,order,GP_TARGETS);s.weights=tensor(GP_TARGETS,1);
    double weights[GP_TARGETS]={1.0/nd,1.0/nd,1.0/nr,1.0/nr};
    for(int t=0;t<GP_TARGETS;t++)s.weights->data[t]=joint_coefficient(&rows[order[t].example],order[t].token,nd,nr);
    float *grad[GP_PARAMS];double *oracle[GP_PARAMS],*saved[GP_PARAMS];
    for(int j=0;j<GP_PARAMS;j++) {
        nt_tensor *p=gp_parameter(&b,j);grad[j]=calloc((size_t)p->len,sizeof(float));oracle[j]=calloc((size_t)p->len,sizeof(double));saved[j]=calloc((size_t)p->len,sizeof(double));
        if(!grad[j]||!oracle[j]||!saved[j])mlp_die("gradient parameter allocation failed");
        for(int k=0;k<p->len;k++)oracle[j][k]=saved[j][k]=(double)p->data[k];
    }
    uint64_t before=gp_identity(&b,&s);double analytic_loss;gp_gradient(&b,&s,grad,&analytic_loss);
    double ces[GP_TARGETS],*oracle_logits=calloc((size_t)GP_TARGETS*b.V,sizeof(double));if(!oracle_logits)mlp_die("logit allocation failed");
    double reference=gp_oracle(&b,&s,oracle,weights,ces,oracle_logits);
    printf("{\"kind\":\"configuration\",\"initial_zero_B\":%s,\"E\":%d,\"F\":%d,\"V\":%d,\"rank\":%d,\"decision_count\":%d,\"residual_count\":%d,\"target_count\":4,\"analytic_loss\":%.17g,\"oracle_loss\":%.17g,\"absolute_gradient_tolerance\":%.17g,\"relative_gradient_tolerance\":%.17g,\"active_signal_floor\":%.17g,\"epsilon_grid\":[0.01,0.003,0.001,0.0003]}\n",initial?"true":"false",b.E,b.F,b.V,b.adapters[0].rank,nd,nr,analytic_loss,reference,gp_abs,gp_rel,gp_signal);
    double mass=0;for(int t=0;t<GP_TARGETS;t++)mass+=weights[t];
    double loss_limit=1e-4*mass+1e-7;
    int pass=isfinite(analytic_loss)&&fabs(analytic_loss-reference)<=loss_limit,li;
    printf("{\"kind\":\"objective_scalar\",\"absolute_error\":%.17g,\"limit\":%.17g,\"pass\":%s}\n",fabs(analytic_loss-reference),loss_limit,pass?"true":"false");
    nt_tape_start();mlp_forward(&b,&s,0,NULL,&li,NULL);
    float *native=nt_tape_get()->entries[li].output->data;
    for(int t=0;t<GP_TARGETS;t++) {
        double maxerr=0,e2=0,r2=0,maximum=-INFINITY;
        for(int v=0;v<b.V;v++){double f=native[(size_t)t*b.V+v],r=oracle_logits[(size_t)t*b.V+v],e=f-r;maxerr=fmax(maxerr,fabs(e));e2+=e*e;r2+=r*r;maximum=fmax(maximum,f);}
        double den=0;for(int v=0;v<b.V;v++)den+=exp((double)native[(size_t)t*b.V+v]-maximum);
        double ce=maximum+log(den)-(double)native[(size_t)t*b.V+(int)s.targets->data[t]],relative=sqrt(e2/fmax(r2,1e-30));
        int ok=isfinite(relative)&&relative<=1e-5&&maxerr<=1e-3&&fabs(ce-ces[t])<=1e-4;pass&=ok;
        printf("{\"kind\":\"baseline\",\"sample\":%d,\"dataset_row\":%d,\"completion_position\":%d,\"target_id\":%d,\"weight\":%.17g,\"native_logits_ce\":%.17g,\"oracle_ce\":%.17g,\"max_logit_error\":%.17g,\"relative_logit_l2\":%.17g,\"pass\":%s}\n",t,order[t].example,order[t].token,(int)s.targets->data[t],weights[t],ce,ces[t],maxerr,relative,ok?"true":"false");
    }
    nt_tape_clear();free(oracle_logits);
    for(int which=0;which<2;which++) {
        int row=which?c:a;printf("{\"kind\":\"input_ids\",\"dataset_row\":%d,\"assistant_start\":%d,\"ids\":[",row,rows[row].start+1);
        for(int t=0;t<rows[row].n_ids;t++)printf("%s%d",t?",":"",rows[row].ids[t]);
        puts("]}");
    }
    int active_tensors=0,expected_zero_tensors=0,inconclusive=0;
    for(int j=0;j<GP_PARAMS;j++) {
        nt_tensor *p=gp_parameter(&b,j);int largest=0;double norm2=0;
        for(int k=0;k<p->len;k++){if(fabsf(grad[j][k])>fabsf(grad[j][largest]))largest=k;norm2+=(double)grad[j][k]*grad[j][k];}
        int expected_zero=initial&&j%2==0,tensor_active=0;
        if(expected_zero){expected_zero_tensors++;if(norm2!=0)pass=0;}
        double *direction=calloc((size_t)p->len,sizeof(double));if(!direction)mlp_die("direction allocation failed");
        for(int kind=0;kind<2;kind++) {
            uint32_t rng=UINT32_C(20261002)+(uint32_t)j;double dot=0,direction_norm2=0;
            for(int k=0;k<p->len;k++) {
                rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
                direction[k]=kind?((rng&1)?1.0:-1.0)/sqrt((double)p->len):(k==largest?1.0:0.0);
                dot+=(double)grad[j][k]*direction[k];direction_norm2+=direction[k]*direction[k];
            }
            if(fabs(direction_norm2-1)>1e-10)mlp_die("probe direction is not unit norm");
            double fd[GP_EPS]={0};int smallest_pass=1;
            for(int h=0;h<GP_EPS;h++) {
                double eps=gp_steps[h];for(int k=0;k<p->len;k++)oracle[j][k]=saved[j][k]+eps*direction[k];
                double hi=gp_oracle(&b,&s,oracle,weights,NULL,NULL);
                for(int k=0;k<p->len;k++)oracle[j][k]=saved[j][k]-eps*direction[k];
                double lo=gp_oracle(&b,&s,oracle,weights,NULL,NULL);memcpy(oracle[j],saved[j],(size_t)p->len*sizeof(double));
                fd[h]=(hi-lo)/(2*eps);double err=fabs(fd[h]-dot),limit=gp_abs+gp_rel*fmax(fabs(fd[h]),fabs(dot));int ok=isfinite(fd[h])&&err<=limit;
                if(h>=GP_EPS-2)smallest_pass&=ok;
                printf("{\"kind\":\"finite_difference\",\"tensor\":\"%s.%c\",\"direction\":\"%s\",\"coordinate\":%d,\"seed\":%u,\"epsilon\":%.17g,\"analytic\":%.17g,\"numerical\":%.17g,\"loss_plus\":%.17g,\"loss_minus\":%.17g,\"absolute_error\":%.17g,\"limit\":%.17g,\"pass\":%s}\n",suffix[j/2],j%2?'B':'A',kind?"rademacher_unit":"maximum_coordinate",kind?-1:largest,UINT32_C(20261002)+(uint32_t)j,eps,dot,fd[h],hi,lo,err,limit,ok?"true":"false");fflush(stdout);
            }
            double stability=fabs(fd[GP_EPS-1]-fd[GP_EPS-2]);int stable=stability<=gp_abs+gp_rel*fmax(fabs(fd[GP_EPS-1]),fabs(fd[GP_EPS-2]));
            int resolved=fabs(dot)>=gp_signal&&fabs(fd[GP_EPS-1])>=gp_signal;
            /* A one-sided missing derivative is a failure, never an excuse to
             * call a direction weak. Signal controls coverage only after the
             * agreement/stability gate has been applied to every direction. */
            int agrees=smallest_pass&&stable;pass&=agrees;
            const char *status=!agrees?"fail":expected_zero?"expected_zero":!resolved?"inconclusive":"pass";
            if(expected_zero)pass&=fd[GP_EPS-1]==0&&fd[GP_EPS-2]==0;
            else if(resolved)tensor_active|=agrees;else if(agrees)inconclusive++;
            printf("{\"kind\":\"direction_summary\",\"tensor\":\"%s.%c\",\"direction\":\"%s\",\"gradient_norm\":%.17g,\"direction_norm\":%.17g,\"two_smallest_stable\":%s,\"status\":\"%s\"}\n",suffix[j/2],j%2?'B':'A',kind?"rademacher_unit":"maximum_coordinate",sqrt(norm2),sqrt(direction_norm2),stable?"true":"false",status);fflush(stdout);
        }
        if(!expected_zero){active_tensors+=tensor_active;pass&=tensor_active;}free(direction);
    }
    int unchanged=before==gp_identity(&b,&s);pass&=unchanged;
    printf("{\"kind\":\"summary\",\"pass\":%s,\"active_tensors\":%d,\"expected_zero_tensors\":%d,\"inconclusive_directions\":%d,\"parameters_and_frozen_bytes_unchanged\":%s,\"optimizer_steps\":0}\n",pass?"true":"false",active_tensors,expected_zero_tensors,inconclusive,unchanged?"true":"false");fflush(stdout);
    nt_tape_start();for(int j=0;j<GP_PARAMS;j++)nt_tape_param(gp_parameter(&b,j));nt_tape_destroy();
    for(int j=0;j<GP_PARAMS;j++){free(grad[j]);free(oracle[j]);free(saved[j]);}
    for(int j=0;j<3;j++)nt_lora_free(&b.adapters[j]);
    nt_tensor_free(b.wg);nt_tensor_free(b.wu);nt_tensor_free(b.wd);nt_tensor_free(b.head);nt_tensor_free(b.norm);nt_tensor_free(b.ffn_norm);nt_tensor_free(b.bias);batch_free(&s);
    for(int i=0;i<count;i++){free(rows[i].system);free(rows[i].prompt);free(rows[i].answer);free(rows[i].ids);batch_free(&rows[i].cache);}free(rows);
    bpe_free(tok);nt_arch_llama.free(m);gguf_close(gf);return pass?0:1;
}
