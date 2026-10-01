/* Tokenization and joint-objective preflight. No model load or forward pass.
 * Build from the repository root with -Itraining and the usual substrate.
 * Reuses the actual native trainer and runtime ChatML tokenizer.
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main
#define main inference_main
#include "../src/infer.c"
#undef main

static void preflight_compare(const mlp_example *e, bpe_tokenizer *tok,
                              int begin, int end, int full) {
    size_t cap = strlen(e->system) + strlen(e->prompt) + strlen(e->answer) + 256;
    char *chat = malloc(cap);
    if (!chat) mlp_die("preflight ChatML allocation failed");
    int written = snprintf(chat, cap, "<|im_start|>system\n%s<|im_end|>\n"
        "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s%s",
        e->system, e->prompt, full ? e->answer : "", full ? "<|im_end|>" : "");
    if (written < 0 || (size_t)written >= cap) mlp_die("preflight ChatML overflow");
    int ids[MLP_MAX_TOKENS];
    int actual = encode_chatml(tok, chat, ids, MLP_MAX_TOKENS, begin, end);
    int expected = full ? e->n_ids : e->start + 1;
    if (actual != expected) mlp_die("preflight trainer/runtime token count disagrees");
    for (int t = 0; t < actual; t++)
        if (ids[t] != e->ids[t]) mlp_die("preflight trainer/runtime token IDs disagree");
    free(chat);
}

int main(int argc, char **argv) {
    if (argc < 4 || argc > 5) {
        fprintf(stderr, "usage: %s BASE.gguf SFT.bin PAIR_MAP [MICROBATCH=40]\n", argv[0]);
        return 2;
    }
    int batch = argc == 5 ? number(argv[4], 1, 128) : 40;
    gguf_file *gf = gguf_open(argv[1]);
    if (!gf) mlp_die("preflight cannot open model metadata");
    if (strcmp(gf->arch, "qwen2") || gf->n_layers < 1 ||
        fabsf(gf->rms_eps - 1e-6f) > 1e-12f)
        mlp_die("preflight incompatible native MLP model metadata");
    bpe_tokenizer *tok = bpe_load(argv[1]);
    if (!tok) mlp_die("preflight cannot load tokenizer");
    int begin = bpe_token_id(tok, "<|im_start|>");
    int end = bpe_token_id(tok, "<|im_end|>");
    if (begin < 0 || end < 0) mlp_die("preflight missing ChatML IDs");
    int count, total = 0, prompt_max = 0, full_max = 0;
    mlp_example *rows = mlp_data(argv[2], &count);
    for (int i = 0; i < count; i++) {
        mlp_example *e = &rows[i];
        tokenize(e, tok);
        if (e->n_ids > gf->ctx_len) mlp_die("preflight exceeds model context");
        if (total > INT_MAX - e->cache.n) mlp_die("preflight too many targets");
        total += e->cache.n;
        if (e->start + 1 > prompt_max) prompt_max = e->start + 1;
        if (e->n_ids > full_max) full_max = e->n_ids;
        if (e->ids[e->n_ids - 1] != end ||
            (int)e->cache.targets->data[e->cache.n - 1] != end)
            mlp_die("preflight missing supervised terminal im_end");
        preflight_compare(e, tok, begin, end, 0);
        preflight_compare(e, tok, begin, end, 1);
    }
    mlp_bank bank = {0};
    bank.average_tokens = (double)total / count;
    load_pairs(&bank, rows, count, argv[3]);
    int decisions, residuals;
    token_row *order = joint_order(rows, count, &decisions, &residuals);
    token_row *decision = decision_order(rows, count, decisions);
    int review_targets = decisions + residuals, review_count = 0;
    for (int i = 0; i < count; i++) {
        mlp_example *e = &rows[i];
        int mapped = e->decision_pair != 0;
        review_count += mapped;
        printf("{\"stage\":\"row\",\"row\":%d,\"prompt_tokens\":%d,\"capture_start\":%d,"
               "\"full_tokens\":%d,\"completion_targets\":%d,\"terminal_target_id\":%d,"
               "\"mapped_review\":%s,\"trained_targets\":%d,\"residual_targets\":%d,"
               "\"chatml_prompt_equal\":true,\"chatml_full_equal\":true",
               i, e->start + 1, e->start, e->n_ids, e->cache.n, end,
               mapped ? "true" : "false", mapped ? e->cache.n : 0,
               mapped ? e->cache.n - 1 : 0);
        if (mapped) printf(",\"pair_index\":%d,\"decision_position\":%d,"
                           "\"decision_target_id\":%d,\"decision_alternative_id\":%d",
                           e->decision_pair - 1, e->decision_position,
                           (int)e->cache.targets->data[e->decision_position],
                           e->decision_alternative_id);
        printf(",\"token_ids\":[");
        for (int t = 0; t < e->n_ids; t++) printf("%s%d", t ? "," : "", e->ids[t]);
        puts("]}");
    }
    if (review_count != decisions) mlp_die("preflight mapped review count disagrees");
    printf("{\"stage\":\"summary\",\"pass\":true,\"examples\":%d,\"review_examples\":%d,"
           "\"readout_only_examples\":%d,\"review_pairs\":%d,\"all_completion_targets\":%d,"
           "\"decision_positions\":%d,\"residual_positions\":%d,\"joint_positions\":%d,"
           "\"decision_coefficient\":%.17g,\"residual_coefficient\":%.17g,"
           "\"native_float_decision_coefficient\":%.9g,\"native_float_residual_coefficient\":%.9g,"
           "\"microbatch_tokens\":%d,\"microbatches_per_update\":%d,\"last_microbatch_tokens\":%d,"
           "\"chatml_comparisons\":%d,\"prompt_tokens_max\":%d,\"full_tokens_max\":%d,"
           "\"model_context\":%d,\"chatml_im_start\":%d,\"chatml_im_end\":%d,"
           "\"model_forward_calls\":0}\n",
           count, decisions, count-decisions, bank.pair_count, total, decisions, residuals,
           review_targets, 1.0/decisions, 1.0/residuals, 1.0f/decisions, 1.0f/residuals,
           batch, (review_targets + batch - 1)/batch, (review_targets-1)%batch+1,
           2*count, prompt_max, full_max, gf->ctx_len, begin, end);
    free(order); free(decision);
    for (int i = 0; i < count; i++) {
        free(rows[i].system); free(rows[i].prompt); free(rows[i].answer);
        free(rows[i].ids); batch_free(&rows[i].cache);
    }
    free(rows); bpe_free(tok); gguf_close(gf);
    return ferror(stdout) ? 1 : 0;
}
