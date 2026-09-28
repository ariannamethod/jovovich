#define main trainer_main
#include "../training/train_head.c"
#undef main
#include <assert.h>
static float dpo_value(sequence *c, sequence *r, nt_lora_pair *a,int vocab) {
 float cv=eval_ce(c,a,vocab),rv=eval_ce(r,a,vocab);
 float z=BETA*(c->n*(c->ref_ce-cv)-r->n*(r->ref_ce-rv));
 return fmaxf(-z,0)+log1pf(expf(-fabsf(z)));
}
int main(void) {
 const int E=3,V=5;nt_lora_pair a; assert(nt_lora_init(&a,E,V,2,4)==0);
 for(int i=0;i<a.A->len;i++)a.A->data[i]=0.11f*(i-2);
 for(int i=0;i<a.B->len;i++)a.B->data[i]=0.07f*(i-4);
 float weights[15];for(int i=0;i<15;i++)weights[i]=0.03f*(i-7);
 sequence c={0},r={0};sequence *seqs[]={&c,&r};
 for(int z=0;z<2;z++){
  sequence *s=seqs[z];s->n=2+z;s->x=nt_tensor_new2d(s->n,E);s->logits=nt_tensor_new2d(s->n,V);s->targets=nt_tensor_new(s->n);
  for(int i=0;i<s->x->len;i++)s->x->data[i]=0.15f*(i-2+z);
  for(int t=0;t<s->n;t++){
   s->targets->data[t]=(float)((t+z)%V);
   for(int v=0;v<V;v++)for(int e=0;e<E;e++)s->logits->data[t*V+v]+=weights[v*E+e]*s->x->data[t*E+e];
  }
  s->ref_ce=eval_ce(s,&a,V)+(z?-.15f:.1f);
 }
 nt_tape_start();int ai=nt_tape_param(a.A),bi=nt_tape_param(a.B);
 int ci=loss(&c,&a,ai,bi,V),ri=loss(&r,&a,ai,bi,V);
 float margin=c.n*(c.ref_ce-value(ci))-r.n*(r.ref_ce-value(ri));
 float coeff=BETA/(1+expf(BETA*margin));
 int weighted=nt_add(nt_scale(ci,coeff*c.n),nt_scale(ri,-coeff*r.n));
 nt_tape_backward(weighted);
 float grad[16];memcpy(grad,nt_tape_get()->entries[ai].grad->data,6*sizeof(float));memcpy(grad+6,nt_tape_get()->entries[bi].grad->data,10*sizeof(float));nt_tape_clear();
 float max_error=0,max_grad=0;
 for(int i=0;i<16;i++){
  float *p=i<6?&a.A->data[i]:&a.B->data[i-6];float old=*p,eps=.005f;
  *p=old+eps;float hi=dpo_value(&c,&r,&a,V);*p=old-eps;float lo=dpo_value(&c,&r,&a,V);*p=old;
  float numeric=(hi-lo)/(2*eps),error=fabsf(numeric-grad[i]);if(error>max_error)max_error=error;if(fabsf(grad[i])>max_grad)max_grad=fabsf(grad[i]);
  assert(error<.0001f+.01f*fabsf(grad[i]));
 }
 assert(max_grad>.001f);
 float merged[15];nt_lora_merge_into(merged,weights,&a,E,V);
 float worst=0;
 for(int t=0;t<c.n;t++)for(int v=0;v<V;v++){
  float actual=0,expected=c.logits->data[t*V+v];
  for(int e=0;e<E;e++)actual+=merged[v*E+e]*c.x->data[t*E+e];
  for(int k=0;k<2;k++){float ax=0;for(int e=0;e<E;e++)ax+=a.A->data[k*E+e]*c.x->data[t*E+e];expected+=a.scaling*a.B->data[v*2+k]*ax;}
  float error=fabsf(actual-expected);if(error>worst)worst=error;assert(error<1e-6f);
 }
 printf("DPO shared A/B finite difference:16/16 max_error=%g max_gradient=%g; merged head logits max_error=%g\n",max_error,max_grad,worst);
 return 0;
}
