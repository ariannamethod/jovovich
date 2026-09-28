/* Export a saved output-head adapter through the exact trainer merge path. */
#define main jovovich_training_main
#include "train_head.c"
#undef main
int main(int argc,char **argv) {
    if(argc!=4) {
        fprintf(stderr,"usage: %s BASE.gguf ADAPTER.lora OUTPUT_PREFIX\n",argv[0]);
        return 2;
    }
    gguf_file *gf=gguf_open(argv[1]);
    if(!gf || strcmp(gf->arch,"qwen2")) die("expected qwen2 GGUF");
    nt_dims dims;
    llama_model *m=nt_arch_llama.load(gf,&dims);
    if(!m) die("could not load Qwen body");
    nt_lora_pair a;
    if(nt_lora_init(&a,m->embed,m->vocab,RANK,2*RANK)) die("adapter allocation failed");
    const char *names[]={"output.weight"};
    if(nt_lora_load(&a,1,1,names,argv[2])) die("could not load output-head adapter");
    sequence probe={0}; probe.x=nt_tensor_new2d(1,m->embed);
    if(!probe.x) die("probe allocation failed");
    for(int i=0;i<m->embed;i++) probe.x->data[i]=(float)((i%17)-8)/17;
    write_merged_head(m,&a,argv[3],&probe);
    nt_tensor_free(probe.x); nt_lora_free(&a); nt_arch_llama.free(m); gguf_close(gf);
    return 0;
}
