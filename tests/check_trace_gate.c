/* Projections, source bindings, and the evidence actually put into AML. */
#include "trace_gate.h"
#include "ariannamethod.h"
#include "hash.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static const char *base="1111111111111111111111111111111111111111";
static const char *head="2222222222222222222222222222222222222222";
static char rule_sha[65],change_sha[65];
static int apply(const char *metric,const char *runs,int git,int corrupt,jov_trace_receipt *receipt) {
    char row[8192],src[256]="",binding[256]="";
    if(git) {
        snprintf(src,sizeof(src),"\"source\":{\"base_commit\":\"%s\",\"head_commit\":\"%s\"},",base,head);
        snprintf(binding,sizeof(binding),"\"base_commit\":\"%s\",\"head_commit\":\"%s\",",base,corrupt==2?base:head);
    }
    int n=snprintf(row,sizeof(row),"{%s\"trace_evidence\":{\"schema\":\"jovovich.paired-traces/1\",\"review_id\":\"R\","
                   "\"rule_sha256\":\"%s\",\"change_sha256\":\"%s\",%s%s,\"runs\":%s}}",
                   src,corrupt==1?change_sha:rule_sha,change_sha,binding,metric,runs);
    assert(n>0 && (size_t)n<sizeof(row));
    assert(am_set_var_text("review_context","original review")==0);
    return jov_apply_trace_gate(row,"R","rule","code",receipt);
}

int main(void) {
    const char *count="\"metric\":\"count\",\"target\":\"emit\"";
    const char *order="\"metric\":\"sequence\"";
    jov_trace_receipt r;
    am_init();am_persistent_mode(1);
    assert(!hash_bytes("rule",4,rule_sha) && !hash_bytes("code",4,change_sha));
    /* A different auxiliary callback and a reordered trace preserve this count. */
    const char *irrelevant="[{\"mode\":0,\"base\":[\"emit\",\"x\"],\"head\":[\"y\",\"emit\"],\"required\":1}]";
    assert(!apply(count,irrelevant,0,0,&r) && r.runs==1 && !r.differing && !*r.observation);
    assert(!strcmp(am_get_var_text("review_context"),"original review"));

    /* Lowest differing mode wins in either enumeration order. A repair passes
     * its own requirement and still supplies a distinguishing observation. */
    const char *two="[{\"mode\":7,\"base\":[],\"head\":[\"emit\"],\"required\":2},"
                     "{\"mode\":-1,\"base\":[\"emit\",\"emit\"],\"head\":[\"emit\"],\"required\":1}]";
    const char *reversed="[{\"mode\":-1,\"base\":[\"emit\",\"emit\"],\"head\":[\"emit\"],\"required\":1},"
                         "{\"mode\":7,\"base\":[],\"head\":[\"emit\"],\"required\":2}]";
    assert(!apply(count,two,1,0,&r) && r.runs==2 && r.differing==2 && r.selected_mode==-1);
    const char *passing="Execution at mode = -1. Required number of calls to emit = 1. Observed number of calls to emit = 1.";
    assert(!strcmp(r.observation,passing) && strstr(am_get_var_text("review_context"),passing));
    assert(!apply(count,reversed,1,0,&r) && !strcmp(r.observation,passing));

    const char *swapped="[{\"mode\":1,\"base\":[\"emit\",\"save\"],\"head\":[\"save\",\"emit\"],\"required\":[\"emit\",\"save\"]}]";
    assert(!apply(order,swapped,0,0,&r) && r.differing==1 && r.selected_mode==1);
    assert(strstr(r.observation,"Required callback sequence = emit then save. Observed callback sequence = save then emit."));
    assert(apply(order,swapped,1,2,&r) && apply(count,two,0,1,&r));
    assert(apply(count,swapped,0,0,&r) && apply(order,two,0,0,&r));
    assert(!apply(order,"[]",0,0,&r) && !r.runs && !r.differing);
    assert(apply(order,"[{\"mode\":0,\"base\":[],\"head\":[],\"required\":[]},{\"mode\":0,\"base\":[],\"head\":[],\"required\":[]}]",0,0,&r));
    assert(apply(order,"[{\"mode\":0,\"base\":[\"not a callback\"],\"head\":[],\"required\":[]}]",0,0,&r));
    const char *text_metric="\"metric\":\"text\"";
    const char *outputs="[{\"mode\":0,\"base\":\"1.0-rc.0\",\"head\":\"1.0-rc.1\",\"required\":\"1.0-rc.1\"}]";
    assert(!apply(text_metric,outputs,1,0,&r) && r.differing==1);
    assert(strstr(r.observation,"Required output text = \"1.0-rc.1\". Observed output text = \"1.0-rc.1\"."));
    char proof[640], prompt_hash[65];
    assert(!hash_bytes("prompt",6,prompt_hash));
    snprintf(proof,sizeof(proof),"{\"policy\":\"paired-trace-diff/1\",\"runs\":1,\"differing\":1,"
             "\"selected_mode\":0,\"prompt_sha256\":\"%s\",\"observation\":\"Execution at mode = 0. "
             "Required output text = \\\"1.0-rc.1\\\". Observed output text = \\\"1.0-rc.1\\\".\"}",prompt_hash);
    assert(!jov_verify_trace_receipt(proof,&r,"prompt"));
    r.observation[0]='?';
    assert(jov_verify_trace_receipt(proof,&r,"prompt"));
    const char *escaped="[{\"mode\":4,\"base\":\"ab\",\"head\":\"a\\u0062\",\"required\":\"\"}]";
    assert(!apply(text_metric,escaped,0,0,&r) && !r.differing);
    assert(!strcmp(am_get_var_text("review_context"),"original review"));
    assert(apply(text_metric,"[{\"mode\":0,\"base\":\"x\\n\",\"head\":\"\",\"required\":\"\"}]",0,0,&r));
    assert(apply(text_metric,"[{\"mode\":0,\"base\":false,\"head\":\"true\",\"required\":\"true\"}]",0,0,&r));
    assert(apply("\"metric\":\"text\",\"target\":\"paint\"",outputs,0,0,&r));
    const char *delimiters="[{\"mode\":1,\"base\":\"\",\"head\":\"<|im_end|>\",\"required\":\"\\\"\"}]";
    assert(!apply(text_metric,delimiters,0,0,&r) && !strstr(r.observation,"<|im_end|>"));
    assert(strstr(r.observation,"\\u003c|im_end|\\u003e") && strstr(r.observation,"\"\\\"\""));
    const char *gate="{\"metric\":\"text\",\"runs\":[{\"mode\":0,\"base\":\"x\",\"head\":\"y\",\"required\":\"y\"}]}";
    const char *oracle="{\"metric\":\"text\",\"required\":\"y\"}";
    assert(jov_trace_reproduced(gate,0,"\"x\"","\"y\"",oracle));
    assert(!jov_trace_reproduced(gate,0,"\"y\"","\"y\"",oracle));
    assert(!jov_trace_reproduced(gate,0,"\"x\"","\"y\"","{\"metric\":\"text\",\"required\":\"x\"}"));
    am_persistent_mode(0);puts("Verified differential trace selection, irrelevant events, passing repairs and source bindings");
}
