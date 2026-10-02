#ifndef JOVOVICH_LOGIT_IO_H
#define JOVOVICH_LOGIT_IO_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <errno.h>
#include <string.h>
static void fail(const char *message) { fprintf(stderr,"external-parity: %s\n",message); exit(1); }
static void put_u32(FILE *out, uint32_t n) { if(fwrite(&n,4,1,out)!=1)fail("write failed"); }
static int *load_ids(const char *path,int *count) {
    FILE *in=fopen(path,"r");if(!in)fail("cannot open ID file");
    int *ids=(int*)malloc(2048*sizeof(int)),n=0,x; if(!ids)fail("allocation failed");
    while(fscanf(in,"%d",&x)==1) { if(n==2048||x<0||x>=151936)fail("invalid token ID");ids[n++]=x; }
    if(!feof(in)||ferror(in)||fclose(in))fail("invalid ID file");
    if(n!=447||ids[n-3]!=4913||ids[n-2]!=3903||ids[n-1]!=819)fail("unexpected fixed pair/prefix length");
    *count=n;return ids;
}
static FILE *start_dump(const char *path,int vocab,int tokens,const int *ids) {
    uint32_t check=1; if(*(unsigned char*)&check!=1||sizeof(float)!=4)fail("requires little-endian float32");
    FILE *out=fopen(path,"wbx");if(!out)fail("dump exists or cannot be created");
    put_u32(out,0x324c564a);put_u32(out,2);put_u32(out,1);put_u32(out,(uint32_t)vocab);put_u32(out,2);put_u32(out,(uint32_t)tokens);
    for(int i=0;i<tokens;i++)put_u32(out,(uint32_t)ids[i]);
    return out;
}
static void dump_row(FILE *out,int prefix_len,const float *logits,int vocab) {
    for(int i=0;i<vocab;i++)if(!isfinite(logits[i]))fail("nonfinite logit");
    put_u32(out,(uint32_t)prefix_len);
    if(fwrite(logits,4,(size_t)vocab,out)!=(size_t)vocab||fflush(out))fail("logit write failed");
}
#endif
