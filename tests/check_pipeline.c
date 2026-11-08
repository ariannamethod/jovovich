#define _POSIX_C_SOURCE 200809L
#include "../src/git_context.h"
#include "../src/report_json.h"
#include "sha256.h"
#include <math.h>

static int checks;
#define CHECK(x) do { checks++; if(!(x)){fprintf(stderr,"FAIL line %d: %s; AML: %s\n",__LINE__,#x,am_get_error());exit(1);} } while(0)
static ssize_t record(FILE *f,char **line,size_t *capacity) {
    ssize_t n=getline(line,capacity,f);
    if(n<0){CHECK(!ferror(f));return n;}
    const char *end=memchr(*line,0,(size_t)n)?NULL:report_json_end(*line,0);
    CHECK(end && !*nj_ws(end));
    return n;
}
static char *str(const char *obj,const char *key){char *s=nj_string(nj_get(obj,key));CHECK(s);return s;}
static double num(const char *obj,const char *key){double v;CHECK(!nj_number(nj_get(obj,key),&v));return v;}
static void equal(const char *a,const char *b){CHECK(a && b && !strcmp(a,b));}
static void field_equal(const char *a,const char *b,const char *key){char*x=str(a,key),*y=str(b,key);equal(x,y);free(x);free(y);}
static const AML_Var *leaf(const AM_Record *r,const char *key){AM_String*k=am_string_new(key);CHECK(k);const AML_Var*v=am_record_get(r,k);am_string_free(k);CHECK(v);return v;}
static void digest(const void *data,size_t len,char out[65]){unsigned char h[32];CHECK(!nt_sha256(data,len,h));for(int i=0;i<32;i++)snprintf(out+2*i,3,"%02x",h[i]);}
static void clock_check(int day,int second,int millisecond){
    const AM_Record*r=am_get_var_record("reviewed_at");CHECK(r);
    const AML_Var*v=leaf(r,"schema");CHECK(v->type==AML_TYPE_STRING);equal(v->string->data,"janus.instant/1");
    v=leaf(r,"time_scale");CHECK(v->type==AML_TYPE_STRING);equal(v->string->data,"posix");
    v=leaf(r,"unix_day");CHECK(v->type==AML_TYPE_FLOAT && v->value==day);
    v=leaf(r,"second");CHECK(v->type==AML_TYPE_FLOAT && v->value==second);
    v=leaf(r,"millisecond");CHECK(v->type==AML_TYPE_FLOAT && v->value==millisecond);
}
int main(int argc,char **argv){
    int live=argc==3 && !strcmp(argv[1],"--live");CHECK(argc==1 || live);
    FILE*out=fopen(live?argv[2]:"build/reviews.jsonl","r");
    FILE*answers=fopen("examples/onejev-20261106/answers.jsonl","r");
    FILE*cases=fopen("examples/onejev-20261106/acceptance.jsonl","r");
    FILE*refs=live?fopen("examples/native-f32/reference.jsonl","r"):NULL;
    FILE*inputs=live?fopen("examples/reviews.jsonl","r"):NULL;
    CHECK(out && answers && cases && (!live || (refs && inputs)));
    char*meta=nj_load("examples/onejev-20261106/metadata.json",NULL);CHECK(meta);
    size_t size;char*raw=nj_load("examples/onejev-20261106/acceptance.jsonl",&size);CHECK(raw);
    char sha[65];digest(raw,size,sha);char*expected_sha=str(meta,"cases_sha256");equal(sha,expected_sha);free(raw);free(expected_sha);
    char*a=NULL,*b=NULL,*c=NULL,*ref=NULL,*input=NULL;size_t ac=0,bc=0,cc=0,rc=0,ic=0;int count=0,misses=0;
    am_init();am_persistent_mode(1);
    /* Both the digest and the reconstructed AML context must agree. */
    const char *frame="Reviewed file: f.c\nRepository rules from the base commit:\nrule\nChange under review (git diff):\ndiff";
    char frame_id[65],modified_id[65],modified[256];
    snprintf(modified,sizeof(modified),"%s\nextra instruction",frame);
    CHECK(!hash_bytes(frame,strlen(frame),frame_id) && !hash_bytes(modified,strlen(modified),modified_id));
    CHECK(jov_git_context_matches("f.c","rule","diff",frame,frame_id));
    CHECK(!jov_git_context_matches("f.c","rule","diff",modified,frame_id));
    CHECK(!jov_git_context_matches("f.c","rule","diff",modified,modified_id));
    while(record(out,&a,&ac)>=0){
        CHECK(record(answers,&b,&bc)>0 && record(cases,&c,&cc)>0);count++;
        field_equal(a,b,"id");field_equal(a,c,"id");CHECK(num(a,"schema_version")==1);
        const char*choice=nj_get(a,"choice"),*prob=nj_get(choice,"probabilities");
        char*verdict=str(choice,"verdict"),*predicted=str(b,"predicted");equal(verdict,predicted);
        double p[2]={num(prob,"CONCERN"),num(prob,"CLEAN")};
        CHECK(isfinite(p[0]) && isfinite(p[1]) && p[0]>=0 && p[1]>=0 && fabs(p[0]+p[1]-1)<1e-6);
        if(!live){const char*q=nj_get(b,"probabilities");CHECK(p[0]==num(q,"CONCERN") && p[1]==num(q,"CLEAN"));}
        else{
            CHECK(record(refs,&ref,&rc)>0);field_equal(a,ref,"id");const char*q=nj_get(ref,"probabilities");
            CHECK(fabs(p[0]-num(q,"CONCERN"))<=2e-4 && fabs(p[1]-num(q,"CLEAN"))<=2e-4);
            ssize_t n=record(inputs,&input,&ic);CHECK(n>0);digest(input,(size_t)n,sha);
            const char*e=nj_get(a,"execution");char*s=str(e,"input_sha256");equal(s,sha);free(s);
            s=str(e,"engine");equal(s,"NoTorch");free(s);s=str(e,"language");equal(s,"AML");free(s);
            char*manifest=nj_load("models/onejev-0.8b.json",NULL);CHECK(manifest);
            field_equal(e,manifest,"weights_sha256");field_equal(e,manifest,"tokenizer_sha256");free(manifest);
            const char*stamp=nj_get(e,"reviewed_at");CHECK(nj_is(nj_get(stamp,"schema"),"janus.instant/1"));
            CHECK(nj_is(nj_get(stamp,"time_scale"),"posix"));CHECK(num(stamp,"unix_day")>=20763);
            CHECK(num(stamp,"second")>=0 && num(stamp,"second")<86400);
            CHECK(num(stamp,"millisecond")>=0 && num(stamp,"millisecond")<1000);
        }
        char*expected=str(c,"expected"),*id=str(c,"id");
        if(strcmp(verdict,expected)){misses++;CHECK(!strcmp(id,"accept-boundary-False") || !strcmp(id,"accept-disabled-False"));}
        const char*model=nj_get(a,"model");char*s=str(model,"id"),*t=str(meta,"model");equal(s,t);free(s);free(t);
        field_equal(model,meta,"revision");s=str(a,"question");t=str(nj_get(meta,"question"),"instructions");equal(s,t);free(s);free(t);
        const char*in=nj_get(a,"input");field_equal(in,c,"context");char*context=str(c,"context");
        s=str(nj_get(a,"scope"),"file");CHECK(strstr(context,s));free(s);
        s=str(in,"rule_excerpt");CHECK(strstr(context,s));free(s);s=str(in,"change_excerpt");CHECK(strstr(context,s));free(s);
        CHECK(!am_set_var_text("review_context",context));CHECK(!am_exec_file("aml/prepare.aml"));
        s=str(b,"prompt");equal(am_get_var_text("prompt"),s);free(s);
        float probs[2]={(float)p[0],(float)p[1]},clock[3]={20763,86399,999};
        CHECK(!am_set_var_array("probabilities",probs,2) && !am_set_var_array("clock_parts",clock,3));
        CHECK(!am_exec_file("aml/answer.aml"));equal(am_get_var_text("verdict"),verdict);clock_check(20763,86399,999);
        free(context);free(verdict);free(predicted);free(expected);free(id);
    }
    CHECK(count==14 && misses==2);CHECK(record(answers,&b,&bc)<0);
    /* The original acceptance file also contains two generative identity
       prompts. OneJev's binary review protocol evaluated the 14 review rows. */
    int identity=0;
    while(record(cases,&c,&cc)>=0){CHECK(nj_is(nj_get(c,"expected"),"IDENTITY"));identity++;}
    CHECK(identity==2);
    if(live){CHECK(record(refs,&ref,&rc)<0 && record(inputs,&input,&ic)<0);fclose(refs);fclose(inputs);}
    /* Locked draw repair logits; the second case checks a large common offset. */
    const float pairs[][2] = {{10.7241526f,11.5221119f},{10000,10000},{-10000,10000}};
    const float clean[] = {0.6895378232f,0.5f,1.0f};
    for(size_t i=0;i<sizeof(clean)/sizeof(*clean);i++) {
        CHECK(!am_set_var_array("choice_logits",pairs[i],2) && !am_exec_file("aml/score-choices.aml"));
        int n=0;const float *scored=am_get_var_array("probabilities",&n);
        CHECK(scored && n==2 && fabsf(scored[1]-clean[i])<0.000002f);
    }
    CHECK(!am_set_var_array("choice_logits",pairs[0],1) && am_exec_file("aml/score-choices.aml")!=0);
    float tie[2]={.5,.5},clock[3]={-1,86399,1};
    CHECK(!am_set_var_array("probabilities",tie,2) && !am_set_var_array("clock_parts",clock,3));
    CHECK(!am_exec_file("aml/answer.aml"));equal(am_get_var_text("verdict"),"CONCERN");clock_check(-1,86399,1);
    tie[0]=1.1;CHECK(!am_set_var_array("probabilities",tie,2));CHECK(am_exec_file("aml/answer.aml")!=0);
    if(!live){
        char*e=nj_load("build/escaping.json",NULL),*m=nj_load("build/escaping.md",NULL);CHECK(e && m);
        char*s=str(nj_get(e,"scope"),"file");equal(s,"a*[x]<b>.c");free(s);
        s=str(nj_get(e,"input"),"rule_excerpt");equal(s,"keep \"quoted\" \\ paths\tand controls\x01.");free(s);
        s=str(nj_get(e,"input"),"change_excerpt");equal(s,"```\n<script>\n`\n````\n");free(s);
        CHECK(strstr(m,"a\\*\\[x\\]&lt;b&gt;\\.c") && strstr(m,"`````text\n```\n<script>\n`\n````\n`````\n"));free(e);free(m);
    }
    am_persistent_mode(0);free(a);free(b);free(c);free(ref);free(input);free(meta);fclose(out);fclose(answers);fclose(cases);
    printf("%s: 14 prompts, 14 choices, calendar and provenance; %d checks passed\n",live?"Native live parity":"Saved results and AML",checks);return 0;
}
