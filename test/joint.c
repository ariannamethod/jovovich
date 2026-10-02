#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>
#include <sys/wait.h>

/* Independent token derivatives provide the oracle for the global objective.
 * Unequal completion lengths, interior unmapped rows, an uneven last batch,
 * and terminal EOS each exercise a different boundary of accumulation. */
enum { ROWS=6, DECISIONS=4, RESIDUAL=25, TOTAL=29, ALL=39, PARAMS=6, ELEMENTS=42, STEPS=4 };
static const int lengths[ROWS]={3,5,8,7,6,10};
static const int positions[ROWS]={-1,2,2,-1,3,3};
static const float learning_rate=.003f, clip_limit=.0001f;

static void fixture_fill(nt_tensor *t,float scale,int shift) {
    for(int i=0;i<t->len;i++)t->data[i]=scale*(float)(((i*7+shift)%17)-8);
}
static nt_tensor *parameter(mlp_bank *b,int j) {
    return j%2?b->adapters[j/2].B:b->adapters[j/2].A;
}
static void fixture_init(mlp_bank *b,mlp_example *rows) {
    *b=(mlp_bank){.E=3,.F=4,.V=7,.layer=1,.average_tokens=(double)ALL/ROWS};
    b->wg=tensor(b->F,b->E);b->wu=tensor(b->F,b->E);b->wd=tensor(b->E,b->F);
    b->head=tensor(b->V,b->E);b->norm=tensor(1,b->E);b->ffn_norm=tensor(1,b->E);b->bias=tensor(1,b->E);
    fixture_fill(b->wg,.07f,2);fixture_fill(b->wu,.06f,3);fixture_fill(b->wd,.08f,4);fixture_fill(b->head,.11f,5);
    for(int k=0;k<b->E;k++){b->norm->data[k]=.8f+.1f*k;b->ffn_norm->data[k]=1.1f-.05f*k;b->bias->data[k]=.01f*(k-2);}
    for(int j=0;j<3;j++) {
        assert(nt_lora_init(&b->adapters[j],j==2?b->F:b->E,j==2?b->E:b->F,2,4)==0);
        fixture_fill(b->adapters[j].A,.035f,1+j);fixture_fill(b->adapters[j].B,.025f,4+j);
    }
    memset(rows,0,ROWS*sizeof(*rows));
    for(int i=0;i<ROWS;i++) {
        mlp_batch *s=&rows[i].cache;s->n=lengths[i];s->z=tensor(s->n,b->E);s->targets=tensor(s->n,1);
        fixture_fill(s->z,.12f,i+1);
        for(int t=0;t<s->n;t++)s->targets->data[t]=(float)((t+1)%5);
        s->targets->data[s->n-1]=6;
        if(positions[i]>=0)s->targets->data[positions[i]]=(i==1||i==4)?1:2;
        prepare_cache(b,s);
    }
    unsigned char map[]={ 'J','V','P','R',1,0,0,0, ROWS,0,0,0, 2,0,0,0,
                         1,0,0,0, 2,0,0,0, 4,0,0,0, 5,0,0,0 };
    char path[]="/tmp/jovovich-joint-pairs-XXXXXX";int fd=mkstemp(path);assert(fd>=0);
    FILE *f=fdopen(fd,"wb");assert(f);assert(fwrite(map,1,sizeof(map),f)==sizeof(map));assert(fclose(f)==0);
    load_pairs(b,rows,ROWS,path);assert(unlink(path)==0);assert(b->pair_count==2);
    for(int i=0;i<ROWS;i++)assert((rows[i].decision_pair!=0)==(positions[i]>=0));
}
static void reset_optimizer(mlp_bank *b) {
    nt_tape_start();for(int j=0;j<PARAMS;j++)nt_tape_param(parameter(b,j));nt_tape_destroy();
}
static void fixture_free(mlp_bank *b,mlp_example *rows) {
    reset_optimizer(b);for(int j=0;j<3;j++)nt_lora_free(&b->adapters[j]);
    nt_tensor_free(b->wg);nt_tensor_free(b->wu);nt_tensor_free(b->wd);nt_tensor_free(b->head);
    nt_tensor_free(b->norm);nt_tensor_free(b->ffn_norm);nt_tensor_free(b->bias);
    for(int i=0;i<ROWS;i++)batch_free(&rows[i].cache);
}
static void read_gradient(mlp_bank *b,float *out) {
    nt_tape *t=nt_tape_get();assert(t->n_params==PARAMS);unsigned seen=0;
    int offsets[PARAMS],offset=0;
    for(int j=0;j<PARAMS;j++){offsets[j]=offset;offset+=parameter(b,j)->len;}assert(offset==ELEMENTS);
    for(int i=0;i<t->count;i++) {
        nt_tape_entry *e=&t->entries[i];
        if(e->frozen){assert(!e->grad);continue;}
        if(!e->is_param)continue;
        assert(e->slot>=0&&e->slot<PARAMS&&!(seen&(1u<<e->slot)));seen|=1u<<e->slot;
        assert(e->output==parameter(b,e->slot)&&e->grad&&e->grad->len==e->output->len);
        for(int k=0;k<e->grad->len;k++){assert(isfinite(e->grad->data[k]));out[offsets[e->slot]+k]=e->grad->data[k];}
    }
    assert(seen==(1u<<PARAMS)-1);
}
static void read_state(mlp_bank *b,int step,float *out) {
    nt_tape *t=nt_tape_get();int p=0;
    for(int j=0;j<PARAMS;j++) {
        nt_tensor *param=parameter(b,j);nt_adam_state *a=&t->adam[j];assert(a->t==step);
        assert((a->m!=NULL)==(a->v!=NULL));if(step)assert(a->m&&a->v);
        if(a->acc_grad)for(int k=0;k<a->acc_grad->len;k++)assert(a->acc_grad->data[k]==0);
        for(int k=0;k<param->len;k++,p++) {
            out[p]=param->data[k];out[ELEMENTS+p]=a->m?a->m->data[k]:0;out[2*ELEMENTS+p]=a->v?a->v->data[k]:0;
            if(!step)assert(out[ELEMENTS+p]==0&&out[2*ELEMENTS+p]==0);
        }
    }
    assert(p==ELEMENTS);
}
static double token_oracle(mlp_bank *b,mlp_example *rows,float *gradient) {
    double value=0,grad[ELEMENTS]={0};int nd=0,nr=0;
    /* Membership and normalization are defined by this fixture, independently
     * of joint_order(), joint_coefficient(), and weighted CE. */
    for(int i=0;i<ROWS;i++)if(i==1||i==2||i==4||i==5)for(int pos=0;pos<lengths[i];pos++) {
        int decision=pos==positions[i];double coefficient=decision?1.0/DECISIONS:1.0/RESIDUAL;
        nd+=decision;nr+=!decision;token_row one={i,pos};mlp_batch s=gather(b,rows,&one,1);assert(!s.weights);
        nt_tape_start();int ce=mlp_forward(b,&s,1,NULL,NULL,NULL);
        value+=coefficient*nt_tape_get()->entries[ce].output->data[0];nt_tape_backward(ce);
        float g[ELEMENTS];read_gradient(b,g);for(int k=0;k<ELEMENTS;k++)grad[k]+=coefficient*g[k];
        nt_tape_clear();batch_free(&s);
    }
    assert(nd==DECISIONS&&nr==RESIDUAL);for(int k=0;k<ELEMENTS;k++)gradient[k]=(float)grad[k];return value;
}
static float max_difference(const float *a,const float *b,int n) {
    float maximum=0;for(int i=0;i<n;i++){assert(isfinite(a[i])&&isfinite(b[i]));maximum=fmaxf(maximum,fabsf(a[i]-b[i]));}return maximum;
}
/* This value oracle never calls backward, joint_loss, joint_coefficient, or
 * joint_order. Membership comes from the fixture, and each inference call is
 * one unweighted token. Accumulate the two CE sums in double before dividing. */
static double objective_value(mlp_bank *b,mlp_example *rows) {
    const int members[]={1,2,4,5};double decision_sum=0,residual_sum=0;int nd=0,nr=0;
    for(unsigned m=0;m<sizeof(members)/sizeof(*members);m++) {
        int row=members[m];
        for(int pos=0;pos<lengths[row];pos++) {
            token_row one={row,pos};mlp_batch s=gather(b,rows,&one,1);assert(!s.weights);
            nt_tape_start();int ce=mlp_forward(b,&s,0,NULL,NULL,NULL);
            double value=nt_tape_get()->entries[ce].output->data[0];assert(isfinite(value));
            assert(nt_tape_get()->n_params==0);
            if(pos==positions[row]){decision_sum+=value;nd++;}else{residual_sum+=value;nr++;}
            nt_tape_clear();batch_free(&s);
        }
    }
    assert(nd==DECISIONS&&nr==RESIDUAL);
    return decision_sum/DECISIONS+residual_sum/RESIDUAL;
}
static double derivative_tolerance(double analytic,double numerical) {
    /* CE outputs and inference arithmetic are float32. The absolute allowance
     * covers cancellation around h=.002; the relative allowance bounds larger
     * derivatives. Both constants are fixed for every tensor and both states. */
    return 1e-4+.02*fmax(fabs(analytic),fabs(numerical));
}
static int derivative_matches(double analytic,double numerical) {
    return isfinite(analytic)&&isfinite(numerical)&&fabs(analytic-numerical)<=derivative_tolerance(analytic,numerical);
}
static void finite_difference_tests(mlp_bank *b,mlp_example *rows,token_row *order) {
    const char *names[]={"gate.A","gate.B","up.A","up.B","down.A","down.B"};
    const float epsilon=.002f;float initial[ELEMENTS];int p=0;
    nt_tensor *frozen[]={b->wg,b->wu,b->wd,b->head,b->norm,b->ffn_norm,b->bias},*saved[7];
    for(int j=0;j<7;j++)saved[j]=nt_tensor_clone(frozen[j]);
    for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++)initial[p++]=parameter(b,j)->data[k];
    assert(p==ELEMENTS);
    for(int zero_b=0;zero_b<2;zero_b++) {
        reset_optimizer(b);p=0;
        for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++,p++)
            parameter(b,j)->data[k]=(zero_b&&j%2)?0:initial[p];
        float before[3*ELEMENTS],after[3*ELEMENTS],analytic[ELEMENTS];double numerical[ELEMENTS];
        read_state(b,0,before);double expected_loss=objective_value(b,rows),actual_loss;
        joint_accumulate(b,rows,order,TOTAL,7,DECISIONS,RESIDUAL,&actual_loss);
        read_gradient(b,analytic);read_state(b,0,after);assert(!memcmp(before,after,sizeof(before)));
        assert(fabs(actual_loss-expected_loss)<2e-6);nt_tape_clear();
        double max_error=0,max_fraction=0,max_a=0;int zero_a=0,wrong_normalization_rejected=0;p=0;
        for(int j=0;j<PARAMS;j++) {
            nt_tensor *param=parameter(b,j);double tensor_error=0,tensor_gradient=0;
            for(int k=0;k<param->len;k++,p++) {
                float old=param->data[k],hi=old+epsilon,lo=old-epsilon;assert(hi>old&&lo<old);
                param->data[k]=hi;double positive=objective_value(b,rows);
                param->data[k]=lo;double negative=objective_value(b,rows);param->data[k]=old;
                numerical[p]=(positive-negative)/((double)hi-lo);
                double error=fabs(analytic[p]-numerical[p]),tolerance=derivative_tolerance(analytic[p],numerical[p]);
                if(!derivative_matches(analytic[p],numerical[p]))
                    fprintf(stderr,"Joint finite difference failed: zero_B=%d %s[%d] analytic=%.9g numerical=%.9g error=%.9g tolerance=%.9g\n",zero_b,names[j],k,analytic[p],numerical[p],error,tolerance);
                assert(derivative_matches(analytic[p],numerical[p]));
                max_error=fmax(max_error,error);max_fraction=fmax(max_fraction,error/tolerance);
                tensor_error=fmax(tensor_error,error);tensor_gradient=fmax(tensor_gradient,fabs(analytic[p]));
                /* Averaging the two already-normalized partitions again is a
                 * plausible wrong objective. The same derivative gate must
                 * reject its half-sized gradients, without mutating code. */
                wrong_normalization_rejected+=!derivative_matches(.5*analytic[p],numerical[p]);
                if(zero_b&&j%2==0){assert(analytic[p]==0&&numerical[p]==0);zero_a++;}
                if(j%2==0)max_a=fmax(max_a,fabs(analytic[p]));
            }
            if(!zero_b||j%2)assert(tensor_gradient>1e-5);
            printf("Joint finite difference: state=%s tensor=%s coordinates=%d max_abs_error=%.9g max_abs_gradient=%.9g\n",zero_b?"zero-B":"nonzero-AB",names[j],param->len,tensor_error,tensor_gradient);
        }
        assert(p==ELEMENTS&&wrong_normalization_rejected>0);
        assert(!zero_b||(zero_a==20&&max_a==0));
        read_state(b,0,after);assert(!memcmp(before,after,sizeof(before)));
        for(int j=0;j<7;j++)assert(!memcmp(frozen[j]->data,saved[j]->data,(size_t)frozen[j]->len*sizeof(float)));
        printf("Joint finite difference: state=%s 42/42 pass h=%.9g loss=%.9g loss_error=%.9g max_abs_error=%.9g max_tolerance_fraction=%.9g; wrong half-normalization rejected at %d/42 coordinates; zero_A=%d; frozen weights unchanged\n",zero_b?"zero-B":"nonzero-AB",epsilon,expected_loss,fabs(actual_loss-expected_loss),max_error,max_fraction,wrong_normalization_rejected,zero_a);
    }
    reset_optimizer(b);p=0;
    for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++)parameter(b,j)->data[k]=initial[p++];
    for(int j=0;j<7;j++)nt_tensor_free(saved[j]);
}
static void diagnostics(mlp_bank *b,mlp_example *rows) {
    token_row all[ALL],decisions[DECISIONS];int p=0,q=0;
    for(int i=0;i<ROWS;i++)for(int j=0;j<lengths[i];j++){all[p++]=(token_row){i,j};if(j==positions[i])decisions[q++]=(token_row){i,j};}
    assert(p==ALL&&q==DECISIONS);int correct,exact,per_row[ROWS],first_error[ROWS];
    int expected_prefix[ROWS]={0};mlp_batch s=gather(b,rows,all,ALL);nt_tape_start();int logits;
    mlp_forward(b,&s,0,NULL,&logits,NULL);float *values=nt_tape_get()->entries[logits].output->data;
    for(int t=0;t<ALL;t++)if(all[t].token<positions[all[t].example]) {
        float *v=values+(size_t)t*b->V;int predicted=0;
        for(int j=1;j<b->V;j++)if(v[j]>v[predicted])predicted=j;
        expected_prefix[all[t].example]+=predicted==(int)s.targets->data[t];
    }
    nt_tape_clear();batch_free(&s);
    assert(isfinite(mean_ce(b,rows,all,ALL,7,ROWS,&correct,&exact,per_row,first_error)));
    for(int i=0;i<ROWS;i++)assert(rows[i].prefix_correct==expected_prefix[i]);
    assert(isfinite(decision_ce(b,rows,decisions,DECISIONS,&correct,&exact)));
    assert(nt_tape_get()->n_params==0);
}
static void objective_tests(mlp_bank *b,mlp_example *rows,token_row *order) {
    int at=0,nd=0,nr=0,eos=0,prefix=0;double dm=0,rm=0;
    for(int i=0;i<ROWS;i++)if(positions[i]>=0)for(int pos=0;pos<lengths[i];pos++,at++) {
        assert(order[at].example==i&&order[at].token==pos);
        int decision=pos==positions[i];float c=joint_coefficient(&rows[i],pos,DECISIONS,RESIDUAL);
        assert(fabs(c-(decision?1.0/DECISIONS:1.0/RESIDUAL))<1e-8);
        if(decision){nd++;dm+=c;}else{nr++;rm+=c;}
        eos+=pos==lengths[i]-1;prefix+=pos<positions[i];
    }
    assert(at==TOTAL&&nd==DECISIONS&&nr==RESIDUAL&&eos==4&&prefix==10);
    assert(fabs(dm-1)<1e-7&&fabs(rm-1)<1e-7);
    float expected[ELEMENTS],actual[ELEMENTS];double expected_loss=token_oracle(b,rows,expected);
    mlp_batch full=gather(b,rows,order,TOTAL);assert(!full.weights);full.weights=tensor(TOTAL,1);
    for(int i=0;i<TOTAL;i++)full.weights->data[i]=joint_coefficient(&rows[order[i].example],order[i].token,DECISIONS,RESIDUAL);
    nt_tape_start();double weighted_loss;int ce=joint_loss(b,&full,&weighted_loss);nt_tape_backward(ce);read_gradient(b,actual);
    assert(fabs(weighted_loss-expected_loss)<2e-6&&max_difference(expected,actual,ELEMENTS)<2e-6);
    nt_tape_clear();batch_free(&full);
    const int batches[]={1,3,7,11,TOTAL,40};double loss_error=0;float gradient_error=0;
    for(unsigned run=0;run<sizeof(batches)/sizeof(*batches);run++) {
        float before[3*ELEMENTS],after[3*ELEMENTS];read_state(b,0,before);
        joint_accumulate(b,rows,order,TOTAL,batches[run],DECISIONS,RESIDUAL,&weighted_loss);read_gradient(b,actual);read_state(b,0,after);
        assert(!memcmp(before,after,sizeof(before)));
        loss_error=fmax(loss_error,fabs(weighted_loss-expected_loss));gradient_error=fmaxf(gradient_error,max_difference(expected,actual,ELEMENTS));
        assert(fabs(weighted_loss-expected_loss)<2e-6&&max_difference(expected,actual,ELEMENTS)<2e-6);nt_tape_clear();
    }
    /* The two unmapped rows have zero objective mass even when every one of
     * their targets and frozen activations changes. */
    for(int i=0;i<ROWS;i++)if(positions[i]<0) {
        mlp_batch *s=&rows[i].cache;nt_tensor *cache[]={s->z,s->xn,s->gate,s->up};
        for(int p=0;p<s->n;p++)s->targets->data[p]=(float)(((int)s->targets->data[p]+3)%b->V);
        for(int j=0;j<4;j++)fixture_fill(cache[j],.32f,j+9);
    }
    float changed[ELEMENTS];double changed_loss=token_oracle(b,rows,changed);
    assert(changed_loss==expected_loss&&!memcmp(changed,expected,sizeof(changed)));
    joint_accumulate(b,rows,order,TOTAL,7,DECISIONS,RESIDUAL,&weighted_loss);read_gradient(b,actual);
    assert(fabs(weighted_loss-expected_loss)<2e-6&&max_difference(expected,actual,ELEMENTS)<2e-6);nt_tape_clear();
    /* Changing only EOS targets must change both loss and adapter gradients. */
    for(int i=0;i<ROWS;i++)if(positions[i]>=0)rows[i].cache.targets->data[lengths[i]-1]=0;
    changed_loss=token_oracle(b,rows,changed);assert(fabs(changed_loss-expected_loss)>1e-4&&max_difference(expected,changed,ELEMENTS)>1e-5);
    joint_accumulate(b,rows,order,TOTAL,11,DECISIONS,RESIDUAL,&weighted_loss);read_gradient(b,actual);
    assert(fabs(weighted_loss-changed_loss)<2e-6&&max_difference(changed,actual,ELEMENTS)<2e-6);nt_tape_clear();
    for(int i=0;i<ROWS;i++)if(positions[i]>=0)rows[i].cache.targets->data[lengths[i]-1]=6;
    printf("Joint objective: 4 decision + 25 residual positions; each partition has unit mass; 4 EOS included, 2 unmapped rows excluded; 6 microbatch sizes match independent token derivatives (loss=%g gradient=%g)\n",loss_error,gradient_error);
}
static void optimizer_tests(mlp_bank *b,mlp_example *rows,token_row *order) {
    float initial[ELEMENTS],reference[STEPS+1][3*ELEMENTS],interleaved[STEPS+1][3*ELEMENTS];int p=0;
    for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++)initial[p++]=parameter(b,j)->data[k];
    assert(p==ELEMENTS);
    const int batches[]={TOTAL,1,3,7,11};float max_update_error=0,max_norm_error=0,max_trajectory_error=0;int clipped=0;
    for(unsigned run=0;run<sizeof(batches)/sizeof(*batches);run++)for(int with_diagnostics=0;with_diagnostics<2;with_diagnostics++) {
        reset_optimizer(b);p=0;for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++)parameter(b,j)->data[k]=initial[p++];
        float ref_m[ELEMENTS]={0},ref_v[ELEMENTS]={0};
        for(int step=0;step<=STEPS;step++) {
            float state[3*ELEMENTS];read_state(b,step,state);
            if(!run&&!with_diagnostics)memcpy(reference[step],state,sizeof(state));
            if(!with_diagnostics)memcpy(interleaved[step],state,sizeof(state));
            else assert(!memcmp(interleaved[step],state,sizeof(state)));
            float trajectory_error=max_difference(reference[step],state,3*ELEMENTS);max_trajectory_error=fmaxf(max_trajectory_error,trajectory_error);assert(trajectory_error<3e-6);
            if(with_diagnostics) {
                nt_tensor *m[PARAMS],*v[PARAMS];for(int j=0;j<PARAMS;j++){m[j]=nt_tape_get()->adam[j].m;v[j]=nt_tape_get()->adam[j].v;}
                diagnostics(b,rows);float after[3*ELEMENTS];read_state(b,step,after);assert(!memcmp(state,after,sizeof(state)));
                for(int j=0;j<PARAMS;j++)assert(m[j]==nt_tape_get()->adam[j].m&&v[j]==nt_tape_get()->adam[j].v);
            }
            if(step==STEPS)break;
            float raw[ELEMENTS];double expected_loss=token_oracle(b,rows,raw),actual_loss;
            joint_accumulate(b,rows,order,TOTAL,batches[run],DECISIONS,RESIDUAL,&actual_loss);
            float before_clip[ELEMENTS];read_gradient(b,before_clip);assert(max_difference(raw,before_clip,ELEMENTS)<2e-6&&fabs(actual_loss-expected_loss)<2e-6);
            float unchanged[3*ELEMENTS];read_state(b,step,unchanged);assert(!memcmp(state,unchanged,sizeof(state)));
            double sumsq=0;for(int k=0;k<ELEMENTS;k++)sumsq+=(double)raw[k]*raw[k];float expected_norm=(float)sqrt(sumsq);
            float norm=nt_tape_clip_grads(clip_limit),norm_error=fabsf(norm-expected_norm);max_norm_error=fmaxf(max_norm_error,norm_error);
            assert(norm_error<2e-6&&norm>clip_limit);clipped++;
            float scale=clip_limit/(expected_norm+1e-6f),expected[ELEMENTS];p=0;
            for(int j=0;j<PARAMS;j++)for(int k=0;k<parameter(b,j)->len;k++,p++) {
                float g=raw[p]*scale;ref_m[p]=.9f*ref_m[p]+(1-.9f)*g;ref_v[p]=.999f*ref_v[p]+(1-.999f)*g*g;
                float mh=ref_m[p]/(1-powf(.9f,(float)(step+1))),vh=ref_v[p]/(1-powf(.999f,(float)(step+1)));
                expected[p]=parameter(b,j)->data[k]-learning_rate*mh/(sqrtf(vh)+1e-8f);
            }
            nt_tape_adam_step(learning_rate);float updated[3*ELEMENTS];read_state(b,step+1,updated);
            float update_error=max_difference(expected,updated,ELEMENTS);max_update_error=fmaxf(max_update_error,update_error);
            assert(update_error<5e-7&&max_difference(ref_m,updated+ELEMENTS,ELEMENTS)<1e-9&&max_difference(ref_v,updated+2*ELEMENTS,ELEMENTS)<1e-12);
            nt_tape_clear();
        }
    }
    assert(clipped==40);assert(max_difference(initial,reference[STEPS],ELEMENTS)>1e-4);
    printf("Joint optimizer: %d whole-objective clipped Adam steps; 5 batch sizes preserve trajectories; diagnostics preserve parameters/moments bit-for-bit (update=%g norm=%g trajectory=%g)\n",clipped,max_update_error,max_norm_error,max_trajectory_error);
}
static void rejection_tests(mlp_bank *b,mlp_example *rows,token_row *order) {
    const char *cases[]={"empty map","negative decision position","EOS decision position","unpaired membership","missing CLI map","zero batch","invalid partition"};
    for(unsigned test=0;test<sizeof(cases)/sizeof(*cases);test++) {
        FILE *errors=tmpfile();assert(errors);fflush(NULL);pid_t pid=fork();assert(pid>=0);
        if(!pid) {
            if(dup2(fileno(errors),STDERR_FILENO)<0)_exit(2);
            int nd,nr;double loss;
            switch(test) {
            case 0:for(int i=0;i<ROWS;i++)rows[i].decision_pair=0;free(joint_order(rows,ROWS,&nd,&nr));break;
            case 1:rows[1].decision_position=-1;free(joint_order(rows,ROWS,&nd,&nr));break;
            case 2:rows[1].decision_position=rows[1].cache.n-1;free(joint_order(rows,ROWS,&nd,&nr));break;
            case 3:rows[2].decision_pair=0;free(joint_order(rows,ROWS,&nd,&nr));break;
            case 4:{char *args[]={"train-mlp","/missing-base","/missing-data","/missing-output","1","0.0001","7","0","joint",NULL};_exit(mlp_trainer_main(9,args));}
            case 5:joint_accumulate(b,rows,order,TOTAL,0,DECISIONS,RESIDUAL,&loss);break;
            case 6:joint_accumulate(b,rows,order,TOTAL,7,DECISIONS,0,&loss);break;
            }
            _exit(0);
        }
        int status;assert(waitpid(pid,&status,0)==pid);
        if(!WIFEXITED(status)||WEXITSTATUS(status)!=1)fprintf(stderr,"joint rejection failed: %s\n",cases[test]);
        assert(WIFEXITED(status)&&WEXITSTATUS(status)==1);
        if(test==4) {
            char message[256]={0};rewind(errors);assert(fread(message,1,sizeof(message)-1,errors)>0);
            assert(strstr(message,"objectives require a pair map"));
        }
        fclose(errors);
    }
    printf("Joint selection: %zu invalid map/objective inputs rejected\n",sizeof(cases)/sizeof(*cases));
}
int main(void) {
    mlp_bank b;mlp_example rows[ROWS];fixture_init(&b,rows);
    int nd,nr;token_row *order=joint_order(rows,ROWS,&nd,&nr);assert(nd==DECISIONS&&nr==RESIDUAL);
    finite_difference_tests(&b,rows,order);objective_tests(&b,rows,order);optimizer_tests(&b,rows,order);rejection_tests(&b,rows,order);
    free(order);fixture_free(&b,rows);return 0;
}
