/* Last-decoder-MLP LoRA SFT. All numerical work uses native notorch C.
 * Frozen: embeddings, attention, preceding blocks, norms and output head.
 * The last MLP cannot affect any attention cache. Temporarily zeroing its
 * down projection exposes its exact post-attention input through the existing
 * post-layer hook; the original projection and bias are restored after capture.
 * Cached gate/up base products are constant, but gradients pass through the
 * adapted SwiGLU, down projection, final norm and frozen vocabulary projection.
 */
#include "harness/arch_models.h"
#include "examples/bpe.h"
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MLP_MAX_TOKENS 4096
#define MLP_RANK 16
#define MLP_SEED 20260929

typedef struct { nt_tensor *z, *xn, *gate, *up, *targets, *bias, *weights; int n; } mlp_batch;
typedef struct {
    char *system, *prompt, *answer; mlp_batch cache; int *ids, n_ids, start;
    int decision_pair, decision_position, decision_alternative_id, decision_correct, decision_predicted_id, prefix_correct;
    float decision_margin;
} mlp_example;
typedef struct {
    int E, F, V, layer, example_weighting, verdict_weighting, pair_count;
    double average_tokens, verdict_weight;
    nt_tensor *wg, *wu, *wd, *head, *norm, *ffn_norm, *bias;
    nt_lora_pair adapters[3];
} mlp_bank;
typedef struct { int example, token; } token_row;
typedef struct { int layer, start; nt_tensor *out; } mlp_capture;

static void mlp_die(const char *s) { fprintf(stderr,"train-mlp: %s\n",s); exit(1); }
static int checked(int i) { if(i<0)mlp_die("tape operation failed"); return i; }
static nt_tensor *tensor(int rows,int cols) {
    nt_tensor *t=nt_tensor_new2d(rows,cols);if(!t)mlp_die("tensor allocation failed");return t;
}
static uint32_t mlp_u32(FILE *f) {
    unsigned char b[4];if(fread(b,1,4,f)!=4)mlp_die("truncated dataset");
    return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;
}
static char *mlp_text(FILE *f) {
    uint32_t n=mlp_u32(f);if(n>1<<20)mlp_die("dataset field exceeds 1 MiB");
    char *s=calloc((size_t)n+1,1);if(!s||fread(s,1,n,f)!=n)mlp_die("cannot read dataset field");
    if(memchr(s,0,n))mlp_die("NUL in dataset text");
    return s;
}
static mlp_example *mlp_data(const char *path,int *count) {
    FILE *f=fopen(path,"rb");unsigned char magic[8];
    if(!f||fread(magic,1,8,f)!=8||memcmp(magic,"JVDS\1\0\0\0",8))mlp_die("invalid JVDS dataset");
    uint32_t n=mlp_u32(f);if(n<1||n>10000)mlp_die("invalid example count");*count=(int)n;
    mlp_example *rows=calloc(n,sizeof(*rows));if(!rows)mlp_die("dataset allocation failed");
    for(int i=0;i<*count;i++) {
        if(mlp_u32(f)!=0)mlp_die("SFT-only trainer refuses DPO rows; prepare an SFT dataset");
        rows[i].system=mlp_text(f);rows[i].prompt=mlp_text(f);rows[i].answer=mlp_text(f);
        char *rejected=mlp_text(f);if(*rejected)mlp_die("SFT row has a rejected completion");free(rejected);
        if(!*rows[i].answer)mlp_die("empty completion");
    }
    if(fgetc(f)!=EOF)mlp_die("trailing dataset bytes");
    fclose(f);return rows;
}
static int mlp_encode(bpe_tokenizer *tok,int *ids,int n,const char *s) {
    int k=bpe_encode_raw(tok,s,ids+n,MLP_MAX_TOKENS-n);
    if(k<0||n+k>=MLP_MAX_TOKENS-2)mlp_die("example exceeds token capacity; no truncation");
    return n+k;
}
static int mlp_role(bpe_tokenizer *tok,int *ids,int n,int begin,const char *role,const char *s,int end) {
    ids[n++]=begin;n=mlp_encode(tok,ids,n,role);n=mlp_encode(tok,ids,n,"\n");
    n=mlp_encode(tok,ids,n,s);ids[n++]=end;return mlp_encode(tok,ids,n,"\n");
}
static void tokenize(mlp_example *e,bpe_tokenizer *tok) {
    int begin=bpe_token_id(tok,"<|im_start|>"),end=bpe_token_id(tok,"<|im_end|>");
    if(begin<0||end<0)mlp_die("missing ChatML tokens");
    e->ids=malloc(MLP_MAX_TOKENS*sizeof(int));if(!e->ids)mlp_die("token allocation failed");
    int n=mlp_role(tok,e->ids,0,begin,"system",e->system,end);
    n=mlp_role(tok,e->ids,n,begin,"user",e->prompt,end);
    e->ids[n++]=begin;n=mlp_encode(tok,e->ids,n,"assistant\n");int prompt=n;
    n=mlp_encode(tok,e->ids,n,e->answer);e->ids[n++]=end;
    e->n_ids=n;e->start=prompt-1;e->cache.n=n-prompt;
    e->cache.targets=tensor(e->cache.n,1);
    for(int t=0;t<e->cache.n;t++)e->cache.targets->data[t]=(float)e->ids[prompt+t];
}
static void load_pairs(mlp_bank *b,mlp_example *rows,int count,const char *path) {
    FILE *f=fopen(path,"rb");unsigned char magic[8];
    if(!f||fread(magic,1,8,f)!=8||memcmp(magic,"JVPR\1\0\0\0",8))mlp_die("invalid JVPR pair map");
    if(mlp_u32(f)!=(uint32_t)count)mlp_die("pair map dataset row count disagrees");
    uint32_t pairs=mlp_u32(f);if(!pairs||pairs>(uint32_t)count/2)mlp_die("invalid pair count");
    for(int i=0;i<count;i++)rows[i].decision_pair=0;
    double mass=0;
    for(uint32_t i=0;i<pairs;i++) {
        uint32_t a=mlp_u32(f),c=mlp_u32(f);
        if(a>=(uint32_t)count||c>=(uint32_t)count||a==c)mlp_die("invalid pair row indices");
        mlp_example *left=&rows[a],*right=&rows[c];
        if(left->decision_pair||right->decision_pair)mlp_die("duplicate pair row");
        int limit=left->cache.n<right->cache.n?left->cache.n:right->cache.n,p=0;
        /* Terminal EOS is not a verdict. Reject identical or prefix-only
         * completions instead of manufacturing a decision at their ending. */
        limit--;
        while(p<limit&&left->cache.targets->data[p]==right->cache.targets->data[p])p++;
        if(p>=limit)mlp_die("pair completions are identical or prefix-only");
        left->decision_pair=right->decision_pair=(int)i+1;
        left->decision_position=right->decision_position=p;
        left->decision_alternative_id=(int)right->cache.targets->data[p];
        right->decision_alternative_id=(int)left->cache.targets->data[p];
        mass+=b->average_tokens/left->cache.n+b->average_tokens/right->cache.n;
    }
    if(fgetc(f)!=EOF||ferror(f))mlp_die("trailing or unreadable pair map bytes");
    fclose(f);b->pair_count=(int)pairs;b->verdict_weight=mass/(2*pairs);
}
static token_row *decision_order(mlp_example *rows,int count,int batch) {
    int n=0;for(int i=0;i<count;i++)if(rows[i].decision_pair)n++;
    if(!n||n>128||batch!=n)mlp_die("decisions requires one full batch of all mapped positions");
    token_row *order=malloc((size_t)n*sizeof(*order));if(!order)mlp_die("decision order allocation failed");
    int p=0;for(int i=0;i<count;i++)if(rows[i].decision_pair) {
        if(rows[i].decision_position<0||rows[i].decision_position>=rows[i].cache.n-1)mlp_die("invalid non-EOS decision position");
        order[p++]=(token_row){i,rows[i].decision_position};
    }
    return order;
}
/* The joint objective partitions every mapped review answer into one decision
 * target and all its remaining targets, including its final EOS. Counts come
 * from the validated tokenized corpus, rather than a particular corpus size. */
static token_row *joint_order(mlp_example *rows,int count,int *decision_count,int *residual_count) {
    if(!rows||count<2||!decision_count||!residual_count)mlp_die("invalid joint corpus");
    int *members=calloc((size_t)count,sizeof(int));if(!members)mlp_die("joint pair allocation failed");
    int decisions=0,total=0;
    for(int i=0;i<count;i++) {
        mlp_example *e=&rows[i];
        if(e->decision_pair<0||e->decision_pair>count/2)mlp_die("invalid joint pair index");
        if(!e->decision_pair)continue;
        if(e->cache.n<2||e->decision_position<0||e->decision_position>=e->cache.n-1)
            mlp_die("invalid non-EOS joint decision position");
        if(total>INT_MAX-e->cache.n)mlp_die("too many joint targets");
        members[e->decision_pair-1]++;decisions++;total+=e->cache.n;
    }
    if(!decisions||decisions%2||total<=decisions)mlp_die("joint requires nonempty decision and residual partitions");
    for(int i=0;i<count;i++)if(members[i]!=(i<decisions/2?2:0))mlp_die("joint requires complete contiguous pairs");
    free(members);
    token_row *order=malloc((size_t)total*sizeof(*order));if(!order)mlp_die("joint order allocation failed");
    int p=0;for(int i=0;i<count;i++)if(rows[i].decision_pair)
        for(int t=0;t<rows[i].cache.n;t++)order[p++]=(token_row){i,t};
    *decision_count=decisions;*residual_count=total-decisions;return order;
}
static float joint_coefficient(const mlp_example *e,int token,int decision_count,int residual_count) {
    if(!e||!e->decision_pair||token<0||token>=e->cache.n||decision_count<1||residual_count<1)
        mlp_die("invalid joint coefficient request");
    return 1.0f/(float)(token==e->decision_position?decision_count:residual_count);
}
static int capture_mlp(void *ctx,int layer,int pos,int n,int width,float *residual) {
    mlp_capture *c=ctx;if(layer!=c->layer)return NT_OK;
    if(width!=c->out->shape[1])return NT_E_ARG;
    for(int t=0;t<n;t++) {
        int row=pos+t-c->start;if(row>=0&&row<c->out->shape[0])
            memcpy(c->out->data+(size_t)row*width,residual+(size_t)t*width,(size_t)width*sizeof(float));
    }
    return NT_OK;
}
static void capture_sequence(llama_model *m,nt_dims dims,const mlp_example *e,nt_tensor *out) {
    kv_cache *kv=kv_new(dims.n_layers,e->n_ids,dims.kv_dim);
    if(!kv||!kv->k||!kv->v)mlp_die("KV allocation failed");
    mlp_capture c={m->n_layers-1,e->start,out};
    for(int pos=0;pos<e->n_ids-1;) {
        int n=e->n_ids-1-pos;if(n>NT_PREFILL_CHUNK)n=NT_PREFILL_CHUNK;
        int rc=nt_arch_llama.forward_residual(m,kv,e->ids+pos,n,pos,NULL,capture_mlp,&c);
        if(rc!=NT_OK)mlp_die(nt_strerror(rc));
        pos+=n;
    }
    kv_free(kv);
}
static nt_tensor *load_matrix(gguf_file *gf,const char *name,int rows,int cols) {
    int ti=gguf_find_tensor(gf,name);
    if(ti<0||gf->tensors[ti].ndim!=2||gf->tensors[ti].shape[0]!=(uint64_t)cols||gf->tensors[ti].shape[1]!=(uint64_t)rows)
        mlp_die("missing or wrongly shaped frozen matrix");
    nt_tensor *w=tensor(rows,cols);free(w->data);w->data=gguf_dequant(gf,ti);
    if(!w->data)mlp_die("matrix dequantization failed");
    return w;
}
static void bank_init(mlp_bank *b,llama_model *m) {
    b->E=m->embed;b->F=m->ffn;b->V=m->vocab;b->layer=m->n_layers-1;char name[128];
    snprintf(name,sizeof(name),"blk.%d.ffn_gate.weight",b->layer);b->wg=load_matrix(m->gf,name,b->F,b->E);
    snprintf(name,sizeof(name),"blk.%d.ffn_up.weight",b->layer);b->wu=load_matrix(m->gf,name,b->F,b->E);
    snprintf(name,sizeof(name),"blk.%d.ffn_down.weight",b->layer);b->wd=load_matrix(m->gf,name,b->E,b->F);
    b->head=load_matrix(m->gf,m->has_output_weight?"output.weight":"token_embd.weight",b->V,b->E);
    b->norm=tensor(1,b->E);b->ffn_norm=tensor(1,b->E);
    memcpy(b->norm->data,m->out_norm,(size_t)b->E*sizeof(float));
    memcpy(b->ffn_norm->data,m->layers[b->layer].ffn_norm,(size_t)b->E*sizeof(float));
    if(m->layers[b->layer].ffn_down_bias) {
        b->bias=tensor(1,b->E);memcpy(b->bias->data,m->layers[b->layer].ffn_down_bias,(size_t)b->E*sizeof(float));
    }
    for(int j=0;j<3;j++)if(nt_lora_init(&b->adapters[j],j==2?b->F:b->E,j==2?b->E:b->F,MLP_RANK,2*MLP_RANK))mlp_die("LoRA allocation failed");
}
static void prepare_cache(mlp_bank *b,mlp_batch *s) {
    s->xn=tensor(s->n,b->E);
    for(int t=0;t<s->n;t++)rmsnorm(s->xn->data+(size_t)t*b->E,s->z->data+(size_t)t*b->E,b->ffn_norm->data,b->E,1e-6f);
    nt_tape_start();int x=checked(nt_tape_param_frozen(s->xn));
    int g=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wg)),x,s->n));
    int u=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wu)),x,s->n));
    s->gate=nt_tensor_ref(nt_tape_get()->entries[g].output);s->up=nt_tensor_ref(nt_tape_get()->entries[u].output);
    nt_tape_clear();
}
static int delta(nt_lora_pair *a,int x,int n,int training,int *indices) {
    int ai=checked(training?nt_tape_param(a->A):nt_tape_param_frozen(a->A));
    int bi=checked(training?nt_tape_param(a->B):nt_tape_param_frozen(a->B));
    if(indices){indices[0]=ai;indices[1]=bi;}
    return checked(nt_scale(checked(nt_seq_linear(bi,checked(nt_seq_linear(ai,x,n)),n)),a->scaling));
}
static int mlp_forward(mlp_bank *b,mlp_batch *s,int training,int *residual,int *logits,int *indices) {
    int x=checked(nt_tape_param_frozen(s->xn)),z=checked(nt_tape_param_frozen(s->z));
    int g=checked(nt_add(checked(nt_tape_param_frozen(s->gate)),delta(&b->adapters[0],x,s->n,training,indices)));
    int u=checked(nt_add(checked(nt_tape_param_frozen(s->up)),delta(&b->adapters[1],x,s->n,training,indices?indices+2:NULL)));
    int h=checked(nt_swiglu(g,u));
    int d=checked(nt_add(checked(nt_seq_linear(checked(nt_tape_param_frozen(b->wd)),h,s->n)),delta(&b->adapters[2],h,s->n,training,indices?indices+4:NULL)));
    int r=checked(nt_add(z,d));if(s->bias)r=checked(nt_add(r,checked(nt_tape_param_frozen(s->bias))));
    int y=checked(nt_seq_rmsnorm(r,checked(nt_tape_param_frozen(b->norm)),s->n,b->E));
    int l=checked(nt_seq_linear(checked(nt_tape_param_frozen(b->head)),y,s->n));
    if(residual)*residual=r;
    if(logits)*logits=l;
    if(training&&s->weights) {
        float sum=0;for(int t=0;t<s->n;t++)sum+=s->weights->data[t];
        int ce=checked(nt_seq_cross_entropy_masked(l,checked(nt_tape_param_frozen(s->targets)),checked(nt_tape_param_frozen(s->weights)),s->n,b->V));
        /* Undo batch weight normalization: uniform token samples estimate the
         * mean of per-example token means, including the final short batch. */
        return checked(nt_scale(ce,sum/s->n));
    }
    return checked(nt_seq_cross_entropy(l,checked(nt_tape_param_frozen(s->targets)),s->n,b->V));
}
static mlp_batch gather(mlp_bank *b,mlp_example *rows,const token_row *order,int n) {
    mlp_batch s={.n=n};s.z=tensor(n,b->E);s.xn=tensor(n,b->E);s.gate=tensor(n,b->F);s.up=tensor(n,b->F);s.targets=tensor(n,1);
    if(b->bias)s.bias=tensor(n,b->E);
    if(b->example_weighting)s.weights=tensor(n,1);
    for(int t=0;t<n;t++) {
        mlp_batch *c=&rows[order[t].example].cache;int p=order[t].token;
        memcpy(s.z->data+(size_t)t*b->E,c->z->data+(size_t)p*b->E,(size_t)b->E*sizeof(float));
        memcpy(s.xn->data+(size_t)t*b->E,c->xn->data+(size_t)p*b->E,(size_t)b->E*sizeof(float));
        memcpy(s.gate->data+(size_t)t*b->F,c->gate->data+(size_t)p*b->F,(size_t)b->F*sizeof(float));
        memcpy(s.up->data+(size_t)t*b->F,c->up->data+(size_t)p*b->F,(size_t)b->F*sizeof(float));
        s.targets->data[t]=c->targets->data[p];if(s.bias)memcpy(s.bias->data+(size_t)t*b->E,b->bias->data,(size_t)b->E*sizeof(float));
        if(s.weights) {
            mlp_example *e=&rows[order[t].example];
            s.weights->data[t]=(float)(b->verdict_weighting&&e->decision_pair&&p==e->decision_position?
                                      b->verdict_weight:b->average_tokens/c->n);
        }
    }
    return s;
}
static void batch_free(mlp_batch *s) {
    nt_tensor_free(s->z);nt_tensor_free(s->xn);nt_tensor_free(s->gate);nt_tensor_free(s->up);nt_tensor_free(s->targets);nt_tensor_free(s->bias);nt_tensor_free(s->weights);memset(s,0,sizeof(*s));
}
/* Existing weighted SFT returns sum(weight * CE) / microbatch_size. The
 * globally normalized joint coefficients instead need the unaveraged sum. */
static int joint_loss(mlp_bank *b,mlp_batch *s,double *weighted_loss) {
    if(!s||s->n<1||!s->weights||s->weights->len!=s->n||!weighted_loss)
        mlp_die("joint loss requires globally weighted targets");
    for(int t=0;t<s->n;t++)if(!(s->weights->data[t]>0)||!isfinite(s->weights->data[t]))
        mlp_die("invalid joint target coefficient");
    int loss=checked(nt_scale(mlp_forward(b,s,1,NULL,NULL,NULL),(float)s->n));
    *weighted_loss=nt_tape_get()->entries[loss].output->data[0];
    if(!isfinite(*weighted_loss))mlp_die("nonfinite joint loss");
    return loss;
}
static void joint_slots(mlp_bank *b,int accumulated) {
    nt_tape *tape=nt_tape_get();int seen=0;
    if(tape->n_params!=6)mlp_die("joint requires six persistent adapter slots");
    for(int i=0;i<tape->count;i++) {
        nt_tape_entry *e=&tape->entries[i];if(!e->is_param||e->frozen)continue;
        int s=e->slot;if(s<0||s>=6||(seen&(1<<s)))mlp_die("invalid joint adapter slot");
        nt_tensor *expected=s%2?b->adapters[s/2].B:b->adapters[s/2].A;
        if(e->output!=expected||!e->grad||e->grad->len!=expected->len)
            mlp_die("joint adapter gradient identity changed");
        nt_adam_state *state=&tape->adam[s];
        if(!state->m||!state->v||state->m->len!=expected->len||state->v->len!=expected->len)
            mlp_die("joint optimizer state shape changed");
        if(accumulated&&(!state->acc_grad||state->acc_grad->len!=expected->len))
            mlp_die("joint gradient accumulation failed");
        seen|=1<<s;
    }
    if(seen!=63)mlp_die("joint adapter gradient coverage incomplete");
}
/* The native accumulator survives tape_clear, while each temporary graph and
 * gradient is released. apply_accum(1) restores the sum and clears its buffers;
 * the caller performs the single global clip and Adam step on this final tape. */
static void joint_accumulate(mlp_bank *b,mlp_example *rows,const token_row *order,int total,int batch,
                             int decision_count,int residual_count,double *loss) {
    if(!b||!rows||!order||!loss||batch<1||decision_count<1||residual_count<1||
       decision_count>INT_MAX-residual_count||total!=decision_count+residual_count||
       b->example_weighting||b->verdict_weighting)mlp_die("invalid joint accumulation configuration");
    for(int j=0;j<6;j++) {
        nt_tensor *acc=nt_tape_get()->adam[j].acc_grad;
        if(acc)for(int k=0;k<acc->len;k++)if(acc->data[k]!=0)mlp_die("joint accumulator was not cleared");
    }
    int decisions=0,residuals=0;*loss=0;
    for(int p=0;p<total;p+=batch) {
        int n=total-p;if(n>batch)n=batch;
        mlp_batch s=gather(b,rows,order+p,n);s.weights=tensor(n,1);
        for(int t=0;t<n;t++) {
            const mlp_example *e=&rows[order[p+t].example];int token=order[p+t].token;
            s.weights->data[t]=joint_coefficient(e,token,decision_count,residual_count);
            if(token==e->decision_position)decisions++;else residuals++;
        }
        nt_tape_start();double part;int ce=joint_loss(b,&s,&part);nt_tape_backward(ce);
        joint_slots(b,0);nt_tape_accum_grads();joint_slots(b,1);*loss+=part;
        if(p+n<total)nt_tape_clear();
        batch_free(&s);
    }
    if(decisions!=decision_count||residuals!=residual_count)mlp_die("joint partition coverage disagrees");
    nt_tape_apply_accum(1);joint_slots(b,1);
}
static void zero_probe(mlp_bank *b,llama_model *m,mlp_example *rows,nt_tensor *reference) {
    int n=reference->shape[0];if(n>4)n=4;token_row order[4];for(int t=0;t<n;t++)order[t]=(token_row){0,t};
    mlp_batch s=gather(b,rows,order,n);nt_tape_start();int ri,li;mlp_forward(b,&s,0,&ri,&li,NULL);
    float *actual_r=nt_tape_get()->entries[ri].output->data,*actual_l=nt_tape_get()->entries[li].output->data;
    float *x=malloc((size_t)b->E*sizeof(float)),*ref_l=malloc((size_t)b->V*sizeof(float));if(!x||!ref_l)mlp_die("probe allocation failed");
    float re=0,rs=0,le=0,ls=0;int argmax_equal=1;
    const wt *head=m->has_output_weight?&m->out_weight:&m->tok_emb;
    for(int t=0;t<n;t++) {
        float *ref_r=reference->data+(size_t)t*b->E;
        for(int j=0;j<b->E;j++){re=fmaxf(re,fabsf(actual_r[(size_t)t*b->E+j]-ref_r[j]));rs=fmaxf(rs,fabsf(ref_r[j]));}
        rmsnorm(x,ref_r,m->out_norm,b->E,m->rms_eps);qmv(ref_l,head,x);int ai=0,bi=0;
        for(int j=0;j<b->V;j++) {
            float y=actual_l[(size_t)t*b->V+j];if(!isfinite(y)||!isfinite(ref_l[j]))mlp_die("nonfinite zero-adapter probe");
            le=fmaxf(le,fabsf(y-ref_l[j]));ls=fmaxf(ls,fabsf(ref_l[j]));
            if(y>actual_l[(size_t)t*b->V+ai])ai=j;
            if(ref_l[j]>ref_l[bi])bi=j;
        }
        argmax_equal&=ai==bi;
    }
    fprintf(stderr,"zero-adapter probe rows=%d residual_max_abs=%.8g residual_scale=%.8g logits_max_abs=%.8g logits_scale=%.8g argmax_equal=%d\n",n,re,rs,le,ls,argmax_equal);
    if(re>0.001f*(1+rs)||le>0.001f*(1+ls)||!argmax_equal)mlp_die("zero-adapter reconstruction disagrees with original forward");
    free(x);free(ref_l);nt_tape_clear();batch_free(&s);
}
static void snapshot(mlp_bank *b,const char *prefix) {
    const char *suffixes[]={"gate","up","down"};nt_tensor *base[]={b->wg,b->wu,b->wd};
    for(int j=0;j<3;j++) {
        char path[4096],name[128];snprintf(name,sizeof(name),"blk.%d.ffn_%s.weight",b->layer,suffixes[j]);const char *names[]={name};
        if(snprintf(path,sizeof(path),"%s.%s.lora",prefix,suffixes[j])>=(int)sizeof(path))mlp_die("snapshot path too long");
        if(access(path,F_OK)==0)mlp_die("snapshot exists; use a new output prefix");
        if(nt_lora_save(&b->adapters[j],1,1,names,path))mlp_die("adapter save failed");
        nt_tensor *merged=nt_tensor_clone(base[j]);if(!merged)mlp_die("merge allocation failed");
        nt_lora_pair *a=&b->adapters[j];nt_lora_merge_into(merged->data,base[j]->data,a,a->in_dim,a->out_dim);
        /* Check the merge through an independent matvec composition. */
        float *x=malloc((size_t)a->in_dim*sizeof(float)),*lo=malloc((size_t)a->rank*sizeof(float));
        float *old=malloc((size_t)a->out_dim*sizeof(float)),*change=malloc((size_t)a->out_dim*sizeof(float)),*out=malloc((size_t)a->out_dim*sizeof(float));
        if(!x||!lo||!old||!change||!out)mlp_die("merge probe allocation failed");
        for(int k=0;k<a->in_dim;k++)x[k]=0.01f*(float)((k%19)-9);
        nt_blas_matvec(old,base[j]->data,x,a->out_dim,a->in_dim);nt_blas_matvec(lo,a->A->data,x,a->rank,a->in_dim);
        nt_blas_matvec(change,a->B->data,lo,a->out_dim,a->rank);nt_blas_matvec(out,merged->data,x,a->out_dim,a->in_dim);
        float err=0,scale=0;for(int k=0;k<a->out_dim;k++) {
            float want=old[k]+a->scaling*change[k];
            if(!isfinite(want)||!isfinite(out[k]))mlp_die("nonfinite merged projection probe");
            err=fmaxf(err,fabsf(out[k]-want));scale=fmaxf(scale,fabsf(want));
        }
        if(!isfinite(err)||err>0.001f*(1+scale))mlp_die("merged MLP projection failed parity probe");
        for(int k=0;k<merged->len;k++)if(!isfinite(merged->data[k]))mlp_die("nonfinite merged weight");
        if(snprintf(path,sizeof(path),"%s.%s.f32",prefix,suffixes[j])>=(int)sizeof(path))mlp_die("snapshot path too long");
        FILE *f=fopen(path,"wbx");if(!f)mlp_die("cannot create merged tensor (path may exist)");
        if(fwrite(merged->data,sizeof(float),(size_t)merged->len,f)!=(size_t)merged->len||fclose(f))mlp_die("merged tensor write failed");
        fprintf(stderr,"saved %s merge_max_abs=%.8g\n",path,err);
        free(x);free(lo);free(old);free(change);free(out);nt_tensor_free(merged);
    }
}
static void epoch_snapshot(mlp_bank *b,const char *prefix,int epoch) {
    char path[4000];if(snprintf(path,sizeof(path),"%s.epoch%02d",prefix,epoch)>=(int)sizeof(path))mlp_die("output prefix too long");
    snapshot(b,path);
}
static double decision_ce(mlp_bank *b,mlp_example *rows,const token_row *order,int n,int *correct,int *exact_pairs) {
    int *hits=calloc((size_t)b->pair_count,sizeof(int));if(!hits)mlp_die("decision score allocation failed");
    mlp_batch s=gather(b,rows,order,n);nt_tape_start();int li;
    int ce=mlp_forward(b,&s,0,NULL,&li,NULL);float value=nt_tape_get()->entries[ce].output->data[0];
    if(!isfinite(value))mlp_die("nonfinite decision evaluation loss");
    float *logits=nt_tape_get()->entries[li].output->data;*correct=0;*exact_pairs=0;
    for(int t=0;t<n;t++) {
        mlp_example *e=&rows[order[t].example];float *l=logits+(size_t)t*b->V;int predicted=0,target=(int)s.targets->data[t];
        for(int j=1;j<b->V;j++)if(l[j]>l[predicted])predicted=j;
        e->decision_predicted_id=predicted;e->decision_correct=predicted==target;
        e->decision_margin=l[target]-l[e->decision_alternative_id];
        *correct+=e->decision_correct;hits[e->decision_pair-1]+=e->decision_correct;
    }
    for(int p=0;p<b->pair_count;p++)*exact_pairs+=hits[p]==2;
    free(hits);nt_tape_clear();batch_free(&s);return value;
}
static void print_decision_rows(mlp_example *rows,const token_row *order,int n) {
    printf(",\"decision_rows\":[");
    for(int t=0;t<n;t++) {
        mlp_example *e=&rows[order[t].example];
        printf("%s{\"row\":%d,\"pair_index\":%d,\"decision_position\":%d,\"decision_target_id\":%d,\"decision_alternative_id\":%d,\"decision_predicted_id\":%d,\"decision_correct\":%s,\"decision_margin\":%.9g}",t?",":"",order[t].example,e->decision_pair-1,order[t].token,(int)e->cache.targets->data[order[t].token],e->decision_alternative_id,e->decision_predicted_id,e->decision_correct?"true":"false",e->decision_margin);
    }
    puts("]}");fflush(stdout);
}
static void print_decision_scores(mlp_bank *b,mlp_example *rows,const token_row *order,int n,int epoch,int saved) {
    int correct,exact_pairs;double ce=decision_ce(b,rows,order,n,&correct,&exact_pairs);
    printf("{\"stage\":\"decision_train\",\"epoch\":%d,\"update\":%d,\"measurement\":\"%s\",\"snapshot_saved\":%s,\"mean_decision_ce\":%.8f,\"decision_positions\":%d,\"decision_correct\":%d,\"decision_pairs\":%d,\"decision_pairs_exact\":%d",epoch,epoch,epoch?"post_update":"initial",saved?"true":"false",ce,n,correct,b->pair_count,exact_pairs);
    print_decision_rows(rows,order,n);
}
static void print_joint_scores(mlp_bank *b,mlp_example *rows,const token_row *decisions,int decision_count,
                               const token_row *order,int total,int batch,int epoch,int saved,
                               double online_loss,float gradient_norm) {
    int residual_count=total-decision_count;
    token_row *residual=malloc((size_t)residual_count*sizeof(*residual));if(!residual)mlp_die("residual readout allocation failed");
    int k=0;for(int t=0;t<total;t++)if(order[t].token!=rows[order[t].example].decision_position) {
        if(k>=residual_count)mlp_die("residual readout exceeds partition");
        residual[k++]=order[t];
    }
    if(k!=residual_count)mlp_die("residual readout misses partition");
    double residual_ce=0;
    for(int p=0;p<residual_count;p+=batch) {
        int n=residual_count-p;if(n>batch)n=batch;mlp_batch s=gather(b,rows,residual+p,n);
        nt_tape_start();int ce=mlp_forward(b,&s,0,NULL,NULL,NULL);
        double value=nt_tape_get()->entries[ce].output->data[0];if(!isfinite(value))mlp_die("nonfinite residual readout");
        residual_ce+=n*value;nt_tape_clear();batch_free(&s);
    }
    free(residual);residual_ce/=residual_count;
    int correct,exact_pairs;double decision_loss=decision_ce(b,rows,decisions,decision_count,&correct,&exact_pairs);
    printf("{\"stage\":\"decision_train\",\"epoch\":%d,\"update\":%d,\"measurement\":\"%s\",\"snapshot_saved\":%s,\"mean_decision_ce\":%.8f,\"decision_positions\":%d,\"decision_correct\":%d,\"decision_pairs\":%d,\"decision_pairs_exact\":%d,\"mean_residual_ce\":%.8f,\"mean_joint_ce\":%.8f,\"residual_positions\":%d,\"joint_positions\":%d,\"residual_lambda\":1",epoch,epoch,epoch?"post_update":"initial",saved?"true":"false",decision_loss,decision_count,correct,b->pair_count,exact_pairs,residual_ce,decision_loss+residual_ce,residual_count,total);
    if(epoch)printf(",\"gradient_norm\":%.9g,\"clip_scale\":%.9g,\"clipped\":%s,\"gradient_measurement\":\"pre_update\",\"online_joint_ce\":%.8f",gradient_norm,gradient_norm>1?1.0f/(gradient_norm+1e-6f):1.0f,gradient_norm>1?"true":"false",online_loss);
    else printf(",\"gradient_norm\":null,\"clip_scale\":null,\"clipped\":null,\"gradient_measurement\":null,\"online_joint_ce\":null");
    print_decision_rows(rows,decisions,decision_count);
}
static double mean_ce(mlp_bank *b,mlp_example *rows,token_row *order,int total,int batch,
                      int count,int *correct_tokens,int *exact_examples,int *row_correct,int *first_error) {
    double sum=0;memset(row_correct,0,(size_t)count*sizeof(int));
    for(int i=0;i<count;i++){first_error[i]=-1;rows[i].decision_correct=0;rows[i].decision_margin=0;rows[i].decision_predicted_id=-1;rows[i].prefix_correct=0;}
    *correct_tokens=0;*exact_examples=0;
    for(int p=0;p<total;p+=batch) {
        int n=total-p;if(n>batch)n=batch;mlp_batch s=gather(b,rows,order+p,n);nt_tape_start();
        int li;int ce=mlp_forward(b,&s,0,NULL,&li,NULL);float v=nt_tape_get()->entries[ce].output->data[0];
        if(!isfinite(v))mlp_die("nonfinite evaluation loss");
        float *logits=nt_tape_get()->entries[li].output->data;
        for(int t=0;t<n;t++) {
            float *l=logits+(size_t)t*b->V;int predicted=0;
            for(int j=1;j<b->V;j++)if(l[j]>l[predicted])predicted=j;
            int row=order[p+t].example,pos=order[p+t].token;
            if(predicted==(int)s.targets->data[t]){
                (*correct_tokens)++;row_correct[row]++;
                if(rows[row].decision_pair&&pos<rows[row].decision_position)rows[row].prefix_correct++;
            }
            else if(first_error[row]<0||pos<first_error[row])first_error[row]=pos;
            if(rows[row].decision_pair&&pos==rows[row].decision_position) {
                rows[row].decision_correct=predicted==(int)s.targets->data[t];
                rows[row].decision_predicted_id=predicted;
                rows[row].decision_margin=l[(int)s.targets->data[t]]-l[rows[row].decision_alternative_id];
            }
        }
        sum+=(double)n*v;nt_tape_clear();batch_free(&s);
    }
    for(int i=0;i<count;i++)if(row_correct[i]==rows[i].cache.n)(*exact_examples)++;
    return sum/total;
}
static void print_row_scores(const mlp_example *rows,int count,const int *correct,const int *first_error,int initial,int joint) {
    if(joint) {
        int positions=0,hits=0,exact=0,examples=0;
        for(int i=0;i<count;i++)if(rows[i].decision_pair) {
            positions+=rows[i].decision_position;hits+=rows[i].prefix_correct;
            exact+=rows[i].prefix_correct==rows[i].decision_position;examples++;
        }
        printf(",\"prefix_positions\":%d,\"prefix_correct\":%d,\"prefix_exact_examples\":%d,\"prefix_examples\":%d",positions,hits,exact,examples);
    }
    printf(",\"teacher_forced_rows\":[");
    for(int i=0;i<count;i++) {
        printf("%s{\"row\":%d,\"tokens\":%d,\"correct\":%d,\"first_error_position\":%d",i?",":"",i,rows[i].cache.n,correct[i],first_error[i]);
        if(rows[i].decision_pair) {
            printf(",\"decision_position\":%d,\"decision_correct\":%s,\"decision_margin\":%.9g,\"decision_predicted_id\":%d",rows[i].decision_position,rows[i].decision_correct?"true":"false",rows[i].decision_margin,rows[i].decision_predicted_id);
            if(initial)printf(",\"decision_target_id\":%d,\"decision_alternative_id\":%d",(int)rows[i].cache.targets->data[rows[i].decision_position],rows[i].decision_alternative_id);
            if(joint)printf(",\"prefix_tokens\":%d,\"prefix_correct\":%d,\"prefix_exact\":%s",rows[i].decision_position,rows[i].prefix_correct,rows[i].prefix_correct==rows[i].decision_position?"true":"false");
        }
        printf("}");
    }
    printf("]");
}
static int number(const char *s,int lo,int hi) {
    char *end;errno=0;long n=strtol(s,&end,10);if(errno||end==s||*end||n<lo||n>hi)mlp_die("invalid integer argument");return (int)n;
}
int main(int argc,char **argv) {
    if(argc<4||argc>10){fprintf(stderr,"usage: %s BASE.gguf SFT.bin PREFIX [EPOCHS LR TOKEN_BATCH SAVE_EVERY OBJECTIVE(tokens|examples|verdict|decisions|joint) PAIR_MAP]\n",argv[0]);return 2;}
    int epochs=argc>4?number(argv[4],0,100):3,batch=argc>6?number(argv[6],1,128):16;
    int save_every=argc>7?number(argv[7],0,100):1;
    const char *objective=argc>8?argv[8]:"tokens";
    int decisions=!strcmp(objective,"decisions"),joint=!strcmp(objective,"joint");
    if(strcmp(objective,"tokens")&&strcmp(objective,"examples")&&strcmp(objective,"verdict")&&!decisions&&!joint)mlp_die("objective must be tokens, examples, verdict, decisions or joint");
    if((!strcmp(objective,"verdict")||decisions||joint)&&argc<10)mlp_die("verdict, decisions and joint objectives require a pair map");
    char *end=NULL;float lr=argc>5?strtof(argv[5],&end):0.00005f;if(!(lr>0)||!isfinite(lr)||(end&&(*end||end==argv[5])))mlp_die("invalid learning rate");
    uint16_t endian=1;if(*(unsigned char*)&endian!=1)mlp_die("raw F32 export requires a little-endian host");
    /* The tape differentiates the fixed dequantized matrices, not activation rounding. */
    if(setenv("NT_NO_I8","1",1))mlp_die("cannot set floating activation mode");
    int count;mlp_example *rows=mlp_data(argv[2],&count);gguf_file *gf=gguf_open(argv[1]);if(!gf)mlp_die("cannot open GGUF");
    if(strcmp(gf->arch,"qwen2"))mlp_die("this SFT prototype requires qwen2 (ChatML, no thinking prefix)");
    if(gf->n_layers<1||fabsf(gf->rms_eps-1e-6f)>1e-12f)mlp_die("requires layers and exact model RMSNorm epsilon 1e-6");
    nt_dims dims;llama_model *m=nt_arch_llama.load(gf,&dims);bpe_tokenizer *tok=bpe_load(argv[1]);if(!m||!tok)mlp_die("cannot load model/tokenizer");
    if(!m->layers[m->n_layers-1].ffn_norm)mlp_die("missing final MLP normalization weight");
    nt_seed(MLP_SEED);srand(MLP_SEED);mlp_bank bank={0};bank_init(&bank,m);
    int total=0;for(int i=0;i<count;i++){tokenize(&rows[i],tok);if(rows[i].n_ids>gf->ctx_len)mlp_die("example exceeds model context");if(total>INT_MAX-rows[i].cache.n)mlp_die("too many tokens");total+=rows[i].cache.n;}
    bank.example_weighting=!strcmp(objective,"examples")||!strcmp(objective,"verdict");bank.average_tokens=(double)total/count;
    bank.verdict_weighting=!strcmp(objective,"verdict");if(argc>9)load_pairs(&bank,rows,count,argv[9]);
    /* Validate the full decision batch before capturing any model activations. */
    int joint_decisions=0,joint_residuals=0;
    token_row *joint_targets=joint?joint_order(rows,count,&joint_decisions,&joint_residuals):NULL;
    token_row *selected=(decisions||joint)?decision_order(rows,count,joint?joint_decisions:batch):NULL;
    nt_tensor *reference=tensor(rows[0].cache.n,m->embed);capture_sequence(m,dims,&rows[0],reference);
    int last=m->n_layers-1;wt original=m->layers[last].wdown;float *bias=m->layers[last].ffn_down_bias;
    float *zero=calloc((size_t)m->embed*m->ffn,sizeof(float));if(!zero)mlp_die("zero projection allocation failed");
    m->layers[last].wdown=(wt){.f32=zero,.dtype=0,.rows=m->embed,.cols=m->ffn};m->layers[last].ffn_down_bias=NULL;
    double started=now_ms();
    for(int i=0;i<count;i++) {
        rows[i].cache.z=tensor(rows[i].cache.n,m->embed);capture_sequence(m,dims,&rows[i],rows[i].cache.z);prepare_cache(&bank,&rows[i].cache);
        fprintf(stderr,"cache %d/%d tokens=%d elapsed=%.1fs\n",i+1,count,rows[i].cache.n,(now_ms()-started)/1000);
    }
    m->layers[last].wdown=original;m->layers[last].ffn_down_bias=bias;free(zero);
    zero_probe(&bank,m,rows,reference);nt_tensor_free(reference);
    token_row *order=malloc((size_t)total*sizeof(*order));if(!order)mlp_die("shuffle allocation failed");int p=0;
    for(int i=0;i<count;i++)for(int t=0;t<rows[i].cache.n;t++)order[p++]=(token_row){i,t};
    token_row *train_order=joint?joint_targets:decisions?selected:order;
    int train_total=joint?joint_decisions+joint_residuals:decisions?batch:total;
    long params=0;for(int j=0;j<3;j++)params+=bank.adapters[j].A->len+bank.adapters[j].B->len;
    int correct_tokens,exact_examples,*row_correct=calloc((size_t)count,sizeof(int)),*first_error=malloc((size_t)count*sizeof(int));if(!row_correct||!first_error)mlp_die("score allocation failed");
    double initial=mean_ce(&bank,rows,order,total,batch,count,&correct_tokens,&exact_examples,row_correct,first_error);
    printf("{\"stage\":\"sft_initial\",\"objective\":\"%s\",\"mean_token_ce\":%.8f,\"examples\":%d,\"tokens\":%d,\"rank\":16,\"alpha\":32,\"layer\":%d,\"trainable_parameters\":%ld,\"seed\":%d,\"teacher_forced_correct_tokens\":%d,\"teacher_forced_exact_examples\":%d",objective,initial,count,total,last,params,MLP_SEED,correct_tokens,exact_examples);
    if(bank.pair_count)printf(",\"decision_pairs\":%d,\"verdict_weight\":%.9g",bank.pair_count,bank.verdict_weight);
    if(joint)printf(",\"decision_positions\":%d,\"residual_positions\":%d,\"joint_positions\":%d,\"residual_lambda\":1,\"clip_limit\":1,\"microbatch_tokens\":%d",joint_decisions,joint_residuals,train_total,batch);
    print_row_scores(rows,count,row_correct,first_error,1,joint);puts("}");fflush(stdout);
    if(decisions)print_decision_scores(&bank,rows,train_order,train_total,0,0);
    if(joint)print_joint_scores(&bank,rows,selected,joint_decisions,train_order,train_total,batch,0,0,0,0);
    for(int ep=1;ep<=epochs;ep++) {
        if(!decisions&&!joint)for(int i=total-1;i>0;i--){int j=rand()%(i+1);token_row tmp=order[i];order[i]=order[j];order[j]=tmp;}
        double sum=0,epoch_start=now_ms();
        float gradient_norm=0;
        if(joint) {
            joint_accumulate(&bank,rows,train_order,train_total,batch,joint_decisions,joint_residuals,&sum);
            gradient_norm=nt_tape_clip_grads(1.0f);if(!isfinite(gradient_norm))mlp_die("nonfinite joint gradients");
            nt_tape_chuck_step(lr,(float)sum);nt_tape_clear();
        } else for(int start=0;start<train_total;start+=batch) {
            int n=train_total-start;if(n>batch)n=batch;mlp_batch s=gather(&bank,rows,train_order+start,n);nt_tape_start();
            int ce=mlp_forward(&bank,&s,1,NULL,NULL,NULL);float loss=nt_tape_get()->entries[ce].output->data[0];if(!isfinite(loss))mlp_die("nonfinite SFT loss");
            nt_tape_backward(ce);float norm=nt_tape_clip_grads(1.0f);if(!isfinite(norm))mlp_die("nonfinite gradients");nt_tape_chuck_step(lr,loss);nt_tape_clear();batch_free(&s);sum+=(double)n*loss;
        }
        int saved=save_every&&(ep%save_every==0||ep==epochs);
        if((decisions||joint)&&saved)epoch_snapshot(&bank,argv[3],ep);
        if(decisions)print_decision_scores(&bank,rows,train_order,train_total,ep,saved);
        if(joint)print_joint_scores(&bank,rows,selected,joint_decisions,train_order,train_total,batch,ep,saved,sum,gradient_norm);
        if((!decisions&&!joint)||saved) {
            double held=mean_ce(&bank,rows,order,total,batch,count,&correct_tokens,&exact_examples,row_correct,first_error);
            printf("{\"stage\":\"sft\",\"epoch\":%d,\"online_mean_objective_ce\":%.8f,\"mean_token_ce\":%.8f,\"teacher_forced_correct_tokens\":%d,\"teacher_forced_exact_examples\":%d,\"seconds\":%.3f",ep,joint?sum:sum/train_total,held,correct_tokens,exact_examples,(now_ms()-epoch_start)/1000);
            print_row_scores(rows,count,row_correct,first_error,0,joint);puts("}");fflush(stdout);
        }
        if(!decisions&&!joint&&saved)epoch_snapshot(&bank,argv[3],ep);
    }
    snapshot(&bank,argv[3]);
    nt_tape_start();for(int j=0;j<3;j++){nt_tape_param(bank.adapters[j].A);nt_tape_param(bank.adapters[j].B);}nt_tape_destroy();
    for(int j=0;j<3;j++)nt_lora_free(&bank.adapters[j]);
    nt_tensor_free(bank.wg);nt_tensor_free(bank.wu);nt_tensor_free(bank.wd);nt_tensor_free(bank.head);nt_tensor_free(bank.norm);nt_tensor_free(bank.ffn_norm);nt_tensor_free(bank.bias);
    for(int i=0;i<count;i++){free(rows[i].system);free(rows[i].prompt);free(rows[i].answer);free(rows[i].ids);batch_free(&rows[i].cache);}free(order);free(selected);free(joint_targets);free(rows);free(row_correct);free(first_error);
    bpe_free(tok);nt_arch_llama.free(m);gguf_close(gf);return 0;
}
