#include "logit_io.h"
#include "llama.h"
int main(int argc,char **argv) {
    if(argc!=4)fail("usage: dump-llama MODEL.gguf IDS.txt NEW_DUMP.bin");
    int n;int *ids=load_ids(argv[2],&n);
    llama_backend_init();
    auto mp=llama_model_default_params();mp.n_gpu_layers=0;mp.use_extra_bufts=false;mp.load_mode=LLAMA_LOAD_MODE_MMAP;
    llama_model *model=llama_model_load_from_file(argv[1],mp);if(!model)fail("reference model load failed");
    int vocab=llama_vocab_n_tokens(llama_model_get_vocab(model));if(vocab!=151936)fail("unexpected vocabulary");
    auto cp=llama_context_default_params();cp.n_ctx=2048;cp.n_batch=32;cp.n_ubatch=32;cp.n_seq_max=1;
    cp.n_threads=1;cp.n_threads_batch=1;cp.flash_attn_type=LLAMA_FLASH_ATTN_TYPE_DISABLED;
    cp.type_k=GGML_TYPE_F32;cp.type_v=GGML_TYPE_F32;cp.no_perf=true;cp.offload_kqv=false;cp.op_offload=false;
    llama_context *ctx=llama_init_from_model(model,cp);if(!ctx)fail("reference context creation failed");
    llama_batch batch=llama_batch_init(32,0,1);
    FILE *out=start_dump(argv[3],vocab,n,ids);
    for(int pos=0;pos<n;) {
        int end=pos<444?444:447,chunk=end-pos;if(chunk>32)chunk=32;
        batch.n_tokens=chunk;
        for(int i=0;i<chunk;i++) {batch.token[i]=ids[pos+i];batch.pos[i]=pos+i;batch.n_seq_id[i]=1;batch.seq_id[i][0]=0;batch.logits[i]=(pos+i==443||pos+i==446);}
        if(llama_decode(ctx,batch))fail("reference decode failed");
        pos+=chunk;
        if(pos==444||pos==447) {const float *logits=llama_get_logits_ith(ctx,-1);if(!logits)fail("missing reference logits");dump_row(out,pos,logits,vocab);}
    }
    if(fclose(out))fail("dump close failed");
    printf("{\"engine\":\"llama.cpp\",\"vocabulary\":%d,\"positions\":[444,447],\"kv\":\"F32\",\"flash_attention\":false,\"repacking\":false,\"threads\":1,\"prefill_chunk\":32}\n",vocab);
    llama_batch_free(batch);llama_free(ctx);llama_model_free(model);llama_backend_free();free(ids);return 0;
}
