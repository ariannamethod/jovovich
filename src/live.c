#define _POSIX_C_SOURCE 200809L
#include "review.h"
#include "facts.h"
#include "boundary.h"
#include "run_selection.h"
#include "ariannamethod.h"
#include "harness/arch.h"
#include "examples/bpe.h"
#include "tools/narrow_json.h"
#include "hash.h"
#include "json.h"
#include "readout.h"
#include "report_json.h"
#include <limits.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int hash_file(const char *path,char out[65]) {
    int fd=open(path,O_RDONLY);struct stat st;int rc=1;
    if(fd>=0 && !fstat(fd,&st) && st.st_size>0) {
        void *p=mmap(NULL,(size_t)st.st_size,PROT_READ,MAP_PRIVATE,fd,0);
        if(p!=MAP_FAILED){rc=hash_bytes(p,(size_t)st.st_size,out);munmap(p,(size_t)st.st_size);}
    }
    if(fd>=0)close(fd);
    return rc;
}
static int run(const char *path){int rc=am_exec_file(path);if(rc)fprintf(stderr,"AML: %s\n",am_get_error());return rc;}

typedef struct {
    int last_layer, captured;
    float unit[JOV_WIDTH];
} final_state;

static int capture_final(void *user, int layer, int pos, int n, int width, float *residual) {
    (void)pos;
    final_state *state = user;
    if (layer != state->last_layer) return 0;
    if (width != JOV_WIDTH || n < 1) return 1;
    const float *last = residual + (size_t)(n-1) * width;
    double sum = 0;
    for (int i = 0; i < width; ++i) sum += (double)last[i] * last[i];
    if (!(sum > 0) || !isfinite(sum)) return 1;
    double norm = sqrt(sum);
    for (int i = 0; i < width; ++i) state->unit[i] = (float)(last[i]/norm);
    state->captured = 1;
    return 0;
}

static int write_features(const final_state *state, const char *id, const char *input_hash,
                          const char *weights, const char *tokenizer, const float *logits) {
    if (!state->captured || !isfinite(logits[32]) || !isfinite(logits[33])) return 1;
    fputs("{\"schema\":\"jovovich.features/1\",",stdout);
    json_field(stdout,"id",id);
    printf(",\"input_sha256\":\"%s\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",",
           input_hash,weights,tokenizer);
    printf("\"logit_a\":%.9g,\"logit_b\":%.9g,\"hidden\":[",logits[32],logits[33]);
    for (int i=0; i<JOV_WIDTH; ++i) printf(i?",%.9g":"%.9g",state->unit[i]);
    return fputs("]}\n",stdout)==EOF || fflush(stdout);
}

/* Both tasks use the same text encoding, fresh cache, and A/B output logits. */
static int forward_prompt(void *model,bpe_tokenizer *tok,const char *prompt,float *logits,final_state *capture) {
    if(!prompt || strlen(prompt)>1048576)return 1;
    for(const unsigned char *p=(const unsigned char*)prompt;*p;p++)if(*p>=128) {
        fprintf(stderr,"Native text input currently requires ASCII; Unicode uses verified token IDs\n");return 1;
    }
    size_t len=strlen(prompt);
    int *ids=malloc((len+1)*sizeof(*ids));if(!ids)return 1;
    int n=bpe_encode_special(tok,prompt,ids,(int)len+1);
    kv_cache *kv=n>=1 && n<=8192 ? nt_arch_qwen35.kv_new(model,n) : NULL;
    int rc=kv?0:1;
    for(int pos=0;!rc && pos<n;pos+=32) {
        int take=n-pos<32?n-pos:32;
        if(capture && pos+take==n)
            rc=nt_arch_qwen35.forward_residual(model,kv,ids+pos,take,pos,logits,capture_final,capture);
        else rc=nt_arch_qwen35.forward(model,kv,ids+pos,take,pos,pos+take==n?logits:NULL);
        if(rc)fprintf(stderr,"NoTorch: %s\n",nt_strerror(rc));
    }
    if(kv)nt_arch_qwen35.kv_free(model,kv);
    free(ids);return rc;
}

static int score_choices(float pair[2]) {
    if (!isfinite(pair[0]) || !isfinite(pair[1]) ||
        am_set_var_array("choice_logits", pair, 2) || run("aml/score-choices.aml")) return 1;
    int count = 0;
    const float *p = am_get_var_array("probabilities", &count);
    if (!p || count != 2) return 1;
    memcpy(pair, p, 2 * sizeof(*p));
    return 0;
}

static int select_run(const char *line,size_t bytes,void *model,bpe_tokenizer *tok,
                      float *logits,const char *weights,const char *tokenizer) {
    int mode_a;
    if(jov_prepare_selection(line,&mode_a))return 1;
    const char *prompt=am_get_var_text("prompt");
    char ih[65],ph[65];
    if(!prompt || hash_bytes(line,bytes,ih) || hash_bytes(prompt,strlen(prompt),ph) ||
       forward_prompt(model,tok,prompt,logits,NULL))return 1;
    char *id=nj_string(nj_get(line,"id"));if(!id || !*id){free(id);return 1;}
    float p[2]={logits[32],logits[33]};
    softmax(p,2);
    if(!isfinite(p[0]) || !isfinite(p[1])){free(id);return 1;}
    int a=p[0]>=p[1];
    fputs("{\"schema\":\"jovovich.run-choice/1\",",stdout);json_field(stdout,"id",id);free(id);
    printf(",\"input_sha256\":\"%s\",\"prompt_sha256\":\"%s\",\"weights_sha256\":\"%s\","
           "\"tokenizer_sha256\":\"%s\",\"p_a\":%.17g,\"p_b\":%.17g,\"letter\":\"%s\",\"selected_mode\":%d}\n",
           ih,ph,weights,tokenizer,p[0],p[1],a?"A":"B",a?mode_a:1-mode_a);
    return fflush(stdout)==EOF || ferror(stdout);
}

int main(int argc,char **argv) {
    int json=0,features=0,canonical=0,select=0,valid=argc>=3;const char *adapter=NULL;
    for(int i=3;i<argc && valid;i++) {
        if(!strcmp(argv[i],"--json") && !json)json=1;
        else if(!strcmp(argv[i],"--select-run") && !select)select=1;
        else if(!strcmp(argv[i],"--features") && !features)features=1;
        else if(!strcmp(argv[i],"--canonical-boundaries") && !canonical)canonical=1;
        else if(!strcmp(argv[i],"--readout") && !adapter && i+1<argc)adapter=argv[++i];
        else valid=0;
    }
    if(!valid || ((features || select) && (json || adapter || canonical)) || (features && select)) {
        fprintf(stderr,"Usage: %s MODEL.gguf TOKENIZER.gguf [--select-run | --features | [--json] [--readout ADAPTER.json] [--canonical-boundaries]] < reviews.jsonl\n",argv[0]);return 2;
    }
    char *manifest=nj_load("models/onejev-0.8b.json",NULL);if(!manifest)return 1;
    char *model_id=nj_string(nj_get(manifest,"model_id")),*revision=nj_string(nj_get(manifest,"revision"));
    char *want_weights=nj_string(nj_get(manifest,"weights_sha256")),*want_tokenizer=nj_string(nj_get(manifest,"tokenizer_sha256"));
    char wh[65],th[65];int rc=1,seen=0;gguf_file *g=NULL;void *m=NULL;bpe_tokenizer *tok=NULL;
    float *logits=NULL;char *line=NULL;size_t cap=0;ssize_t bytes;nt_dims dims={0};
    if(!model_id || !revision || !want_weights || !want_tokenizer || hash_file(argv[1],wh) || hash_file(argv[2],th) ||
       strcmp(wh,want_weights) || strcmp(th,want_tokenizer)) {
        fprintf(stderr,"Model/tokenizer bytes do not match models/onejev-0.8b.json\n");goto done;
    }
    jov_readout head;char adapter_hash[65];
    if(adapter && jov_readout_load(&head,adapter,wh,th,adapter_hash)) {
        fprintf(stderr,"Invalid readout or mismatched base model\n");goto done;
    }
    g=gguf_open(argv[1]);m=g?nt_arch_qwen35.load(g,&dims):NULL;tok=bpe_load(argv[2]);
    if(!m || !tok || bpe_token_id(tok,"A")!=32 || bpe_token_id(tok,"B")!=33)goto done;
    logits=malloc((size_t)dims.vocab*sizeof(float));if(!logits)goto done;
    am_init();
    am_persistent_mode(1);
    while((bytes=getline(&line,&cap,stdin))>=0) {
        if(memchr(line,0,(size_t)bytes) || bytes>1048576){fprintf(stderr,"Invalid input row size/NUL\n");goto done;}
        const char *end=nj_skip(line,0);
        if(end && nj_get(line,"fact"))end=report_json_end(line,0);
        if(!end || *nj_ws(end)){fprintf(stderr,"Invalid JSON row\n");goto done;}
        if(select) {
            if(select_run(line,(size_t)bytes,m,tok,logits,wh,th)){fprintf(stderr,"Invalid run selection at row %d\n",seen+1);goto done;}
            seen++;continue;
        }
        char *id=nj_string(nj_get(line,"id")),*file=nj_string(nj_get(line,"file"));
        char *context=nj_string(nj_get(line,"context")),*rule=nj_string(nj_get(line,"rule_excerpt"));
        char *change=nj_string(nj_get(line,"change_excerpt"));char ih[65];
        jov_review r={.id=id,.model=model_id,.revision=revision,.question="pending",
            .file=file,.context=context,.rule_excerpt=rule,.change_excerpt=change,.concern=.5,.clean=.5};
        char code[JOV_BOUNDARY_CODE_SIZE],ph[65],*model_context=NULL;
        jov_boundary_receipt receipt={NULL,ph};
        int status=1;
        jov_fact *fact = NULL;
        char *origin[6]={0};jov_source source={0};
        const char *raw_source=nj_get(line,"source");
        if(raw_source) {
            const char *keys[]={"base_commit","head_commit","rules_path","rules_blob","rules_sha256","diff_sha256"};
            for(int i=0;i<6;i++)origin[i]=nj_string(nj_get(raw_source,keys[i]));
            long long first=0,last=0;
            if(!nj_is(nj_get(raw_source,"kind"),"git") ||
                nj_int(nj_get(raw_source,"rule_first_line"),&first) ||
                nj_int(nj_get(raw_source,"rule_last_line"),&last) ||
                first<1 || last<first || last>INT_MAX)goto row_done;
            source=(jov_source){origin[0],origin[1],origin[2],origin[3],origin[4],origin[5],(int)first,(int)last};
            r.source=&source;
        }
        if (jov_fact_decode(nj_get(line, "fact"), &fact)) goto row_done;
        r.fact = fact;
        if(jov_review_validate(&r) || hash_bytes(line,(size_t)bytes,ih))goto row_done;
        if(r.source) {
            char rule_hash[65],diff_hash[65];
            if(hash_bytes(rule,strlen(rule),rule_hash) || hash_bytes(change,strlen(change),diff_hash) ||
                strcmp(rule_hash,source.rules_sha256) || strcmp(diff_hash,source.diff_sha256)) {
                fprintf(stderr,"Git evidence hash mismatch\n");goto row_done;
            }
        }
        if(canonical) {
            int matched=jov_boundary_context(context,rule,change,code,&model_context);
            if(matched<0)goto row_done;
            if(matched)receipt.code=code;
        }
        jov_trace_receipt trace={0};
        int has_trace=nj_get(line,"trace_evidence")!=NULL;
        if(am_set_var_text("review_context",model_context?model_context:context) ||
           (has_trace && jov_apply_trace_gate(line,id,rule,change,&trace)) || run("aml/prepare.aml"))goto row_done;
        const char *prompt=am_get_var_text("prompt");r.question=am_get_var_text("question");
        if(!prompt || !r.question)goto row_done;
        if(features && nj_get(line,"prompt")) {
            char *stored=nj_string(nj_get(line,"prompt"));
            int same=stored && !strcmp(stored,prompt);free(stored);
            if(!same){fprintf(stderr,"Training prompt differs from AML output\n");goto row_done;}
        }
        size_t len=strlen(prompt);if(len>1048576 || ((canonical || has_trace) && hash_bytes(prompt,len,ph)))goto row_done;
        if(has_trace)memcpy(trace.prompt_sha256,ph,sizeof(ph));
        final_state state={.last_layer=dims.n_layers-1};
        if(forward_prompt(m,tok,prompt,logits,features || adapter ? &state : NULL))goto row_done;
        if(features) {status=write_features(&state,id,ih,wh,th,logits);goto row_done;}
        float probs[2]={logits[32],logits[33]};
        if(adapter) {
            if(!state.captured || jov_readout_margin(&head,state.unit,probs[0]-probs[1],&probs[0]))goto row_done;
            probs[1]=0;
        }
        if(score_choices(probs))goto row_done;
        struct timespec now;if(clock_gettime(CLOCK_REALTIME,&now))goto row_done;
        int day=(int)(now.tv_sec/86400),sec=(int)(now.tv_sec%86400),ms=(int)(now.tv_nsec/1000000);
        if(sec<0){day--;sec+=86400;}
        float parts[3]={(float)day,(float)sec,(float)ms};
        if(am_set_var_array("clock_parts",parts,3) || run("aml/answer.aml"))goto row_done;
        r.concern=probs[0];r.clean=probs[1];
        const char *verdict=am_get_var_text("verdict"),*chosen=jov_review_verdict(&r);
        if(!verdict || !chosen || strcmp(verdict,chosen) || !am_get_var_record("reviewed_at"))goto row_done;
        jov_execution execution={ih,wh,th,day,sec,ms,adapter?adapter_hash:NULL,canonical?&receipt:NULL,has_trace?&trace:NULL};r.execution=&execution;
        if(seen && !json)fputs("\n---\n\n",stdout);
        status=json?jov_review_json(stdout,&r):jov_review_markdown(stdout,&r);
        if(fflush(stdout))status=JOV_IO_ERROR;
row_done:
        jov_fact_free(fact);
        free(model_context);free(id);free(file);free(context);free(rule);free(change);
        for(int i=0;i<6;i++)free(origin[i]);
        if(status){fprintf(stderr,"Review failed at input row %d\n",seen+1);goto done;}seen++;
    }
    rc=ferror(stdin) || !seen;
done:
    am_persistent_clear();am_persistent_mode(0);
    free(line);free(logits);bpe_free(tok);nt_arch_qwen35.free(m);gguf_close(g);
    free(model_id);free(revision);free(want_weights);free(want_tokenizer);free(manifest);return rc;
}
