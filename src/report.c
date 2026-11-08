#define _POSIX_C_SOURCE 200809L
#include "batch.h"
#include "facts.h"
#include "boundary_view.h"
#include "json.h"
#include "hash.h"
#include "report_json.h"
#include "tools/narrow_json.h"
#include "ariannamethod.h"
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define ROW_LIMIT 1048576u
static const char *source_keys[]={"base_commit","head_commit","rules_path","rules_blob","rules_sha256","diff_sha256"};
typedef struct {
    char *row,*id,*file,*context,*rule,*change,*origin[6],*batch;
    char row_hash[65];int count;
    jov_batch_item item;
    jov_fact *fact;
} input;
static int eq(const char*obj,const char*key,const char*want) {
    char*s=nj_string(nj_get(obj,key));int ok=s && want && !strcmp(s,want);free(s);return ok;
}
static int number(const char*obj,const char*key,int*value) {
    long long v;if(nj_int(nj_get(obj,key),&v) || v<INT_MIN || v>INT_MAX)return 1;
    *value=(int)v;return 0;
}
static int parse(input*p,int index) {
    p->id=nj_string(nj_get(p->row,"id"));p->file=nj_string(nj_get(p->row,"file"));
    p->context=nj_string(nj_get(p->row,"context"));p->rule=nj_string(nj_get(p->row,"rule_excerpt"));p->change=nj_string(nj_get(p->row,"change_excerpt"));
    const char*s=nj_get(p->row,"source"),*b=nj_get(p->row,"batch");
    for(int i=0;i<6;i++)p->origin[i]=nj_string(nj_get(s,source_keys[i]));
    int first,last,position;
    if(!eq(s,"kind","git") || number(s,"rule_first_line",&first) || number(s,"rule_last_line",&last) ||
       !eq(b,"schema","jovovich.git-batch/1") || !eq(b,"scope","all_changed_paths") ||
       number(b,"index",&position) || position!=index || number(b,"count",&p->count) || p->count<1 || p->count>JOV_BATCH_MAX_FILES)return 1;
    p->batch=nj_string(nj_get(b,"id"));
    p->item=(jov_batch_item){p->file,p->id,{p->origin[0],p->origin[1],p->origin[2],p->origin[3],p->origin[4],p->origin[5],first,last}};
    if (jov_fact_decode(nj_get(p->row, "fact"), &p->fact)) return 1;
    jov_review r={.fact=p->fact,.id=p->id,.model="input",.revision="input",.question="input",.file=p->file,.context=p->context,
        .rule_excerpt=p->rule,.change_excerpt=p->change,.concern=.5,.clean=.5,.source=&p->item.source};
    char h[65];
    return !p->batch || jov_review_validate(&r) || hash_bytes(p->context,strlen(p->context),h) || strcmp(h,p->id) ||
        hash_bytes(p->rule,strlen(p->rule),h) || strcmp(h,p->origin[4]) ||
        hash_bytes(p->change,strlen(p->change),h) || strcmp(h,p->origin[5]) || hash_bytes(p->row,strlen(p->row),p->row_hash);
}
static int same_policy(const input*a,const input*b) {
    if (!jov_fact_same(a->fact, b->fact)) return 0;
    for(int i=0;i<5;i++)if(strcmp(a->origin[i],b->origin[i]))return 0;
    return a->item.source.first_line==b->item.source.first_line && a->item.source.last_line==b->item.source.last_line;
}
static int answer(const char*j,const input*p,const char*manifest,float*flag,int index,int *policy) {
    const char*model=nj_get(j,"model"),*choice=nj_get(j,"choice"),*prob=nj_get(choice,"probabilities"),*in=nj_get(j,"input");
    const char*src=nj_get(j,"source"),*e=nj_get(j,"execution"),*time=nj_get(e,"reviewed_at");
    int version,first,last,day,sec,ms;double concern,clean;char *model_id=nj_string(nj_get(manifest,"model_id")),*revision=nj_string(nj_get(manifest,"revision"));
    char *wh=nj_string(nj_get(manifest,"weights_sha256")),*th=nj_string(nj_get(manifest,"tokenizer_sha256"));int rc=1;
    jov_fact *fact = NULL;
    if (jov_fact_decode(nj_get(j, "fact"), &fact) || !jov_fact_same(fact, p->fact)) goto done;
    if(!model_id || !revision || !wh || !th || number(j,"schema_version",&version) || version!=1 || !eq(j,"id",p->id) ||
       !eq(model,"id",model_id) || !eq(model,"revision",revision) || !eq(nj_get(j,"scope"),"file",p->file) ||
       !eq(in,"context",p->context) || !eq(in,"rule_excerpt",p->rule) || !eq(in,"change_excerpt",p->change) ||
       !eq(src,"kind","git") || number(src,"rule_first_line",&first) || number(src,"rule_last_line",&last) ||
       first!=p->item.source.first_line || last!=p->item.source.last_line)goto done;
    for(int i=0;i<6;i++)if(!eq(src,source_keys[i],p->origin[i]))goto done;
    if(jov_verify_boundary_view(j,p->row,p->id,p->context,p->rule,p->change,"aml/prepare.aml",index,policy) || !eq(j,"question",am_get_var_text("question")))goto done;
    if(nj_number(nj_get(prob,"CONCERN"),&concern) || nj_number(nj_get(prob,"CLEAN"),&clean) ||
       !isfinite(concern) || !isfinite(clean) || concern<0 || clean<0 || concern>1 || clean>1 || fabs(concern+clean-1)>1e-6 ||
       !eq(choice,"verdict",concern>=clean?"CONCERN":"CLEAN"))goto done;
    if(!eq(e,"engine","NoTorch") || !eq(e,"language","AML") || !eq(e,"arithmetic","float32") ||
       !eq(e,"input_sha256",p->row_hash) || !eq(e,"weights_sha256",wh) || !eq(e,"tokenizer_sha256",th) ||
       !eq(time,"schema","janus.instant/1") || !eq(time,"time_scale","posix") ||
       number(time,"unix_day",&day) || number(time,"second",&sec) || number(time,"millisecond",&ms) ||
       sec<0 || sec>=86400 || ms<0 || ms>=1000)goto done;
    *flag=concern>=clean?1:0;rc=0;
done:
    jov_fact_free(fact);
    free(model_id);free(revision);free(wh);free(th);return rc;
}
int main(int argc,char **argv) {
    int json=argc==4 && !strcmp(argv[3],"--json");
    if((argc!=3 && argc!=4) || (argc==4 && !json)){fprintf(stderr,"Usage: %s BATCH.jsonl ANSWERS.jsonl [--json]\n",argv[0]);return 2;}
    int rc=1,count=0,bad=0,policy=0;size_t total=0;FILE*batch=fopen(argv[1],"rb"),*answers=fopen(argv[2],"rb"),*out=NULL;
    char*manifest=nj_load("models/onejev-0.8b.json",NULL),*extra=NULL,*results[JOV_BATCH_MAX_FILES]={0};
    input inputs[JOV_BATCH_MAX_FILES]={{0}};jov_batch_item items[JOV_BATCH_MAX_FILES];float flags[JOV_BATCH_MAX_FILES];char digest[65], readout[65]={0};
    if(!batch || !answers || !manifest)goto done;
    for(;;) {
        char*s=report_json_row(batch,&total,&bad,ROW_LIMIT,JOV_BATCH_MAX_BYTES);if(!s)break;
        if(count==JOV_BATCH_MAX_FILES){free(s);bad=1;break;}
        input*p=inputs+count;p->row=s;
        if(parse(p,count))goto done;
        if(count && (p->count!=inputs[0].count || strcmp(p->batch,inputs[0].batch) || !same_policy(p,inputs)))goto done;
        for(int i=0;i<count;i++)if(!strcmp(p->file,inputs[i].file))goto done;
        items[count]=p->item;count++;
    }
    if(bad || !count || count!=inputs[0].count || jov_batch_digest_fact(items,count,inputs[0].fact,digest) || strcmp(digest,inputs[0].batch))goto done;
    am_init();am_persistent_mode(1);total=0;
    for(int i=0;i<count;i++) {
        results[i]=report_json_row(answers,&total,&bad,ROW_LIMIT,JOV_BATCH_MAX_BYTES);
        if(bad || !results[i] || report_readout(results[i],i,readout) || answer(results[i],inputs+i,manifest,flags+i,i,&policy))goto done;
    }
    extra=report_json_row(answers,&total,&bad,ROW_LIMIT,JOV_BATCH_MAX_BYTES);if(extra || bad)goto done;
    if(am_set_var_array("file_concerns",flags,count) || am_exec_file("aml/report.aml"))goto done;
    const char*verdict=am_get_var_text("report_verdict");float raw_concern=am_get_var_float("concern_files");
    if(!isfinite(raw_concern) || raw_concern<0 || raw_concern>count || raw_concern!=truncf(raw_concern))goto done;
    int concern=(int)raw_concern;
    if(!verdict || (strcmp(verdict,"CLEAN") && strcmp(verdict,"CONCERN")) || am_get_var_float("reviewed_files")!=count || concern<0 || concern>count)goto done;
    out=tmpfile();if(!out)goto done;
    if(json) {
    fputs("{\"schema\":\"jovovich.review-report/1\",\"scope\":\"all_changed_paths\",",out);json_field(out,"batch_id",digest);
    fputc(',',out);json_field(out,"base_commit",inputs[0].origin[0]);fputc(',',out);json_field(out,"head_commit",inputs[0].origin[1]);
    if(policy){fputc(',',out);json_field(out,"boundary_policy","signed-int-comparison/1");}
    if(*readout){fputc(',',out);json_field(out,"readout_sha256",readout);}
    fputs(",\"summary\":{",out);json_field(out,"verdict",verdict);
    fprintf(out,",\"reviewed_files\":%d,\"concern_files\":%d,\"clean_files\":%d},\"reviews\":[",count,concern,count-concern);
    for(int i=0;i<count;i++){if(i)fputc(',',out);fputs(results[i],out);}fputs("]}\n",out);
    }else {
        fprintf(out,"**JOVOVICH · %s**\n\nReviewed files: %d · CONCERN: %d · CLEAN: %d\n\nBatch: `%s`\n",verdict,count,concern,count-concern,digest);
        for(int i=0;i<count;i++) {
            input*p=inputs+i;const char*prob=nj_get(nj_get(results[i],"choice"),"probabilities");double a,b;
            char*model_id=nj_string(nj_get(manifest,"model_id")),*revision=nj_string(nj_get(manifest,"revision")),*question=nj_string(nj_get(results[i],"question"));
            int failed=!model_id || !revision || !question || nj_number(nj_get(prob,"CONCERN"),&a) || nj_number(nj_get(prob,"CLEAN"),&b);
            if(!failed) {
                jov_review r={.fact=p->fact,.id=p->id,.model=model_id,.revision=revision,.question=question,.file=p->file,.context=p->context,
                    .rule_excerpt=p->rule,.change_excerpt=p->change,.concern=a,.clean=b,.source=&p->item.source};
                const char *view=nj_get(nj_get(results[i],"execution"),"boundary_view");
                const char *listed=nj_get(view,"code");
                char *code=nj_string(listed);
                const char *trace=nj_get(nj_get(results[i],"execution"),"trace_witness");
                const char *raw_obs=nj_get(trace,"observation");
                char *obs=nj_string(raw_obs);
                fputs("\n---\n\n",out);failed=(listed && !code) || (raw_obs && !obs) ||
                    jov_review_markdown_evidence(out,&r,code,obs);
                jov_replay_ref prior;
                if (jov_replay_ref_read(nj_get(trace, "replayed_from"), &prior)) failed = 1;
                else jov_replay_ref_markdown(out, &prior);
                free(code);free(obs);
            }
            free(model_id);free(revision);free(question);if(failed)goto done;
        }
    }
    if(ferror(out) || fseek(out,0,SEEK_SET))goto done;
    char buf[8192];size_t n;while((n=fread(buf,1,sizeof(buf),out)))if(fwrite(buf,1,n,stdout)!=n)break;
    rc=ferror(out) || ferror(stdout) || fflush(stdout);
done:
    if(rc)fprintf(stderr,"Incomplete or inconsistent batch: no review report published\n");
    if(batch)fclose(batch);
    if(answers)fclose(answers);
    if(out && fclose(out))rc=1;
    for(int i=0;i<JOV_BATCH_MAX_FILES;i++){input*p=inputs+i;jov_fact_free(p->fact);free(p->row);free(p->id);free(p->file);free(p->context);free(p->rule);free(p->change);free(p->batch);for(int j=0;j<6;j++)free(p->origin[j]);free(results[i]);}
    free(manifest);free(extra);am_persistent_mode(0);return rc?1:0;
}
