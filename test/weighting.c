#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>

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
    nt_tape_start();for(int j=0;j<3;j++){nt_tape_param(b.adapters[j].A);nt_tape_param(b.adapters[j].B);}nt_tape_destroy();
    for(int j=0;j<3;j++)nt_lora_free(&b.adapters[j]);
    nt_tensor_free(b.wg);nt_tensor_free(b.wu);nt_tensor_free(b.wd);nt_tensor_free(b.head);nt_tensor_free(b.norm);nt_tensor_free(b.ffn_norm);
    for(int i=0;i<2;i++)batch_free(&rows[i].cache);
    return 0;
}
