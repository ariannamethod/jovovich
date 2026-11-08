#include "trace_gate.h"
#include "ariannamethod.h"
#include "hash.h"
#include "report_json.h"
#include <limits.h>

enum { MAX_RUNS=64, MAX_CALLS=32, NAME_BYTES=64, EFFECT_BYTES=MAX_CALLS*(NAME_BYTES+6) };

static int hex_field(const char *json, const char *key, int git_id, char out[65]) {
    char *s = nj_string(nj_get(json, key));
    size_t n = s ? strlen(s) : 0;
    int ok = (n == 64 || (git_id && n == 40)) && strspn(s, "0123456789abcdef") == n;
    if (ok) memcpy(out, s, n + 1);
    free(s);
    return ok;
}

int jov_replay_ref_read(const char *json, jov_replay_ref *r) {
    memset(r, 0, sizeof(*r));
    if (!json) return 0;
    long long mode;
    if (!nj_is(nj_get(json, "schema"), "jovovich.replayed-mode/1") ||
        !hex_field(json, "base_commit", 1, r->base) || !hex_field(json, "head_commit", 1, r->head) ||
        strlen(r->base) != strlen(r->head) || !hex_field(json, "input_sha256", 0, r->source_sha) ||
        !hex_field(json, "harness_sha256", 0, r->harness_sha) ||
        nj_int(nj_get(json, "mode"), &mode) || mode < INT_MIN || mode > INT_MAX) return 1;
    r->mode = (int)mode;
    return 0;
}

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

typedef enum { INVALID, SEQUENCE, COUNT, TEXT } metric_kind;

static metric_kind metric(const char *json) {
    const char *kind = nj_get(json, "metric");
    if (nj_is(kind, "sequence")) return SEQUENCE;
    if (nj_is(kind, "count")) return COUNT;
    if (nj_is(kind, "text")) return TEXT;
    return INVALID;
}

/* One canonical quoted representation for a short single-line program result. */
static int quoted_text(const char *value, char out[EFFECT_BYTES]) {
    char *s = nj_string(value);
    if (!s || strlen(s) > 256) { free(s); return 1; }
    /* A quoted program result cannot introduce an AML prompt delimiter. */
    char *w = out;
    *w++ = '"';
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p < 32 || *p > 126) { free(s); return 1; }
        if (*p == '<' || *p == '>') {
            memcpy(w, *p == '<' ? "\\u003c" : "\\u003e", 6);
            w += 6;
            continue;
        }
        if (*p == '"' || *p == '\\') *w++ = '\\';
        *w++ = (char)*p;
    }
    *w++ = '"';
    *w = 0;
    free(s);
    return 0;
}

static int project(const char *value, metric_kind kind, const char *target, int required,
                   char out[EFFECT_BYTES]) {
    if (kind == TEXT) return quoted_text(value, out);
    if (kind == COUNT && required) {
        long long count;
        if (nj_int(value,&count) || count<0 || count>INT_MAX) return 1;
        snprintf(out,EFFECT_BYTES,"%lld",count);
        return 0;
    }
    return effect(value,target,out);
}

static int same_effect(const char *saved, const char *fresh, metric_kind kind,
                       const char *target, int required) {
    char a[EFFECT_BYTES], b[EFFECT_BYTES];
    return !project(saved,kind,target,required,a) && !project(fresh,kind,target,required,b) && !strcmp(a,b);
}

/* On count metrics, capture rechecks the complete sequence, including calls
 * outside the projection. Every capture re-reads the requirement oracle. */
int jov_trace_reproduced(const char *gate, int mode, const char *base, const char *head, const char *oracle) {
    metric_kind kind = metric(gate), raw = kind == TEXT ? TEXT : SEQUENCE;
    if (kind == INVALID || kind != metric(oracle)) return 0;
    char *target = nj_string(nj_get(gate, "target"));
    int ok = kind == COUNT ? identifier(target) && nj_is(nj_get(oracle, "target"), target)
                           : !nj_get(gate, "target") && !nj_get(oracle, "target");
    int bad = 0, found = 0;
    const char *runs = nj_get(gate, "runs");
    for (const char *v=nj_first(runs,&bad); ok && v; v=nj_next(v,']',&bad)) {
        long long m;
        if (nj_int(nj_get(v,"mode"),&m)) { bad=1; break; }
        if (m != mode) continue;
        found = same_effect(nj_get(v,"base"),base,raw,NULL,0) &&
                same_effect(nj_get(v,"head"),head,raw,NULL,0) &&
                same_effect(nj_get(v,"required"),nj_get(oracle,"required"),kind,target,1);
        break;
    }
    free(target);
    return ok && !bad && found;
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
    metric_kind kind = metric(g);
    const char *raw_target=nj_get(g,"target"),*runs=nj_get(g,"runs");
    char *target=nj_string(raw_target);
    int bad=0,seen[MAX_RUNS];
    if(!runs || *runs!='[' || kind == INVALID || (kind == COUNT ? !identifier(target) : raw_target != NULL)) {
        free(target);return 1;
    }
    char required[EFFECT_BYTES],head[EFFECT_BYTES],selected_required[EFFECT_BYTES],selected_head[EFFECT_BYTES];
    memset(r,0,sizeof(*r));
    for(const char *v=nj_first(runs,&bad);v;v=nj_next(v,']',&bad)) {
        long long mode;char base[EFFECT_BYTES];
        if(r->runs>=MAX_RUNS || nj_int(nj_get(v,"mode"),&mode) || mode<INT_MIN || mode>INT_MAX ||
           project(nj_get(v,"base"),kind,target,0,base) || project(nj_get(v,"head"),kind,target,0,head) ||
           project(nj_get(v,"required"),kind,target,1,required)){bad=1;break;}
        for(int i=0;i<r->runs;i++)if(seen[i]==(int)mode)bad=1;
        if(bad)break;
        seen[r->runs++]=(int)mode;
        if(!strcmp(base,head))continue;
        if(!r->differing || mode<r->selected_mode) {
            r->selected_mode=(int)mode;strcpy(selected_required,required);strcpy(selected_head,head);
        }
        r->differing++;
    }
    const char *prior = nj_get(g, "replayed_from");
    char harness[65];
    if (nj_get(g, "harness_sha256") && !hex_field(g, "harness_sha256", 0, harness)) bad = 1;
    if (prior && (jov_replay_ref_read(prior, &r->replay) || r->runs != 1 ||
        r->replay.mode != seen[0] || !nj_is(nj_get(g, "harness_sha256"), r->replay.harness_sha) ||
        !nj_is(nj_get(nj_get(row, "fact"), "schema"), "jovovich.rule-fact/1") ||
        !nj_is(nj_get(nj_get(row, "source"), "kind"), "git"))) bad = 1;
    if(!bad && r->differing) {
        char metric[96],mode[32];
        if(target)snprintf(metric,sizeof(metric),"number of calls to %s",target);
        else strcpy(metric,kind == TEXT ? "output text" : "callback sequence");
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
    jov_replay_ref prior;
    if (jov_replay_ref_read(nj_get(listed, "replayed_from"), &prior) ||
        strcmp(prior.base, r->replay.base) || strcmp(prior.head, r->replay.head) ||
        strcmp(prior.source_sha, r->replay.source_sha) || strcmp(prior.harness_sha, r->replay.harness_sha) ||
        prior.mode != r->replay.mode) return 1;
    const char *mode=nj_get(listed,"selected_mode"),*obs=nj_get(listed,"observation");
    if(!r->differing)return mode || obs;
    char *shown = nj_string(obs);
    int bad = nj_int(mode,&n) || n!=r->selected_mode || !shown || strcmp(shown,r->observation);
    free(shown);
    return bad;
}
