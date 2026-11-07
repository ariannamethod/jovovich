/* Exhaust the two-input domain of the execution-trace transfer fixtures. */
#include "ariannamethod.h"
#include "json.h"
#include "hash.h"
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char *api, *source;
    void (*execute)(int);
} implementation;

typedef struct {
    const implementation *source[2];
    const char *first, *second;
    int witness_mode, control_value;
} fixture;

enum { ORDER, COUNT };
enum { SOURCE, CONTROL, OBSERVED, WITNESS, EXPECTED, RECEIPTS };

static const char *events[4];
static size_t event_count;

static void fail(const char *why) {
    fprintf(stderr,"Trace corpus: %s\n",why);
    exit(EXIT_FAILURE);
}
static void record(const char *event) {
    if(event_count == sizeof(events)/sizeof(*events))fail("trace too long");
    events[event_count++]=event;
}

#define CALLBACK(name) static void name(void) { record(#name); }
CALLBACK(scan) CALLBACK(paint) CALLBACK(read_tag) CALLBACK(write_tag)
CALLBACK(pack) CALLBACK(seal) CALLBACK(mark) CALLBACK(send)
CALLBACK(pulse) CALLBACK(idle) CALLBACK(stamp) CALLBACK(pause_job)
CALLBACK(tick) CALLBACK(wait_step) CALLBACK(flush) CALLBACK(poll_io)
#undef CALLBACK

#define TRACE_BODY(symbol, api, body) \
    static void symbol##_run(int mode) body \
    static const implementation symbol={#api,"void " #api "(int mode) " #body,symbol##_run};
#include "trace_bodies.inc"
#undef TRACE_BODY

/* control_value encodes AB/BA for order and one/two for count. */
static const fixture fixtures[]={
    {{&scan_a,&scan_b},"scan","paint",1,0},
    {{&tag_a,&tag_b},"read_tag","write_tag",0,1},
    {{&pack_a,&pack_b},"pack","seal",1,1},
    {{&mark_a,&mark_b},"mark","send",0,0},
    {{&pulse_a,&pulse_b},"pulse","idle",1,0},
    {{&stamp_a,&stamp_b},"stamp","pause_job",0,1},
    {{&tick_a,&tick_b},"tick","wait_step",1,1},
    {{&flush_a,&flush_b},"flush","poll_io",0,0}
};

typedef struct {
    char required[64], observed[64];
    const char *calls[2];
} measurement;

static void measure(const fixture *f,int family,int rule,int body,int mode,measurement *m) {
    int value=mode==f->witness_mode ? rule : f->control_value;
    event_count=0;
    f->source[body]->execute(mode);
    if(event_count!=2)fail("unexpected number of instrumented events");
    memcpy(m->calls,events,sizeof(m->calls));
    if(family==ORDER) {
        snprintf(m->required,sizeof(m->required),"%s then %s",
                 value?f->second:f->first,value?f->first:f->second);
        snprintf(m->observed,sizeof(m->observed),"%s then %s",events[0],events[1]);
    } else {
        int count=0;
        for(size_t i=0;i<event_count;i++)count+=strcmp(events[i],f->first)==0;
        snprintf(m->required,sizeof(m->required),"%d",1+value);
        snprintf(m->observed,sizeof(m->observed),"%d",count);
    }
}

static void callback_pair(const char *first,const char *second) {
    fputc('[',stdout);json_string(stdout,first);fputc(',',stdout);
    json_string(stdout,second);fputc(']',stdout);
}

static void emit_gate(const fixture *f,int family,int body,int contract,int mask,const char *id,
                      const char *rule,const measurement head[2]) {
    char rh[65],ch[65];
    const char *source=f->source[body]->source;
    if(hash_bytes(rule,strlen(rule),rh) || hash_bytes(source,strlen(source),ch))fail("input digest");
    fputs(",\"trace_evidence\":{\"schema\":\"jovovich.paired-traces/1\",",stdout);
    json_field(stdout,"review_id",id);printf(",\"rule_sha256\":\"%s\",\"change_sha256\":\"%s\",",rh,ch);
    json_field(stdout,"metric",family==COUNT?"count":"sequence");
    if(family==COUNT){fputc(',',stdout);json_field(stdout,"target",f->first);}
    fputs(",\"runs\":[",stdout);
    int seen=0;
    for(int mode=0;mode<2;mode++)if(mask & (1<<mode)) {
        measurement base;measure(f,family,contract,1-body,mode,&base);
        if(seen++)fputc(',',stdout);
        printf("{\"mode\":%d,\"base\":",mode);callback_pair(base.calls[0],base.calls[1]);
        fputs(",\"head\":",stdout);callback_pair(head[mode].calls[0],head[mode].calls[1]);
        fputs(",\"required\":",stdout);
        if(family==COUNT)fputs(head[mode].required,stdout);
        else {
            int reverse=mode==f->witness_mode?contract:f->control_value;
            callback_pair(reverse?f->second:f->first,reverse?f->first:f->second);
        }
        fputc('}',stdout);
    }
    fputs("]}",stdout);
}

static void emit_input(int arm,int family,const fixture *f,int body,const char *id,
                       const char *file,const measurement m[2],int contract,int mask) {
    int mode=arm==CONTROL ? 1-f->witness_mode : f->witness_mode;
    const implementation *impl=f->source[body];
    float config[]={(float)family,(float)arm};
    if(am_set_var_array("trace_config",config,2) || am_set_var_text("api",impl->api) ||
       am_set_var_text("target",f->first) || am_set_var_text("file",file) ||
       am_set_var_text("source_code",impl->source) || am_set_var_text("mode_text",mode?"1":"0") ||
       am_set_var_text("required_zero",m[0].required) || am_set_var_text("required_one",m[1].required) ||
       am_set_var_text("required_value",m[mode].required) || am_set_var_text("observed_value",m[mode].observed) ||
       am_exec_file("aml/execution-traces.aml"))fail(am_get_error());
    const char *rule=am_get_var_text("rule"),*context=am_get_var_text("review_context");
    if(!rule || !context)fail("missing AML text");
    fputc('{',stdout);json_field(stdout,"id",id);fputc(',',stdout);json_field(stdout,"file",file);
    fputc(',',stdout);json_field(stdout,"context",context);fputc(',',stdout);json_field(stdout,"rule_excerpt",rule);
    fputc(',',stdout);json_field(stdout,"change_excerpt",impl->source);
    if(mask)emit_gate(f,family,body,contract,mask,id,rule,m);
    puts("}");
}

static void emit_receipt(const char *id,const measurement m[2]) {
    fputc('{',stdout);json_field(stdout,"id",id);fputs(",\"executions\":[",stdout);
    for(int mode=0;mode<2;mode++) {
        if(mode)fputc(',',stdout);
        printf("{\"mode\":%d,\"calls\":[",mode);
        json_string(stdout,m[mode].calls[0]);fputc(',',stdout);json_string(stdout,m[mode].calls[1]);
        fputs("],",stdout);json_field(stdout,"required",m[mode].required);fputc(',',stdout);
        json_field(stdout,"observed",m[mode].observed);fputc('}',stdout);
    }
    puts("]}");
}

/* This entry point renders source-only selector tasks without running a fixture. */
static int emit_choices(void) {
    for(size_t i=0;i<sizeof(fixtures)/sizeof(*fixtures);i++) {
        const fixture *f=fixtures+i;
        for(int flip=0;flip<2;flip++)for(int mode_a=0;mode_a<2;mode_a++) {
            printf("{\"id\":\"select-%zu-%d-%d\",\"mode_a\":%d,",i,flip,mode_a,mode_a);
            json_field(stdout,"first_body",f->source[flip]->source);fputc(',',stdout);
            json_field(stdout,"second_body",f->source[1-flip]->source);fputc(',',stdout);
            json_field(stdout,"metric",i<4?"sequence":"count");
            if(i>=4){fputc(',',stdout);json_field(stdout,"target",f->first);}
            puts("}");
        }
    }
    return fflush(stdout)==EOF || ferror(stdout);
}

static int distinguishing_modes(void) {
    for(size_t i=0;i<sizeof(fixtures)/sizeof(*fixtures);i++) {
        int found=-1;
        for(int m=0;m<2;m++) {
            measurement a,b;
            measure(fixtures+i,i<4?ORDER:COUNT,0,0,m,&a);measure(fixtures+i,i<4?ORDER:COUNT,0,1,m,&b);
            if(strcmp(a.observed,b.observed)) {
                if(found>=0)fail("ambiguous distinguishing mode");
                found=m;
            }
        }
        if(found<0)fail("no distinguishing mode");
        fputc('0'+found,stdout);
    }
    puts("");return fflush(stdout)==EOF || ferror(stdout);
}

int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"choices"))return emit_choices();
    if(argc==2 && !strcmp(argv[1],"distinguishing"))return distinguishing_modes();
    int paired=argc>=2 && !strcmp(argv[1],"paired");
    const char *modes=NULL;
    if(paired && argc==3) {
        modes=argv[2];
        if(strlen(modes)!=sizeof(fixtures)/sizeof(*fixtures) || strspn(modes,"01")!=strlen(modes))
            fail("expected one binary mode per fixture");
    }
    const char *names[]={"source","control","observed","witness","expected","receipts"};
    int arm=SOURCE;
    while(!paired && argc==2 && arm<=RECEIPTS && strcmp(argv[1],names[arm]))arm++;
    if((argc!=2 && !modes) || arm>RECEIPTS)fail("expected source|control|observed|witness|expected|receipts|choices|distinguishing|paired [MODES]");
    am_init();am_persistent_mode(1);
    for(size_t i=0;i<sizeof(fixtures)/sizeof(*fixtures);i++) {
        const fixture *f=fixtures+i;
        int family=i<4?ORDER:COUNT;
        for(int rule=0;rule<2;rule++)for(int body=0;body<2;body++) {
            char id[24],file[64];measurement m[2];
            snprintf(id,sizeof(id),"trace-%02zu",4*i+2*rule+body);
            snprintf(file,sizeof(file),"%s.c",f->source[body]->api);
            for(int mode=0;mode<2;mode++)measure(f,family,rule,body,mode,m+mode);
            int control=1-f->witness_mode;
            if(strcmp(m[control].observed,m[control].required))fail("control differs across bodies");
            int violation=strcmp(m[f->witness_mode].observed,m[f->witness_mode].required)!=0;
            if(violation!=(rule!=body))fail("compiled body does not realize the planned crossover");
            if(arm==EXPECTED)
                printf("{\"id\":\"%s\",\"split\":\"transfer\",\"family\":\"%s\",\"expected\":\"%s\"}\n",
                       id,family==ORDER?"order":"count",violation?"CONCERN":"CLEAN");
            else if(arm==RECEIPTS)emit_receipt(id,m);
            else {
                int mask=modes?(1<<(modes[i]-'0')):(paired?3:0);
                emit_input(arm,family,f,body,id,file,m,rule,mask);
            }
        }
    }
    am_persistent_mode(0);
    return fflush(stdout)==EOF || ferror(stdout);
}
