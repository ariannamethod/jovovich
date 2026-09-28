#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>

static float test_loss(mlp_bank *b,mlp_batch *s) {
    nt_tape_start();int ce=mlp_forward(b,s,0,NULL,NULL,NULL);
    float value=nt_tape_get()->entries[ce].output->data[0];nt_tape_clear();return value;
}
static void fill(nt_tensor *t,float scale,int shift) {
    for(int i=0;i<t->len;i++)t->data[i]=scale*(float)(((i*7+shift)%17)-8);
}
int main(void) {
    mlp_bank b={.E=4,.F=5,.V=7,.layer=1};
    b.wg=tensor(b.F,b.E);b.wu=tensor(b.F,b.E);b.wd=tensor(b.E,b.F);b.head=tensor(b.V,b.E);
    b.norm=tensor(1,b.E);b.ffn_norm=tensor(1,b.E);b.bias=tensor(1,b.E);
    fill(b.wg,.07f,2);fill(b.wu,.06f,3);fill(b.wd,.08f,4);fill(b.head,.11f,5);
    for(int i=0;i<b.E;i++){b.norm->data[i]=.8f+.1f*i;b.ffn_norm->data[i]=1.1f-.05f*i;b.bias->data[i]=.01f*(i-2);}
    for(int j=0;j<3;j++) {
        assert(nt_lora_init(&b.adapters[j],j==2?b.F:b.E,j==2?b.E:b.F,2,4)==0);
        fill(b.adapters[j].A,.035f,1+j);fill(b.adapters[j].B,.025f,4+j);
    }
    mlp_example ex={0};ex.cache.n=3;ex.cache.z=tensor(3,b.E);ex.cache.targets=tensor(3,1);
    fill(ex.cache.z,.12f,1);for(int i=0;i<3;i++)ex.cache.targets->data[i]=(float)(i*2+1);
    prepare_cache(&b,&ex.cache);token_row order[]={{0,0},{0,1},{0,2}};mlp_batch s=gather(&b,&ex,order,3);
    int slots[6],ri,li;nt_tape_start();int ce=mlp_forward(&b,&s,1,&ri,&li,slots);nt_tape_backward(ce);
    float gradients[54];int p=0;float per_target[3]={0};
    for(int j=0;j<6;j++) {
        nt_tape_entry *entry=&nt_tape_get()->entries[slots[j]];assert(entry->grad);
        for(int k=0;k<entry->grad->len;k++){gradients[p++]=entry->grad->data[k];per_target[j/2]=fmaxf(per_target[j/2],fabsf(entry->grad->data[k]));}
    }
    assert(p==54);nt_tensor *expected_r=nt_tensor_clone(nt_tape_get()->entries[ri].output),*expected_l=nt_tensor_clone(nt_tape_get()->entries[li].output);
    nt_tape_clear();float max_error=0;p=0;
    for(int j=0;j<6;j++) {
        nt_tensor *param=j%2?b.adapters[j/2].B:b.adapters[j/2].A;
        for(int k=0;k<param->len;k++) {
            float old=param->data[k],eps=.002f;param->data[k]=old+eps;float hi=test_loss(&b,&s);
            param->data[k]=old-eps;float lo=test_loss(&b,&s);param->data[k]=old;
            float numerical=(hi-lo)/(2*eps),error=fabsf(numerical-gradients[p]);max_error=fmaxf(max_error,error);
            assert(error<.0002f+.02f*fabsf(gradients[p]));p++;
        }
    }
    for(int j=0;j<3;j++)assert(per_target[j]>.00001f);

    /* Fold all three adapters into independent matrices, turn the adapters
     * off, and recompute the changed gate/up caches. This catches a detached
     * down-input branch, missing residual, or wrong merge orientation. */
    nt_tensor *bases[]={b.wg,b.wu,b.wd};nt_tensor *saved[3];
    for(int j=0;j<3;j++) {
        saved[j]=nt_tensor_clone(bases[j]);nt_lora_pair *a=&b.adapters[j];
        nt_lora_merge_into(bases[j]->data,saved[j]->data,a,a->in_dim,a->out_dim);nt_tensor_fill(a->B,0);
    }
    nt_tensor_free(ex.cache.xn);nt_tensor_free(ex.cache.gate);nt_tensor_free(ex.cache.up);prepare_cache(&b,&ex.cache);
    batch_free(&s);s=gather(&b,&ex,order,3);nt_tape_start();mlp_forward(&b,&s,0,&ri,&li,NULL);
    float merge_error=0;nt_tensor *actual[]={nt_tape_get()->entries[ri].output,nt_tape_get()->entries[li].output};nt_tensor *expected[]={expected_r,expected_l};
    for(int j=0;j<2;j++)for(int i=0;i<actual[j]->len;i++){float err=fabsf(actual[j]->data[i]-expected[j]->data[i]);merge_error=fmaxf(merge_error,err);assert(err<2e-6f);}
    nt_tape_clear();

    /* One real optimizer step may only change the six adapter tensors. */
    nt_tensor *frozen[]={b.wg,b.wu,b.wd,b.head,b.norm,b.ffn_norm,b.bias};nt_tensor *copies[7];
    for(int j=0;j<7;j++)copies[j]=nt_tensor_clone(frozen[j]);
    nt_tape_start();ce=mlp_forward(&b,&s,1,NULL,NULL,NULL);nt_tape_backward(ce);nt_tape_adam_step(.001f);nt_tape_clear();
    float update=0;for(int j=0;j<3;j++)for(int i=0;i<b.adapters[j].B->len;i++)update+=fabsf(b.adapters[j].B->data[i]);assert(update>0);
    for(int j=0;j<7;j++){assert(!memcmp(frozen[j]->data,copies[j]->data,(size_t)frozen[j]->len*sizeof(float)));nt_tensor_free(copies[j]);}
    printf("MLP LoRA: 54/54 finite differences max_error=%g; gate/up/down max_grad=%g/%g/%g; merged residual/logits max_error=%g; frozen tensors unchanged\n",max_error,per_target[0],per_target[1],per_target[2],merge_error);
    nt_tape_start();for(int j=0;j<3;j++){nt_tape_param(b.adapters[j].A);nt_tape_param(b.adapters[j].B);}nt_tape_destroy();
    for(int j=0;j<3;j++){nt_lora_free(&b.adapters[j]);nt_tensor_free(saved[j]);}
    for(int j=0;j<7;j++)nt_tensor_free(frozen[j]);
    nt_tensor_free(expected_r);nt_tensor_free(expected_l);batch_free(&s);batch_free(&ex.cache);
    return 0;
}
