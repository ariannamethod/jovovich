#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>
#include <sys/wait.h>

static void weighted_fill(nt_tensor *t,float scale,int shift) {
    for(int i=0;i<t->len;i++)t->data[i]=scale*(float)(((i*7+shift)%17)-8);
}
static void read_gradients(const int *slots,float *out) {
    int p=0;
    for(int j=0;j<6;j++) {
        nt_tape_entry *e=&nt_tape_get()->entries[slots[j]];
        assert(e->grad&&e->grad->len==e->output->len);
        for(int k=0;k<e->grad->len;k++)out[p++]=e->grad->data[k];
    }
    assert(p==54);
}
static void map_u32(unsigned char *p,uint32_t n) {
    for(int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));
}
static void map_file(char *path,const unsigned char *data,size_t n) {
    int fd=mkstemp(path);assert(fd>=0);FILE *f=fdopen(fd,"wb");assert(f);
    assert(fwrite(data,1,n,f)==n);assert(fclose(f)==0);
}
static void reject_map(mlp_bank *b,mlp_example *rows,const unsigned char *data,size_t n,int completion,const char *label) {
    char path[]="/tmp/jovovich-pairs-XXXXXX";map_file(path,data,n);fflush(NULL);
    pid_t pid=fork();assert(pid>=0);
    if(!pid) {
        if(!freopen("/dev/null","w",stderr))_exit(2);
        mlp_example fresh[5];memcpy(fresh,rows,sizeof(fresh));
        for(int i=0;i<5;i++)fresh[i].decision_pair=0;
        if(completion) {
            int ncopy=fresh[0].cache.n-(completion==2);
            memcpy(fresh[1].cache.targets->data,fresh[0].cache.targets->data,(size_t)ncopy*sizeof(float));
            if(completion==1)fresh[1].cache.n=fresh[0].cache.n;
        }
        load_pairs(b,fresh,5,path);_exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid);assert(unlink(path)==0);
    if(!WIFEXITED(status)||WEXITSTATUS(status)!=1)fprintf(stderr,"pair-map rejection failed: %s\n",label);
    assert(WIFEXITED(status)&&WEXITSTATUS(status)==1);
}
static float training_value(mlp_bank *b,mlp_batch *s,float *gradient) {
    int slots[6];nt_tape_start();int ce=mlp_forward(b,s,1,NULL,NULL,slots);
    float value=nt_tape_get()->entries[ce].output->data[0];
    nt_tape_backward(ce);read_gradients(slots,gradient);nt_tape_clear();return value;
}
static void verdict_tests(mlp_bank *b) {
    enum { COUNT=5,TOTAL=43 };
    const int lengths[COUNT]={6,9,8,13,7},positions[COUNT]={4,4,5,5,-1};
    mlp_example rows[COUNT]={0};token_row all[TOTAL];int p=0;
    b->average_tokens=(double)TOTAL/COUNT;b->verdict_weighting=0;
    for(int i=0;i<COUNT;i++) {
        mlp_batch *s=&rows[i].cache;s->n=lengths[i];s->z=tensor(s->n,b->E);s->targets=tensor(s->n,1);
        weighted_fill(s->z,.12f,i+2);
        for(int t=0;t<s->n;t++){s->targets->data[t]=(float)((t+1)%5);all[p++]=(token_row){i,t};}
        s->targets->data[s->n-1]=6; /* EOS participates in weighting, never in pair discovery. */
        prepare_cache(b,s);
    }
    rows[0].cache.targets->data[4]=1;rows[1].cache.targets->data[4]=2;
    rows[2].cache.targets->data[5]=3;rows[3].cache.targets->data[5]=4;
    assert(p==TOTAL);
    float baseline_loss[2],baseline_gradient[2][54],baseline_weights[TOTAL];
    for(int mode=0;mode<2;mode++) {
        b->example_weighting=mode;mlp_batch s=gather(b,rows,all,TOTAL);
        assert((s.weights!=NULL)==mode);
        if(mode)memcpy(baseline_weights,s.weights->data,sizeof(baseline_weights));
        baseline_loss[mode]=training_value(b,&s,baseline_gradient[mode]);batch_free(&s);
    }
    unsigned char valid[32]={ 'J','V','P','R',1,0,0,0 };
    map_u32(valid+8,COUNT);map_u32(valid+12,2);
    map_u32(valid+16,0);map_u32(valid+20,1);map_u32(valid+24,2);map_u32(valid+28,3);
    char path[]="/tmp/jovovich-pairs-XXXXXX";map_file(path,valid,sizeof(valid));
    load_pairs(b,rows,COUNT,path);assert(unlink(path)==0);
    assert(b->pair_count==2&&b->verdict_weighting==0);
    float old[COUNT];double pooled=0;
    for(int i=0;i<COUNT;i++) {
        old[i]=(float)((double)TOTAL/COUNT/lengths[i]);if(i<4)pooled+=old[i];
        assert(rows[i].decision_pair==(i<4?i/2+1:0));
        if(i<4) {
            assert(rows[i].decision_position==positions[i]);
            assert(rows[i].decision_alternative_id==(int)rows[i^1].cache.targets->data[positions[i]]);
        }
    }
    float expected_pool=(float)(pooled/4);assert(fabs(b->verdict_weight-expected_pool)<2e-7);
    assert(fabsf(expected_pool-(old[0]+old[1])/2)>.1f);
    /* Merely loading diagnostic pairs cannot alter either existing objective. */
    for(int mode=0;mode<2;mode++) {
        b->example_weighting=mode;mlp_batch s=gather(b,rows,all,TOTAL);float gradient[54];
        assert((s.weights!=NULL)==mode);
        if(mode)assert(!memcmp(baseline_weights,s.weights->data,sizeof(baseline_weights)));
        assert(training_value(b,&s,gradient)==baseline_loss[mode]);
        assert(!memcmp(gradient,baseline_gradient[mode],sizeof(gradient)));batch_free(&s);
    }
    b->example_weighting=1;b->verdict_weighting=1;
    mlp_batch full=gather(b,rows,all,TOTAL);double before=0,after=0;
    for(int t=0;t<TOTAL;t++) {
        int i=all[t].example;float expected=all[t].token==positions[i]?expected_pool:old[i];
        assert(fabsf(full.weights->data[t]-expected)<2e-7f);
        before+=old[i];after+=full.weights->data[t];
    }
    assert(fabs(before-after)<5e-6);assert(fabs(after-TOTAL)<5e-6);
    int expected_correct[COUNT]={0},expected_first[COUNT],expected_predicted[4];float expected_margin[4];
    for(int i=0;i<COUNT;i++)expected_first[i]=-1;
    nt_tape_start();int li,ce=mlp_forward(b,&full,0,NULL,&li,NULL);
    float expected_mean=nt_tape_get()->entries[ce].output->data[0],*logits=nt_tape_get()->entries[li].output->data;
    for(int t=0;t<TOTAL;t++) {
        int i=all[t].example,pos=all[t].token,predicted=0,target=(int)full.targets->data[t];
        float *l=logits+(size_t)t*b->V;for(int j=1;j<b->V;j++)if(l[j]>l[predicted])predicted=j;
        if(predicted==target)expected_correct[i]++;else if(expected_first[i]<0)expected_first[i]=pos;
        if(pos==positions[i]) {
            expected_predicted[i]=predicted;
            expected_margin[i]=l[target]-l[(int)rows[i^1].cache.targets->data[pos]];
        }
    }
    nt_tape_clear();batch_free(&full);
    /* Reverse the traversal so diagnostics must follow row/token positions. */
    token_row reverse[TOTAL];for(int t=0;t<TOTAL;t++)reverse[t]=all[TOTAL-1-t];
    int correct,exact,row_correct[COUNT],first_error[COUNT],expected_total=0,expected_exact=0;
    double evaluation=mean_ce(b,rows,reverse,TOTAL,7,COUNT,&correct,&exact,row_correct,first_error);
    assert(fabs(evaluation-expected_mean)<2e-6);
    for(int i=0;i<COUNT;i++) {
        assert(row_correct[i]==expected_correct[i]&&first_error[i]==expected_first[i]);
        expected_total+=expected_correct[i];expected_exact+=expected_correct[i]==lengths[i];
        if(i<4) {
            assert(rows[i].decision_predicted_id==expected_predicted[i]);
            assert(rows[i].decision_correct==(expected_predicted[i]==(int)rows[i].cache.targets->data[positions[i]]));
            assert(fabsf(rows[i].decision_margin-expected_margin[i])<1e-6f);
        } else assert(rows[i].decision_correct==0&&rows[i].decision_margin==0&&rows[i].decision_predicted_id==-1);
    }
    assert(correct==expected_total&&exact==expected_exact);
    const token_row order[]={{0,4},{2,5},{1,4},{4,3},{3,5},{0,5},{1,8},{2,1},{3,12}};
    const int sizes[]={1,3,5,9};float max_loss_error=0,max_gradient_error=0;
    for(int run=0;run<4;run++) {
        int n=sizes[run];mlp_batch s=gather(b,rows,order,n);float actual_grad[54];
        float actual_loss=training_value(b,&s,actual_grad),expected_loss=0,unweighted_loss=0,expected_grad[54]={0};
        /* Independent token derivatives catch masked-CE normalization mistakes,
         * including batches containing only pooled verdict tokens. */
        for(int t=0;t<n;t++) {
            mlp_batch single=gather(b,rows,order+t,1);nt_tensor_free(single.weights);single.weights=NULL;
            int i=order[t].example;float weight=order[t].token==positions[i]?expected_pool:old[i],gradient[54];
            float value=training_value(b,&single,gradient);expected_loss+=weight/n*value;unweighted_loss+=value/n;
            for(int j=0;j<54;j++)expected_grad[j]+=weight/n*gradient[j];
            batch_free(&single);
        }
        float loss_error=fabsf(actual_loss-expected_loss);max_loss_error=fmaxf(max_loss_error,loss_error);assert(loss_error<2e-6f);
        for(int j=0;j<54;j++) {
            float error=fabsf(actual_grad[j]-expected_grad[j]);max_gradient_error=fmaxf(max_gradient_error,error);assert(error<2e-6f);
        }
        nt_tape_start();int ce=mlp_forward(b,&s,0,NULL,NULL,NULL);
        assert(fabsf(nt_tape_get()->entries[ce].output->data[0]-unweighted_loss)<1e-6f);
        assert(nt_tape_get()->n_params==0);nt_tape_clear();batch_free(&s);
    }
    unsigned char bad[33];int rejected=0;
#define REJECT(N,COMPLETION,LABEL) do { reject_map(b,rows,bad,N,COMPLETION,LABEL);rejected++; } while(0)
    memcpy(bad,valid,32);bad[0]='X';REJECT(32,0,"magic");
    memcpy(bad,valid,32);bad[4]=2;REJECT(32,0,"version");
    memcpy(bad,valid,32);REJECT(7,0,"truncated magic");REJECT(11,0,"truncated row count");REJECT(15,0,"truncated pair count");REJECT(31,0,"truncated pair");
    map_u32(bad+8,COUNT+1);REJECT(32,0,"row-count mismatch");
    memcpy(bad,valid,32);bad[32]=1;REJECT(33,0,"trailing bytes");
    memcpy(bad,valid,32);map_u32(bad+12,UINT32_MAX);REJECT(32,0,"oversized pair count");
    memcpy(bad,valid,32);map_u32(bad+20,0);REJECT(32,0,"self pair");
    memcpy(bad,valid,32);map_u32(bad+24,0);REJECT(32,0,"duplicate concern row");
    memcpy(bad,valid,32);map_u32(bad+28,1);REJECT(32,0,"duplicate clean row");
    memcpy(bad,valid,32);map_u32(bad+24,1);REJECT(32,0,"cross-role duplicate row");
    memcpy(bad,valid,32);map_u32(bad+28,COUNT);REJECT(32,0,"out-of-range row");
    memcpy(bad,valid,32);map_u32(bad+28,UINT32_MAX);REJECT(32,0,"overflow row");
    memcpy(bad,valid,32);REJECT(32,1,"identical completions");REJECT(32,2,"concern prefix only");
    map_u32(bad+16,1);map_u32(bad+20,0);REJECT(32,2,"clean prefix only");
#undef REJECT
    printf("Verdict weighting: global pool=%g; mass error=%g; 4 batch sizes, 216 adapter gradients match independent composition (loss=%g gradient=%g); defaults/evaluation unchanged; %d invalid maps rejected\n",expected_pool,fabs(before-after),max_loss_error,max_gradient_error,rejected);
    for(int i=0;i<COUNT;i++)batch_free(&rows[i].cache);
}
int main(void) {
    mlp_bank b={.E=4,.F=5,.V=7,.layer=1,.example_weighting=1,.average_tokens=2.5f};
    b.wg=tensor(b.F,b.E);b.wu=tensor(b.F,b.E);b.wd=tensor(b.E,b.F);b.head=tensor(b.V,b.E);
    b.norm=tensor(1,b.E);b.ffn_norm=tensor(1,b.E);
    weighted_fill(b.wg,.07f,2);weighted_fill(b.wu,.06f,3);
    weighted_fill(b.wd,.08f,4);weighted_fill(b.head,.11f,5);
    for(int j=0;j<b.E;j++){b.norm->data[j]=.8f+.1f*j;b.ffn_norm->data[j]=1.1f-.05f*j;}
    for(int j=0;j<3;j++) {
        int rc=nt_lora_init(&b.adapters[j],j==2?b.F:b.E,j==2?b.E:b.F,2,4);assert(rc==0);
        weighted_fill(b.adapters[j].A,.035f,j+1);weighted_fill(b.adapters[j].B,.025f,j+4);
    }
    mlp_example rows[2]={0};
    for(int i=0;i<2;i++) {
        mlp_batch *s=&rows[i].cache;s->n=2+i;s->z=tensor(s->n,b.E);s->targets=tensor(s->n,1);
        weighted_fill(s->z,.12f,1+i);
        for(int t=0;t<s->n;t++)s->targets->data[t]=(float)(t*2+1);
        prepare_cache(&b,s);
    }
    token_row order[]={{0,0},{0,1},{1,0},{1,1},{1,2}};
    float max_loss_error=0,max_gradient_error=0;
    const int sizes[]={1,2,3,5};
    for(int run=0;run<4;run++) {
        int n=sizes[run],slots[6];mlp_batch s=gather(&b,rows,order,n);
        for(int t=0;t<n;t++)assert(fabsf(s.weights->data[t]-2.5f/rows[order[t].example].cache.n)<1e-7f);
        nt_tape_start();int loss=mlp_forward(&b,&s,1,NULL,NULL,slots);
        float actual_loss=nt_tape_get()->entries[loss].output->data[0],actual_grad[54];
        nt_tape_backward(loss);read_gradients(slots,actual_grad);nt_tape_clear();
        float expected_loss=0,expected_grad[54]={0},unweighted_loss=0;
        /* Independently differentiate each unweighted token, then apply the
         * corpus-level weight / actual batch size to its loss and gradient.
         * Short-only minibatches catch accidental batch renormalization. */
        for(int t=0;t<n;t++) {
            mlp_batch single=gather(&b,rows,order+t,1);
            nt_tensor_free(single.weights);single.weights=NULL;
            nt_tape_start();int ce=mlp_forward(&b,&single,1,NULL,NULL,slots);
            float value=nt_tape_get()->entries[ce].output->data[0],gradient[54];
            float coefficient=2.5f/rows[order[t].example].cache.n/n;
            expected_loss+=coefficient*value;unweighted_loss+=value/n;
            nt_tape_backward(ce);read_gradients(slots,gradient);
            for(int j=0;j<54;j++)expected_grad[j]+=coefficient*gradient[j];
            nt_tape_clear();batch_free(&single);
        }
        max_loss_error=fmaxf(max_loss_error,fabsf(actual_loss-expected_loss));
        assert(fabsf(actual_loss-expected_loss)<1e-6f);
        for(int j=0;j<54;j++) {
            float error=fabsf(actual_grad[j]-expected_grad[j]);
            max_gradient_error=fmaxf(max_gradient_error,error);assert(error<2e-6f);
        }
        nt_tape_start();int eval=mlp_forward(&b,&s,0,NULL,NULL,NULL);
        assert(fabsf(nt_tape_get()->entries[eval].output->data[0]-unweighted_loss)<1e-6f);
        assert(nt_tape_get()->n_params==0);nt_tape_clear();batch_free(&s);
    }
    printf("Example weighting: 4 batch sizes, 216 adapter gradients match independent token composition; max_loss_error=%g max_gradient_error=%g; evaluation remains token-mean\n",max_loss_error,max_gradient_error);
    verdict_tests(&b);
    nt_tape_start();for(int j=0;j<3;j++){nt_tape_param(b.adapters[j].A);nt_tape_param(b.adapters[j].B);}nt_tape_destroy();
    for(int j=0;j<3;j++)nt_lora_free(&b.adapters[j]);
    nt_tensor_free(b.wg);nt_tensor_free(b.wu);nt_tensor_free(b.wd);nt_tensor_free(b.head);nt_tensor_free(b.norm);nt_tensor_free(b.ffn_norm);
    for(int i=0;i<2;i++)batch_free(&rows[i].cache);
    return 0;
}
