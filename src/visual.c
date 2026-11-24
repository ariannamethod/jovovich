#define _POSIX_C_SOURCE 200809L
#include "visual.h"
#include "visual_memory.h"
#include "visual_compare.h"
#include "harness/image.h"
#include "model_bytes.h"
#include "prompt_text.h"
#include "json.h"
#include "tools/narrow_json.h"
#include "ariannamethod.h"
#include <math.h>
#include <time.h>

static int visual_aml(const char *path) {
    int rc=am_exec_file(path);if(rc)fprintf(stderr,"AML: %s\n",am_get_error());return rc;
}
/* Same immutable snapshot and exact-byte verification as text weights. */
static char *captured_path(const jov_model_files *s) {
    if(!s->name)return strdup(s->part[JOV_WEIGHTS].path);
    size_t n=strlen(s->name)+sizeof("/weights");char *p=malloc(n);
    if(p)snprintf(p,n,"%s/weights",s->name);
    return p;
}
nt_qwen35_vision *jov_visual_load(const char *path,const char *manifest,char hash[65]) {
    char *vm=nj_load("models/onejev-0.8b-vision.json",NULL);
    const char *keys[]={"model_id","revision","weights_sha256","tokenizer_sha256"};
    int matches=vm!=NULL;
    for(int i=0;i<4;i++) {
        char *text=nj_string(nj_get(manifest,keys[i])),*image=nj_string(nj_get(vm,keys[i]));
        if(!text || !image || strcmp(text,image))matches=0;
        free(text);free(image);
    }
    char *want=matches?nj_string(nj_get(vm,"vision_weights_sha256")):NULL;free(vm);
    if(!want){fprintf(stderr,"This model manifest has no verified vision encoder\n");return NULL;}
    jov_model_files files;nt_qwen35_vision *v=NULL;gguf_file *g=NULL;char *copy=NULL;
    if(!jov_model_files_begin(&files,1) && !jov_model_capture(&files,JOV_WEIGHTS,path,want,hash) &&
       (copy=captured_path(&files)) && (g=gguf_open(copy)))v=nt_qwen35_vision_load(g);
    free(copy);gguf_close(g);jov_model_files_end(&files);free(want);return v;
}
static int read_image(const char *path,const char *want,char hash[65],uint8_t **pixels,int *h,int *w) {
    jov_model_files files;char *copy=NULL;int rc=1;
    if(!jov_model_files_begin(&files,1) && !jov_model_capture(&files,JOV_WEIGHTS,path,want,hash) &&
       (copy=captured_path(&files)) && (*pixels=nt_image_load(copy,h,w)))rc=0;
    free(copy);jov_model_files_end(&files);return rc;
}
static char *field(const char *row,const char *key,size_t limit) {
    char *v=nj_string(nj_get(row,key));
    if(v && (!*v || strlen(v)>limit)){free(v);v=NULL;}
    return v;
}
static char *aml_text(const char *name) {
    const char *s=am_get_var_text(name);
    return s?strdup(s):NULL;
}
int jov_visual_choice(const char *line,size_t bytes,void *model,bpe_tokenizer *tok,
    nt_qwen35_vision *vision,float *logits,const char *weights,const char *tokenizer,const char *vision_hash,const char *memory) {
    char *id=field(line,"id",256),*question=field(line,"question",4096),*a=field(line,"choice_a",2048),*b=field(line,"choice_b",2048);
    const char *image=nj_get(line,"image");char *path=field(image,"path",4096),*want=field(image,"sha256",64);
    uint8_t *rgb=NULL;nt_qwen35_image im={0};float *features=NULL;int *ids=NULL,(*positions)[3]=NULL;
    const float **rows=NULL;kv_cache *cache=NULL;int rc=1,h=0,w=0;char ih[65],ph[65],image_hash[65];
    char *answer=NULL,*receipt=NULL;size_t answer_length=0;FILE *out=NULL;
    const nt_qwen35_vision_info *vi=nt_qwen35_vision_get_info(vision);
    if((nj_get(line,"remember") && !memory) || nj_get(line,"recall") || nj_get(line,"compare") ||
       !id || !question || !a || !b || !path || !want || strlen(want)!=64 || !strcmp(a,b) ||
       !vi || vi->output_width!=1024 || vi->rope_dim!=64 ||
       read_image(path,want,image_hash,&rgb,&h,&w) ||
       nt_qwen35_image_prepare(vision,rgb,h,w,262144,&im) || nt_qwen35_vision_encode(vision,&im,&features))goto done;
    if(am_set_var_text("visual_question",question) || am_set_var_text("visual_a",a) || am_set_var_text("visual_b",b) ||
       visual_aml("aml/visual.aml"))goto done;
    const char *prompt=am_get_var_text("prompt"),*state=am_get_var_text("visual_text");
    if(!prompt || !state || hash_bytes(line,bytes,ih) || hash_bytes(prompt,strlen(prompt),ph))goto done;
    size_t cap=strlen(prompt)*2+(size_t)im.tokens+16;
    if(cap>1048576 || !(ids=malloc(cap*sizeof(*ids))))goto done;
    const char *begin=strstr(prompt,"\n</state>");
    if(!begin)goto done;
    begin+=strlen("\n</state>");
    if(strncmp(begin,state,strlen(state)))goto done;
    int n=jov_literal_span_ids(tok,prompt,begin,strlen(state),ids,(int)cap),at=-1;
    for(int t=0;t<n;t++)if(ids[t]==vi->image_id){if(at>=0)goto done;at=t;}
    if(n<1 || at<1 || at>=n-1 || ids[at-1]!=vi->start_id || ids[at+1]!=vi->end_id ||
       (size_t)n+im.tokens-1>=cap || n+im.tokens-1>8192)goto done;
    memmove(ids+at+im.tokens,ids+at+1,(size_t)(n-at-1)*sizeof(*ids));
    for(int j=0;j<im.tokens;j++)ids[at+j]=vi->image_id;
    n+=im.tokens-1;
    positions=malloc((size_t)n*sizeof(*positions));rows=malloc((size_t)n*sizeof(*rows));
    if(!positions || !rows || nt_qwen35_image_positions(vision,&im,features,ids,n,positions,rows)<0 ||
       !(cache=nt_arch_qwen35.kv_new(model,n)))goto done;
    for(int pos=0;pos<n;pos+=32) {
        int take=n-pos<32?n-pos:32;
        if(nt_qwen35_forward_3d(model,cache,ids+pos,rows+pos,(const int(*)[3])(positions+pos),vi->section,
            take,pos,pos+take==n?logits:NULL,NULL,NULL))goto done;
    }
    float pair[2]={logits[32],logits[33]};
    if(!isfinite(pair[0]) || !isfinite(pair[1]) || am_set_var_array("choice_logits",pair,2) || visual_aml("aml/score-choices.aml"))goto done;
    int count=0;const float *p=am_get_var_array("probabilities",&count);if(!p || count!=2)goto done;
    pair[0]=p[0];pair[1]=p[1];
    struct timespec now;if(clock_gettime(CLOCK_REALTIME,&now))goto done;
    int day=(int)(now.tv_sec/86400),sec=(int)(now.tv_sec%86400),ms=(int)(now.tv_nsec/1000000);
    if(sec<0){day--;sec+=86400;}float clock[3]={(float)day,(float)sec,(float)ms};
    if(am_set_var_array("clock_parts",clock,3) || visual_aml("aml/visual-answer.aml") || !am_get_var_record("observed_at"))goto done;
    const char *letter=am_get_var_text("visual_letter");if(!letter || strcmp(letter,pair[0]>=pair[1]?"A":"B"))goto done;
    out=open_memstream(&answer,&answer_length);if(!out)goto done;
    fputs("{\"schema\":\"jovovich.visual-choice/1\",",out);json_field(out,"id",id);
    fputc(',',out);json_field(out,"question",question);fputc(',',out);json_field(out,"choice_a",a);fputc(',',out);json_field(out,"choice_b",b);
    fprintf(out,",\"input_sha256\":\"%s\",\"prompt_sha256\":\"%s\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",\"vision_weights_sha256\":\"%s\",",ih,ph,weights,tokenizer,vision_hash);
    fprintf(out,"\"image\":{\"sha256\":\"%s\",\"width\":%d,\"height\":%d,\"resized_width\":%d,\"resized_height\":%d,\"tokens\":%d,\"max_pixels\":262144},",image_hash,w,h,im.width,im.height,im.tokens);
    fprintf(out,"\"logit_a\":%.9g,\"logit_b\":%.9g,\"p_a\":%.9g,\"p_b\":%.9g,\"letter\":\"%s\",\"observed_at\":{\"schema\":\"janus.instant/1\",\"time_scale\":\"posix\",\"unix_day\":%d,\"second\":%d,\"millisecond\":%d}}",logits[32],logits[33],pair[0],pair[1],letter,day,sec,ms);
    int closed=fclose(out);out=NULL;if(closed)goto done;
    if(nj_get(line,"remember") && jov_visual_remember(memory,line,answer,&receipt))goto done;
    if(receipt) {answer[answer_length-1]=0;printf("%s,\"memory\":%s}\n",answer,receipt);}
    else printf("%s\n",answer);
    rc=ferror(stdout) || fflush(stdout);
done:
    if(out)fclose(out);
    free(answer);free(receipt);
    if(cache)nt_arch_qwen35.kv_free(model,cache);
    free(id);free(question);free(a);free(b);free(path);free(want);free(rgb);free(features);free(ids);free(positions);free(rows);nt_qwen35_image_free(&im);
    return rc;
}

int jov_visual_from_memory(const char *line,size_t bytes,void *model,bpe_tokenizer *tok,
    float *logits,const char *weights,const char *tokenizer,const char *memory,int comparison) {
    const char *request=nj_get(line,"recall");long long through=-1;
    char *repository=field(request,"repository",128),*key=field(request,"key",128);
    char *id=field(line,"id",256),*question=field(line,"question",4096),*a=field(line,"choice_a",2048),*b=field(line,"choice_b",2048);
    char *receipt=NULL,*old_question=NULL,*value=NULL,*state=NULL;int *ids=NULL;kv_cache *cache=NULL;int rc=1;
    if(comparison) {
        if(jov_visual_comparison(memory,line,&receipt))goto done;
        question=aml_text("visual_question");a=aml_text("visual_a");
        b=aml_text("visual_b");state=aml_text("visual_state");
        if(!id || !question || !a || !b || !state)goto done;
    } else {
        if(!repository || !key || !id || !question || !a || !b || !strcmp(a,b) || nj_get(line,"image") || nj_get(line,"remember") || nj_get(line,"compare") ||
           (nj_get(request,"through") && nj_int(nj_get(request,"through"),&through)) || through < -1 || through>256 ||
           jov_visual_remembered(memory,repository,key,(int)through,&receipt))goto done;
        const char *obs=nj_get(nj_get(receipt,"origin"),"observation");
        old_question=field(obs,"question",4096);
        value=field(obs,nj_is(nj_get(obs,"letter"),"A")?"choice_a":"choice_b",2048);
        if(!old_question || !value)goto done;
        size_t length=0;FILE *out=open_memstream(&state,&length);if(!out)goto done;
        fputs("Recorded image observation:\n",out);
        json_field(out,"question",old_question);fputc('\n',out);json_field(out,"observed_answer",value);
        if(fclose(out))goto done;
    }
    if(am_set_var_text("visual_state",state) || am_set_var_text("visual_question",question) ||
       am_set_var_text("visual_a",a) || am_set_var_text("visual_b",b) || visual_aml("aml/visual-recall.aml"))goto done;
    const char *prompt=am_get_var_text("prompt"),*body=am_get_var_text("visual_recall_text");char ih[65],ph[65];
    if(!prompt || !body || hash_bytes(line,bytes,ih) || hash_bytes(prompt,strlen(prompt),ph))goto done;
    const char *begin=strstr(prompt,"<state>\n");if(!begin)goto done;
    begin+=strlen("<state>\n");if(strncmp(begin,body,strlen(body)))goto done;
    size_t capacity=strlen(prompt)*2+16;
    ids=malloc(capacity*sizeof(*ids));if(!ids)goto done;
    int n=jov_literal_span_ids(tok,prompt,begin,strlen(body),ids,(int)capacity);
    if(n<1 || n>8192 || !(cache=nt_arch_qwen35.kv_new(model,n)))goto done;
    for(int pos=0;pos<n;pos+=32) {
        int take=n-pos<32?n-pos:32;
        if(nt_arch_qwen35.forward(model,cache,ids+pos,take,pos,pos+take==n?logits:NULL))goto done;
    }
    float pair[2]={logits[32],logits[33]};
    if(!isfinite(pair[0]) || !isfinite(pair[1]) || am_set_var_array("choice_logits",pair,2) || visual_aml("aml/score-choices.aml"))goto done;
    int count=0;const float *p=am_get_var_array("probabilities",&count);if(!p || count!=2)goto done;
    fputs("{\"schema\":",stdout);json_string(stdout,comparison?"jovovich.visual-review/1":"jovovich.visual-recall/1");
    fputc(',',stdout);json_field(stdout,"id",id);
    fputc(',',stdout);json_field(stdout,"question",question);fputc(',',stdout);json_field(stdout,"choice_a",a);fputc(',',stdout);json_field(stdout,"choice_b",b);
    printf(",\"input_sha256\":\"%s\",\"prompt_sha256\":\"%s\",\"weights_sha256\":\"%s\",\"tokenizer_sha256\":\"%s\",",ih,ph,weights,tokenizer);
    const char *letter=p[0]>=p[1]?"A":"B";
    if(comparison) {
        int reverse=nj_is(nj_get(line,"concern_letter"),"B");
        float concern=p[reverse],clean=p[1-reverse];int found=concern>=clean;
        letter=(found?!reverse:reverse)?"A":"B";
        printf("\"verdict\":\"%s\",\"concern\":%.9g,\"clean\":%.9g,",found?"CONCERN":"CLEAN",concern,clean);
    }
    printf("\"logit_a\":%.9g,\"logit_b\":%.9g,\"p_a\":%.9g,\"p_b\":%.9g,\"letter\":\"%s\",\"%s\":%s}\n",logits[32],logits[33],p[0],p[1],letter,comparison?"comparison":"memory",receipt);
    rc=ferror(stdout) || fflush(stdout);
done:
    if(cache)nt_arch_qwen35.kv_free(model,cache);
    free(repository);free(key);free(id);free(question);free(a);free(b);free(receipt);free(old_question);free(value);free(state);free(ids);return rc;
}
