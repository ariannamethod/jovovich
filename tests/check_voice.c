/* Exercise the same sparse objective used by the native audition. */
#define main voice_pilot_main
#include "../tools/voice_pilot.c"
#undef main
#include "prompt_text.h"

static void check_math(void) {
    adapter a={.n=2,.ids={0,2}};
    int index[]={0,-1,1,-1}; a.index=index;
    float logits[]={0.4f,-1.2f,0.7f,1.1f};
    engine e={.logits=logits}; e.dims.vocab=4;
    e.feature[0]=-0.7f; e.feature[D]=1;
    a.params[0]=0.3f; a.params[WIDTH+D]=-0.2f;
    position rows[2]={0};
    observe(&e,&a,2,&rows[0]); /* Gold inside the trained rows. */
    observe(&e,&a,3,&rows[1]); /* Held-out gold has no trainable row. */
    double dense=0, scores[4];
    for (int i=0;i<4;i++) {
        scores[i]=logits[i]+(index[i]<0 ? 0 : offset(&a,index[i],e.feature));
        dense+=exp(scores[i]);
    }
    float gradient[2*WIDTH]={0};
    double value=nll(&a,rows,2,gradient);
    if (fabs(value-(log(dense)-(scores[2]+scores[3])/2))>1e-6) fail("dense partition mismatch");
    for (int i=0;i<2*WIDTH;i++) {
        float saved=a.params[i],step=0.001f;
        a.params[i]=saved+step; double plus=nll(&a,rows,2,NULL);
        a.params[i]=saved-step; double minus=nll(&a,rows,2,NULL);
        a.params[i]=saved;
        if (fabs((plus-minus)/(2*step)-gradient[i])>5e-5) fail("gradient mismatch");
    }
    fit(&a,rows,2,0.25f,NULL);
    if (nll(&a,rows,2,NULL)>=value) fail("SGD failed to reduce loss");
}

static void check_tokens(const char *path) {
    /* From the original pinned Hugging Face tokenizer.json, without added BOS. */
    const int reference[]={1022,417,86550,48698,3919,2267,9585,1892,15094,11,24461,1892,1436};
    const char *prompt="/* BLOOD INCLUDE \"<path>\" — inject,logging — see";
    bpe_tokenizer *t=bpe_load(path);
    int ids[128];
    if (!t || jov_prompt_ids(t,prompt,ids,128)!=(int)(sizeof(reference)/sizeof(*reference)) ||
        memcmp(ids,reference,sizeof(reference))) fail("em dash tokenization differs from reference");
    const char *outside[]={"x—y","x —y","x— y","x  — y","x —  y","x — ","é — y","x — yé","x — y —λ"};
    for (size_t i=0;i<sizeof(outside)/sizeof(*outside);i++)
        if (jov_prompt_ids(t,outside[i],ids,128)) fail("admitted uncovered prompt text");
    bpe_free(t);
}

int main(int argc,char **argv) {
    if (argc>2) return 2;
    check_math();
    am_init(); am_persistent_mode(1);
    if (am_set_var_text("voice_state","UNIQUE-VOICE-STATE") || am_exec_file("aml/voice-prompt.aml"))
        fail("voice policy did not render");
    const char *p=am_get_var_text("voice_prompt");
    if (!p || !strstr(p,"<|im_start|>user\nUNIQUE-VOICE-STATE\n") ||
        !strstr(p,"<|im_start|>assistant\n<think>\n\n</think>\n\n")) fail("voice context or assistant turn missing");
    am_persistent_clear(); am_persistent_mode(0);
    if (argc==2) check_tokens(argv[1]);
    puts("Voice objective, gradients, SGD and AML prompt verified");
    return 0;
}
