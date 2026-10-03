/* Inspect pair positions using the actual native tokenizer, before inference.
 * No model weights, activations, fitting or training are used by this probe.
 * Usage: jovovich-probe-pairs BASE.gguf SFT.bin PAIRS.bin
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main

int main(int argc,char **argv) {
    if(argc!=4) {
        fprintf(stderr,"usage: %s BASE.gguf SFT.bin PAIRS.bin\n",argv[0]);
        return 2;
    }
    bpe_tokenizer *tok=bpe_load(argv[1]);
    if(!tok)mlp_die("cannot load tokenizer for pair probe");
    int count,total=0;
    mlp_example *rows=mlp_data(argv[2],&count);
    for(int i=0;i<count;i++) {
        tokenize(&rows[i],tok);
        if(total>INT_MAX-rows[i].cache.n)mlp_die("too many probe tokens");
        total+=rows[i].cache.n;
    }
    mlp_bank bank={.average_tokens=(double)total/count};
    load_pairs_tokenized(&bank,rows,count,argv[3],tok);
    printf("{\"stage\":\"pair_configuration\",\"pair_map_version\":%d,\"rows\":%d,\"pairs\":%d}\n",
           bank.pair_map_version,count,bank.pair_count);
    int observed=0;
    for(int i=0;i<count;i++) {
        mlp_example *e=&rows[i];
        if(!e->decision_pair)continue;
        printf("{\"stage\":\"pair_row\",\"row\":%d,\"pair_index\":%d,\"prompt_tokens\":%d,\"total_tokens\":%d,\"decision_position\":%d,"
               "\"decision_prefix_bytes\":%d,\"decision_target_id\":%d,\"decision_alternative_id\":%d,\"decision_prefix\":",
               i,e->decision_pair-1,e->start+1,e->n_ids,e->decision_position,e->decision_prefix_bytes,
               (int)e->cache.targets->data[e->decision_position],e->decision_alternative_id);
        print_json_span(e->answer,(size_t)e->decision_prefix_bytes);
        printf(",\"answer_ids\":[");
        for(int t=0;t<e->cache.n;t++)printf("%s%d",t?",":"",(int)e->cache.targets->data[t]);
        printf("]}\n");observed++;
    }
    if(observed!=2*bank.pair_count)mlp_die("incomplete pair probe coverage");
    printf("{\"stage\":\"pair_completion\",\"pass\":true,\"review_rows\":%d}\n",observed);
    for(int i=0;i<count;i++) {
        free(rows[i].system);free(rows[i].prompt);free(rows[i].answer);free(rows[i].ids);
        batch_free(&rows[i].cache);
    }
    free(rows);bpe_free(tok);return 0;
}
