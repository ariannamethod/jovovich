// Optional conversion only; never called by the original-Q8 execution plan.
#include "llama.h"
#include <cstdio>
#include <fcntl.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if(argc!=3) {std::fprintf(stderr,"usage: convert-f32 SOURCE.gguf NEW-F32.gguf\n");return 2;}
    int fd=open(argv[2],O_WRONLY|O_CREAT|O_EXCL,0600);
    if(fd<0) {std::perror("reserve new F32 export");return 1;}
    if(close(fd))return 1;
    llama_backend_init();
    auto params=llama_model_quantize_default_params();
    params.nthread=1;params.ftype=LLAMA_FTYPE_ALL_F32;params.allow_requantize=true;
    params.quantize_output_tensor=true;params.output_tensor_type=GGML_TYPE_F32;params.token_embedding_type=GGML_TYPE_F32;
    params.only_copy=false;params.pure=true;params.keep_split=false;params.dry_run=false;
    params.max_buf_size=64*1024*1024;
    auto result=llama_model_quantize(argv[1],argv[2],&params);
    llama_backend_free();
    if(result) {std::fprintf(stderr,"F32 conversion failed; partial export retained\n");return 1;}
    std::puts("{\"conversion\":\"original_Q8_to_F32\",\"engine\":\"llama.cpp\",\"threads\":1,\"model_forwards\":0}");
    return 0;
}
