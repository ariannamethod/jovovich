/* Read saved last-MLP adapters and invoke the unchanged native snapshot path.
 * This executable never tokenizes data, computes a gradient or updates weights. */
#define main mlp_training_main
#include "train_mlp.c"
#undef main

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s BASE.gguf SAVED_PREFIX OUTPUT_PREFIX\n", argv[0]);
        return 2;
    }
    gguf_file *gf = gguf_open(argv[1]);
    if (!gf || strcmp(gf->arch, "qwen2")) mlp_die("expected qwen2 base");
    nt_dims dims;
    llama_model *model = nt_arch_llama.load(gf, &dims);
    if (!model) mlp_die("cannot load native model");
    mlp_bank bank = {0};
    bank_init(&bank, model);
    const char *parts[] = {"gate", "up", "down"};
    for (int i = 0; i < 3; i++) {
        char file[4096], name[128];
        if (snprintf(file, sizeof(file), "%s.%s.lora", argv[2], parts[i]) >= (int)sizeof(file))
            mlp_die("saved adapter path too long");
        snprintf(name, sizeof(name), "blk.%d.ffn_%s.weight", bank.layer, parts[i]);
        const char *names[] = {name};
        if (nt_lora_load(&bank.adapters[i], 1, 1, names, file))
            mlp_die("cannot load saved adapter");
    }
    snapshot(&bank, argv[3]);
    for (int i = 0; i < 3; i++) nt_lora_free(&bank.adapters[i]);
    nt_tensor_free(bank.wg); nt_tensor_free(bank.wu); nt_tensor_free(bank.wd);
    nt_tensor_free(bank.head); nt_tensor_free(bank.norm); nt_tensor_free(bank.ffn_norm);
    nt_tensor_free(bank.bias);
    nt_arch_llama.free(model); gguf_close(gf);
    return 0;
}
