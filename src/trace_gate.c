#include "trace_gate.h"
#include "ariannamethod.h"
#include "hash.h"
#include "report_json.h"
#include <limits.h>

enum { MAX_RUNS=64, MAX_CALLS=32, NAME_BYTES=64, EFFECT_BYTES=MAX_CALLS*(NAME_BYTES+6) };

static int identifier(const char *s) {
    const char *letters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_";
    if(!s || !*s || !strchr(letters,*s) || strlen(s)>=NAME_BYTES)return 0;
    for(s++;*s;s++)if(!strchr(letters,*s) && (*s<'0' || *s>'9'))return 0;
    return 1;
}

/* Compare the actual observations after projecting them onto the rule's
 * observable. Identifiers contain no spaces, so the sequence encoding is unique. */
static int effect(const char *calls,const char *target,char text[EFFECT_BYTES]) {
    if(!calls || *calls!='[')return 1;
    int bad=0,length=0,count=0;
    size_t used=0;
    for(const char *v=nj_first(calls,&bad);v;v=nj_next(v,']',&bad)) {
        char *name=nj_string(v);
        if(!identifier(name) || ++length>MAX_CALLS){free(name);return 1;}
        if(target)count+=!strcmp(target,name);
        else {
            int n=snprintf(text+used,EFFECT_BYTES-used,"%s%s",used?" then ":"",name);
            if(n<0 || (size_t)n>=EFFECT_BYTES-used){free(name);return 1;}
            used+=(size_t)n;
        }
        free(name);
    }
    if(target)snprintf(text,EFFECT_BYTES,"%d",count);
    else if(!length)strcpy(text,"(none)");
    return bad;
}

static int expected_effect(const char *value,const char *target,char text[EFFECT_BYTES]) {
    if(!target)return effect(value,NULL,text);
    long long count;
    if(nj_int(value,&count) || count<0 || count>INT_MAX)return 1;
    snprintf(text,EFFECT_BYTES,"%lld",count);return 0;
}

static int bound_to_review(const char *row,const char *g,const char *id,const char *rule,const char *change) {
    char h[65];
    if(!nj_is(nj_get(g,"schema"),"jovovich.paired-traces/1") || !nj_is(nj_get(g,"review_id"),id) ||
       hash_bytes(rule,strlen(rule),h) || !nj_is(nj_get(g,"rule_sha256"),h) ||
       hash_bytes(change,strlen(change),h) || !nj_is(nj_get(g,"change_sha256"),h))return 0;
    const char *src=nj_get(row,"source");
    const char *keys[]={"base_commit","head_commit"};
    for(int k=0;k<2;k++) {
        if(!src) {if(nj_get(g,keys[k]))return 0;continue;}
        char *oid=nj_string(nj_get(src,keys[k]));
        int ok=oid && nj_is(nj_get(g,keys[k]),oid);free(oid);
        if(!ok)return 0;
    }
    return 1;
}

int jov_apply_trace_gate(const char *row,const char *id,const char *rule,const char *change,
                         jov_trace_receipt *r) {
    const char *g=nj_get(row,"trace_evidence");
    if(!g)return 0;
    const char *end=report_json_end(row,0);
    if(!end || *nj_ws(end) || !bound_to_review(row,g,id,rule,change))return 1;
    const char *kind=nj_get(g,"metric"),*raw_target=nj_get(g,"target"),*runs=nj_get(g,"runs");
    char *target=nj_string(raw_target);
    int count=nj_is(kind,"count"),bad=0,seen[MAX_RUNS];
    if(!runs || *runs!='[' || (count?!identifier(target):(!nj_is(kind,"sequence") || raw_target))) {
        free(target);return 1;
    }
    char required[EFFECT_BYTES],head[EFFECT_BYTES],selected_required[EFFECT_BYTES],selected_head[EFFECT_BYTES];
    memset(r,0,sizeof(*r));
    for(const char *v=nj_first(runs,&bad);v;v=nj_next(v,']',&bad)) {
        long long mode;char base[EFFECT_BYTES];
        if(r->runs>=MAX_RUNS || nj_int(nj_get(v,"mode"),&mode) || mode<INT_MIN || mode>INT_MAX ||
           effect(nj_get(v,"base"),target,base) || effect(nj_get(v,"head"),target,head) ||
           expected_effect(nj_get(v,"required"),target,required)){bad=1;break;}
        for(int i=0;i<r->runs;i++)if(seen[i]==(int)mode)bad=1;
        if(bad)break;
        seen[r->runs++]=(int)mode;
        if(!strcmp(base,head))continue;
        if(!r->differing || mode<r->selected_mode) {
            r->selected_mode=(int)mode;strcpy(selected_required,required);strcpy(selected_head,head);
        }
        r->differing++;
    }
    if(!bad && r->differing) {
        char metric[96],mode[32];
        if(target)snprintf(metric,sizeof(metric),"number of calls to %s",target);
        else strcpy(metric,"callback sequence");
        snprintf(mode,sizeof(mode),"%d",r->selected_mode);
        bad=am_set_var_text("gate_mode",mode) || am_set_var_text("gate_metric",metric) ||
            am_set_var_text("gate_required",selected_required) || am_set_var_text("gate_observed",selected_head) ||
            am_exec_file("aml/trace-witness.aml");
        const char *obs=am_get_var_text("observation");
        if(!obs || strlen(obs)>=sizeof(r->observation))bad=1;
        else strcpy(r->observation,obs);
    }
    free(target);return bad;
}

int jov_verify_trace_receipt(const char *listed,const jov_trace_receipt *r,const char *prompt) {
    long long n;
    char h[65];
    if(!listed || !prompt || !nj_is(nj_get(listed,"policy"),"paired-trace-diff/1") ||
       hash_bytes(prompt,strlen(prompt),h) || !nj_is(nj_get(listed,"prompt_sha256"),h) ||
       nj_int(nj_get(listed,"runs"),&n) || n!=r->runs ||
       nj_int(nj_get(listed,"differing"),&n) || n!=r->differing)return 1;
    const char *mode=nj_get(listed,"selected_mode"),*obs=nj_get(listed,"observation");
    if(!r->differing)return mode || obs;
    return nj_int(mode,&n) || n!=r->selected_mode || !nj_is(obs,r->observation);
}
