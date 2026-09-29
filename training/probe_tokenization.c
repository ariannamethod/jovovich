/* Compare the actual SFT tokenizer with the actual inference ChatML tokenizer.
 * Usage: jovovich-probe-tokenization BASE.gguf SFT.bin [SFT.bin ...]
 * Check every row twice: prompt alone, then prompt + completion + im_end.
 * file_index is the zero-based position among the SFT.bin arguments.
 * Any differing ID or length is reported in JSONL and causes a nonzero exit.
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main
#define main inference_main
#include "../src/infer.c"
#undef main

int main(int argc, char **argv) {
    if (argc<3) {
        fprintf(stderr,"usage: %s BASE.gguf SFT.bin [SFT.bin ...]\n",argv[0]);
        return 2;
    }
    bpe_tokenizer *tok=bpe_load(argv[1]);
    if (!tok) mlp_die("cannot load tokenizer for token boundary probe");
    int begin=bpe_token_id(tok,"<|im_start|>");
    int end=bpe_token_id(tok,"<|im_end|>");
    int failures=0;
    for (int f=2; f<argc; f++) {
        int n, file_failures=0, comparisons=0;
        long total_ids=0;
        mlp_example *rows=mlp_data(argv[f],&n);
        for (int i=0; i<n; i++) {
            mlp_example *e=&rows[i];
            tokenize(e,tok);
            size_t cap=strlen(e->system)+strlen(e->prompt)+strlen(e->answer)+256;
            char *chat=malloc(cap);
            if (!chat) mlp_die("token boundary probe allocation failed");
            int ids[MLP_MAX_TOKENS];
            for (int full=0; full<2; full++) {
                int written=snprintf(chat,cap,"<|im_start|>system\n%s<|im_end|>\n"
                    "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s%s",
                    e->system,e->prompt,full?e->answer:"",full?"<|im_end|>":"");
                if (written<0 || (size_t)written>=cap) mlp_die("probe ChatML buffer too small");
                int ni=encode_chatml(tok,chat,ids,MLP_MAX_TOKENS,begin,end);
                int nt=full?e->n_ids:e->start+1;
                if (ni<0) mlp_die("inference tokenizer failed in boundary probe");
                int first=-1;
                for (int t=0; t<ni && t<nt; t++) {
                    if (ids[t]!=e->ids[t]) { first=t; break; }
                }
                if (first<0 && ni!=nt) first=ni<nt?ni:nt;
                if (first>=0) {
                    file_failures++;
                    printf("{\"file_index\":%d,\"row\":%d,\"full\":%s,"
                           "\"trainer_count\":%d,\"runner_count\":%d,"
                           "\"first_difference\":%d,\"trainer_id\":%d,\"runner_id\":%d}\n",
                           f-2,i,full?"true":"false",nt,ni,first,
                           first<nt?e->ids[first]:-1,first<ni?ids[first]:-1);
                }
                comparisons++;
                total_ids+=nt;
            }
            free(chat);
            free(e->ids); free(e->system); free(e->prompt); free(e->answer);
            batch_free(&e->cache);
        }
        printf("{\"file_index\":%d,\"pass\":%s,\"rows\":%d,\"comparisons\":%d,"
               "\"trainer_ids_compared\":%ld,\"failures\":%d}\n",
               f-2,file_failures?"false":"true",n,comparisons,total_ids,file_failures);
        failures+=file_failures;
        free(rows);
    }
    bpe_free(tok);
    return failures?1:0;
}
