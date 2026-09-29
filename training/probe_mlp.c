/* Compare a trained cached MLP with the complete exported model.
 * Usage: jovovich-probe-mlp BASE.gguf MERGED.gguf SFT.bin LORA_PREFIX ROW [ROW ...]
 * LORA_PREFIX names the three .{gate,up,down}.lora files. ROW is zero-based.
 * JSONL on stdout reports teacher-forced completion accuracy including im_end.
 * Both paths use the trainer's floating activation mode, NT_NO_I8=1.
 * Reports exported-forward parity and completion accuracy.
 */
#define main mlp_trainer_main
#include "train_mlp.c"
#undef main

typedef struct {
    int correct, first_wrong, predicted, target, eos_correct;
} probe_accuracy;

static void record_accuracy(probe_accuracy *a, int prediction, int target,
                            int position, int count) {
    a->correct += prediction == target;
    if (prediction != target && a->first_wrong < 0) {
        a->first_wrong = position;
        a->predicted = prediction;
        a->target = target;
    }
    if (position == count - 1) a->eos_correct = prediction == target;
}

static void print_accuracy(const char *name, const probe_accuracy *a, int n) {
    printf("\"%s\":{\"correct\":%d,\"top1_accuracy\":%.9g,"
           "\"eos_correct\":%s,\"first_incorrect\":",
           name, a->correct, (double)a->correct / n,
           a->eos_correct ? "true" : "false");
    if (a->first_wrong < 0) printf("null}");
    else printf("{\"position\":%d,\"predicted_id\":%d,\"target_id\":%d}}",
                a->first_wrong, a->predicted, a->target);
}

static int probe_row(mlp_bank *b, llama_model *base, nt_dims bd,
                      llama_model *merged, nt_dims md, bpe_tokenizer *tok,
                      mlp_example *ex, int index) {
    tokenize(ex, tok);
    if (ex->n_ids > base->gf->ctx_len || ex->n_ids > merged->gf->ctx_len)
        mlp_die("probe example exceeds model context");

    /* Recover the frozen post-attention input exactly as the trainer does. */
    int last = base->n_layers - 1;
    wt original = base->layers[last].wdown;
    float *bias = base->layers[last].ffn_down_bias;
    float *zero = calloc((size_t)b->E * b->F, sizeof(float));
    if (!zero) mlp_die("probe zero projection allocation failed");
    base->layers[last].wdown = (wt){.f32=zero, .dtype=0, .rows=b->E, .cols=b->F};
    base->layers[last].ffn_down_bias = NULL;
    ex->cache.z = tensor(ex->cache.n, b->E);
    capture_sequence(base, bd, ex, ex->cache.z);
    base->layers[last].wdown = original;
    base->layers[last].ffn_down_bias = bias;
    free(zero);
    prepare_cache(b, &ex->cache);

    /* The reference executes the complete merged GGUF through the native
     * architecture. The hook only observes its final residual; no weights or
     * activations are replaced. Project every observed row to vocabulary. */
    nt_tensor *full = tensor(ex->cache.n, b->E);
    capture_sequence(merged, md, ex, full);
    const wt *head = merged->has_output_weight ? &merged->out_weight : &merged->tok_emb;
    float *xn = malloc((size_t)b->E * sizeof(float));
    if (!xn) mlp_die("probe norm allocation failed");

    double ce_cached=0, ce_full=0, lerr2=0, lref2=0, rerr2=0, rref2=0;
    float max_logit_error=0, max_residual_error=0, max_batch_ce_error=0;
    int agreed=0;
    probe_accuracy cached={.first_wrong=-1}, reference={.first_wrong=-1};
    for (int start=0; start<ex->cache.n; start+=16) {
        int n=ex->cache.n-start;
        if (n>16) n=16;
        token_row order[16];
        for (int t=0; t<n; t++) order[t]=(token_row){0,start+t};
        mlp_batch s=gather(b, ex, order, n);
        nt_tape_start();
        int ri, li;
        int ce=mlp_forward(b, &s, 0, &ri, &li, NULL);
        float cached_ce=nt_tape_get()->entries[ce].output->data[0];
        ce_cached+=(double)n*cached_ce;
        float *ar=nt_tape_get()->entries[ri].output->data;
        float *al=nt_tape_get()->entries[li].output->data;
        nt_tensor *fl=tensor(n, b->V);

        for (int t=0; t<n; t++) {
            float *fr=full->data+(size_t)(start+t)*b->E;
            rmsnorm(xn, fr, merged->out_norm, b->E, merged->rms_eps);
            qmv(fl->data+(size_t)t*b->V, head, xn);
            for (int j=0; j<b->E; j++) {
                double a=ar[(size_t)t*b->E+j], r=fr[j], d=a-r;
                if (!isfinite(a) || !isfinite(r)) mlp_die("nonfinite probe residual");
                max_residual_error=fmaxf(max_residual_error, (float)fabs(d));
                rerr2+=d*d; rref2+=r*r;
            }
            int ai=0, fi=0;
            for (int j=0; j<b->V; j++) {
                float a=al[(size_t)t*b->V+j], r=fl->data[(size_t)t*b->V+j];
                if (!isfinite(a) || !isfinite(r)) mlp_die("nonfinite probe logits");
                double d=(double)a-r;
                max_logit_error=fmaxf(max_logit_error, (float)fabs(d));
                lerr2+=d*d; lref2+=(double)r*r;
                if (a>al[(size_t)t*b->V+ai]) ai=j;
                if (r>fl->data[(size_t)t*b->V+fi]) fi=j;
            }
            agreed+=ai==fi;
            int target=(int)s.targets->data[t];
            record_accuracy(&cached, ai, target, start+t, ex->cache.n);
            record_accuracy(&reference, fi, target, start+t, ex->cache.n);
        }
        int fc=checked(nt_seq_cross_entropy(checked(nt_tape_param_frozen(fl)),
                       checked(nt_tape_param_frozen(s.targets)), n, b->V));
        float full_ce=nt_tape_get()->entries[fc].output->data[0];
        if (!isfinite(cached_ce) || !isfinite(full_ce)) mlp_die("nonfinite probe CE");
        ce_full+=(double)n*full_ce;
        max_batch_ce_error=fmaxf(max_batch_ce_error, fabsf(cached_ce-full_ce));
        nt_tape_clear();
        nt_tensor_free(fl);
        batch_free(&s);
    }
    double residual_relative_l2=sqrt(rerr2/fmax(rref2,1e-30));
    double logits_relative_l2=sqrt(lerr2/fmax(lref2,1e-30));
    int pass=agreed==ex->cache.n && logits_relative_l2<=1e-5 &&
             residual_relative_l2<=1e-5 && max_batch_ce_error<=1e-4;
    printf("{\"row\":%d,\"pass\":%s,\"context_tokens\":%d,\"completion_tokens\":%d,"
           "\"cached_adapter_ce\":%.9g,\"full_merged_ce\":%.9g,"
           "\"max_batch_ce_diff\":%.9g,\"residual_max_abs\":%.9g,"
           "\"residual_relative_l2\":%.9g,\"logits_max_abs\":%.9g,"
           "\"logits_relative_l2\":%.9g,\"argmax_agree\":%d,",
           index, pass ? "true" : "false", ex->start+1, ex->cache.n, ce_cached/ex->cache.n,
           ce_full/ex->cache.n, max_batch_ce_error, max_residual_error,
           residual_relative_l2, max_logit_error, logits_relative_l2, agreed);
    print_accuracy("cached", &cached, ex->cache.n);
    printf(",");
    print_accuracy("full", &reference, ex->cache.n);
    printf("}\n");
    fflush(stdout);
    free(xn);
    nt_tensor_free(full);
    batch_free(&ex->cache);
    memset(&ex->cache, 0, sizeof(ex->cache));
    free(ex->ids);
    ex->ids=NULL;
    return pass;
}

int main(int argc, char **argv) {
    if (argc<6) {
        fprintf(stderr, "usage: %s BASE.gguf MERGED.gguf SFT.bin LORA_PREFIX ROW [ROW ...]\n", argv[0]);
        return 2;
    }
    if (setenv("NT_NO_I8", "1", 1)) mlp_die("cannot set floating activation mode");
    int count;
    mlp_example *rows=mlp_data(argv[3], &count);
    gguf_file *bg=gguf_open(argv[1]), *mg=gguf_open(argv[2]);
    if (!bg || !mg) mlp_die("cannot load probe GGUF files");
    if (strcmp(bg->arch,"qwen2") || strcmp(mg->arch,"qwen2") || bg->n_layers<1 ||
        !isfinite(bg->rms_eps) || fabsf(bg->rms_eps-1e-6f)>1e-12f || mg->rms_eps!=bg->rms_eps)
        mlp_die("probe requires matching qwen2 models with RMS epsilon 1e-6");
    nt_dims bd, md;
    llama_model *base=nt_arch_llama.load(bg, &bd), *merged=nt_arch_llama.load(mg, &md);
    bpe_tokenizer *tok=bpe_load(argv[1]);
    if (!base || !merged || !tok) mlp_die("cannot load probe bodies/tokenizer");
    if (base->embed!=merged->embed || base->ffn!=merged->ffn ||
        base->vocab!=merged->vocab || base->n_layers!=merged->n_layers ||
        !base->layers[base->n_layers-1].ffn_norm)
        mlp_die("probe model dimensions do not match");
    mlp_bank bank={0};
    bank_init(&bank, base);
    const char *suffix[]={"gate","up","down"};
    for (int j=0; j<3; j++) {
        char path[4096], name[128];
        if (snprintf(path,sizeof(path),"%s.%s.lora",argv[4],suffix[j])>=(int)sizeof(path))
            mlp_die("probe adapter path too long");
        snprintf(name,sizeof(name),"blk.%d.ffn_%s.weight",bank.layer,suffix[j]);
        const char *names[]={name};
        if (nt_lora_load(&bank.adapters[j], 1, 1, names, path)) mlp_die("cannot load probe adapter");
    }
    int pass=1;
    for (int a=5; a<argc; a++) {
        int i=number(argv[a], 0, count-1);
        pass &= probe_row(&bank, base, bd, merged, md, tok, &rows[i], i);
    }
    nt_tape_destroy();
    for (int j=0; j<3; j++) nt_lora_free(&bank.adapters[j]);
    nt_tensor_free(bank.wg); nt_tensor_free(bank.wu); nt_tensor_free(bank.wd);
    nt_tensor_free(bank.head); nt_tensor_free(bank.norm); nt_tensor_free(bank.ffn_norm);
    nt_tensor_free(bank.bias);
    for (int i=0; i<count; i++) {
        free(rows[i].system); free(rows[i].prompt); free(rows[i].answer);
    }
    free(rows);
    bpe_free(tok);
    nt_arch_llama.free(base); nt_arch_llama.free(merged);
    gguf_close(bg); gguf_close(mg);
    return pass ? 0 : 1;
}
