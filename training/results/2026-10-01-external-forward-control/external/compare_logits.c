/* No model arithmetic: summarize two complete, identically indexed native dumps. */
#include "logit_io.h"
static uint32_t get_u32(FILE *in) {uint32_t n;if(fread(&n,4,1,in)!=1)fail("truncated dump");return n;}
static float *read_row(FILE *in,int vocab,uint32_t expected) {
    if(get_u32(in)!=expected)fail("capture position mismatch");
    float *v=(float*)malloc((size_t)vocab*4);if(!v||fread(v,4,(size_t)vocab,in)!=(size_t)vocab)fail("truncated logits");
    for(int i=0;i<vocab;i++)if(!isfinite(v[i]))fail("nonfinite dump");return v;
}
static void top_ids(const float *v,int n,int top[10]) {
    for(int k=0;k<10;k++){top[k]=-1;for(int i=0;i<n;i++) {
        int used=0;for(int j=0;j<k;j++)used|=top[j]==i;
        if(!used&&(top[k]<0||v[i]>v[top[k]]))top[k]=i;
    }}
}
static void print_top(const float *v,const int top[10]) {
    putchar('[');for(int k=0;k<10;k++)printf("%s{\"id\":%d,\"logit\":%.9g}",k?",":"",top[k],v[top[k]]);putchar(']');
}
int main(int argc,char **argv) {
    if(argc!=3)fail("usage: compare-logits NOTORCH.dump LLAMA.dump");
    FILE *a=fopen(argv[1],"rb"),*b=fopen(argv[2],"rb");if(!a||!b)fail("cannot open dumps");
    const uint32_t expected[]={0x324c564a,2,1,151936,2,447};
    for(int i=0;i<6;i++)if(get_u32(a)!=expected[i]||get_u32(b)!=expected[i])fail("dump header mismatch");
    for(int i=0;i<447;i++)if(get_u32(a)!=get_u32(b))fail("different input token IDs");
    const int n=151936;
    for(int row=0;row<2;row++) {
        uint32_t pos=row?447:444;float *x=read_row(a,n,pos),*y=read_row(b,n,pos);
        double err2=0,ref2=0,sumabs=0,maxabs=0,maxref=0;int changed=0,maxid=0;
        for(int i=0;i<n;i++) {double d=(double)x[i]-y[i],ad=fabs(d);err2+=d*d;ref2+=(double)y[i]*y[i];sumabs+=ad;
            if(ad>maxabs){maxabs=ad;maxid=i;}if(fabs(y[i])>maxref)maxref=fabs(y[i]);changed+=memcmp(x+i,y+i,4)!=0;}
        int tx[10],ty[10];top_ids(x,n,tx);top_ids(y,n,ty);
        double relative=sqrt(err2/fmax(ref2,1e-300));
        printf("{\"prefix_tokens\":%u,\"vocabulary\":%d,\"different_float32_values\":%d,\"max_abs\":%.17g,\"max_abs_token_id\":%d,\"reference_max_abs\":%.17g,\"relative_l2\":%.17g,\"rmse\":%.17g,\"mean_abs\":%.17g,",pos,n,changed,maxabs,maxid,maxref,relative,sqrt(err2/n),sumabs/n);
        printf("\"notorch_argmax\":%d,\"llama_argmax\":%d,\"argmax_agree\":%s,\"notorch_top_margin\":%.17g,\"llama_top_margin\":%.17g,",tx[0],ty[0],tx[0]==ty[0]?"true":"false",(double)x[tx[0]]-x[tx[1]],(double)y[ty[0]]-y[ty[1]]);
        printf("\"notorch_concern_minus_clean\":%.17g,\"llama_concern_minus_clean\":%.17g,\"decision_ids\":[66582,788],\"notorch_top10\":",(double)x[66582]-x[788],(double)y[66582]-y[788]);print_top(x,tx);printf(",\"llama_top10\":");print_top(y,ty);printf("}\n");
        free(x);free(y);
    }
    if(fgetc(a)!=EOF||fgetc(b)!=EOF||ferror(a)||ferror(b))fail("trailing dump bytes");
    if(fclose(a)||fclose(b)||fflush(stdout))fail("I/O close failed");return 0;
}
