#include "logit_io.h"
#include "harness/arch_models.h"
int main(int argc,char **argv) {
    if(argc!=4)fail("usage: dump-notorch MODEL.gguf IDS.txt NEW_DUMP.bin");
    if(!getenv("NT_NO_I8")||strcmp(getenv("NT_NO_I8"),"1"))fail("NT_NO_I8=1 required");
    int n;int *ids=load_ids(argv[2],&n);
    gguf_file *gf=gguf_open(argv[1]);if(!gf||strcmp(gf->arch,"qwen2"))fail("expected qwen2 GGUF");
    nt_dims dims={0};const nt_arch *arch=&nt_arch_llama;
    void *model=arch->load(gf,&dims);if(!model||dims.vocab!=151936)fail("unexpected model/vocabulary");
    kv_cache *kv=kv_new(dims.n_layers,2048,dims.kv_dim);
    float *logits=(float*)malloc((size_t)dims.vocab*sizeof(float));if(!kv||!kv->k||!kv->v||!logits)fail("allocation failed");
    FILE *out=start_dump(argv[3],dims.vocab,n,ids);
    for(int pos=0;pos<444;) {
        int chunk=444-pos;if(chunk>32)chunk=32;
        if(arch->forward(model,kv,ids+pos,chunk,pos,pos+chunk==444?logits:NULL)!=NT_OK)fail("native prefill failed");
        pos+=chunk;
    }
    dump_row(out,444,logits,dims.vocab);
    if(arch->forward(model,kv,ids+444,3,444,logits)!=NT_OK)fail("native prefix failed");
    dump_row(out,447,logits,dims.vocab);
    if(fclose(out))fail("dump close failed");
    printf("{\"engine\":\"notorch\",\"vocabulary\":%d,\"positions\":[444,447],\"NT_NO_I8\":\"1\",\"prefill_chunk\":32}\n",dims.vocab);
    free(logits);free(ids);kv_free(kv);arch->free(model);gguf_close(gf);return 0;
}
