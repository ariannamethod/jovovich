/* Observe the real trainer call sites; all updates use native Chuck unchanged. */
#include "notorch.h"
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint64_t audit_hash(uint64_t h,const void *value,size_t n) {
    const unsigned char *p=value;
    for(size_t i=0;i<n;i++){h^=p[i];h*=UINT64_C(1099511628211);}
    return h;
}
static uint64_t audit_state(nt_tape *t) {
    uint64_t h=UINT64_C(14695981039346656037);
    h=audit_hash(h,&t->chuck,sizeof(t->chuck));
    for(int i=0;i<t->n_params;i++) {
        h=audit_hash(h,&t->chuck_params[i],sizeof(t->chuck_params[i]));
        h=audit_hash(h,&t->adam[i].t,sizeof(t->adam[i].t));
        h=audit_hash(h,t->adam[i].m->data,(size_t)t->adam[i].m->len*sizeof(float));
        h=audit_hash(h,t->adam[i].v->data,(size_t)t->adam[i].v->len*sizeof(float));
    }
    return h;
}
static void audited_chuck_step(float lr,float loss) {
    static uint64_t prior;
    static int calls,resets;
    nt_tape *t=nt_tape_get();
    assert(isfinite(lr)&&lr>0&&isfinite(loss)&&loss>=0);
    int before=t->chuck.global_step;
    if(calls&&before)assert(audit_state(t)==prior);
    if(calls&&!before)resets++;
    double previous=0;
    for(int i=0;i<t->count;i++)if(t->entries[i].is_param&&t->entries[i].slot>=0)
        for(int k=0;k<t->entries[i].output->len;k++)previous+=t->entries[i].output->data[k];
    nt_tape_chuck_step(lr,loss);
    assert(t->chuck.global_step==before+1&&t->chuck.initialized);
    int frozen=0;double current=0;
    for(int i=0;i<t->n_params;i++)frozen+=!!t->chuck_params[i].frozen;
    for(int i=0;i<t->count;i++)if(t->entries[i].is_param&&t->entries[i].slot>=0)
        for(int k=0;k<t->entries[i].output->len;k++) {
            float value=t->entries[i].output->data[k];assert(isfinite(value));current+=value;
        }
    calls++;prior=audit_state(t);
    fprintf(stderr,"CHUCK_AUDIT {\"call\":%d,\"step_before\":%d,\"step_after\":%d,\"resets\":%d,\"slots\":%d,\"frozen_slots\":%d,\"loss\":%.9g,\"lr\":%.9g,\"dampen\":%.9g,\"noise\":%.9g,\"parameter_sum_delta\":%.17g}\n",calls,before,t->chuck.global_step,resets,t->n_params,frozen,loss,lr,t->chuck.dampen,t->chuck.noise,current-previous);
}
