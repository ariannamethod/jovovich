#define _POSIX_C_SOURCE 200809L
#include "hash.h"
#include "report_json.h"
#include <assert.h>
typedef struct {char*code,*context,*rule,*file,*label;int split,kind,form;} row;
static int checks;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"Corpus check failed at line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static char *str(const char*j,const char*k){char*s=nj_string(nj_get(j,k));CHECK(s);return s;}
static int num(const char*j,const char*k){long long n;CHECK(!nj_int(nj_get(j,k),&n));CHECK(n>= -100 && n<10000);return (int)n;}
static FILE *open_file(const char*dir,const char*name){char p[4096];CHECK(snprintf(p,sizeof(p),"%s/%s",dir,name)<(int)sizeof(p));FILE*f=fopen(p,"rb");CHECK(f);return f;}
static void eq(const char*j,const char*k,const char*want){char*s=str(j,k);CHECK(!strcmp(s,want));free(s);}
static void next(FILE*f,char**s,size_t*cap){CHECK(getline(s,cap,f)>0);const char*end=report_json_end(*s,0);CHECK(end && !*nj_ws(end));}
int main(int argc,char**argv) {
    CHECK(argc==2);row rows[192]={{0}};
    FILE*t=open_file(argv[1],"train.jsonl"),*e=open_file(argv[1],"eval-inputs.jsonl"),*g=open_file(argv[1],"eval-expected.jsonl"),*a=open_file(argv[1],"audit.jsonl");
    char *input=NULL,*audit=NULL,*gold=NULL;size_t ic=0,ac=0,gc=0;int counts[2][2]={{0}},domains=0,contract_pairs=0;
    for(int i=0;i<192;i++) {
        row*r=rows+i;r->split=i>=128;next(r->split?e:t,&input,&ic);next(a,&audit,&ac);
        char id[32],pair[32];snprintf(id,sizeof(id),"semantic-%03d",i);snprintf(pair,sizeof(pair),"pair-%03d",i/2);
        eq(input,"id",id);eq(audit,"id",id);eq(audit,"pair_id",pair);eq(audit,"split",r->split?"eval":"train");
        r->code=str(input,"change_excerpt");r->context=str(input,"context");r->rule=str(input,"rule_excerpt");r->file=str(input,"file");r->label=str(audit,"expected");
        CHECK(!strcmp(r->label,"CLEAN") || !strcmp(r->label,"CONCERN"));int concern=!strcmp(r->label,"CONCERN");
        char h[65];CHECK(!hash_bytes(r->code,strlen(r->code),h));eq(audit,"code_sha256",h);
        CHECK(!hash_bytes(r->context,strlen(r->context),h));eq(audit,"context_sha256",h);
        CHECK(strstr(r->context,r->code) && strstr(r->context,r->rule) && strstr(r->context,r->file));
        r->kind=!strcmp(r->file,"publish.c");eq(audit,"family",r->kind?"guard":"boundary");r->form=num(audit,"template");
        CHECK(r->kind?(r->split?r->form>=4:r->form<4):(r->split?r->form==2:r->form<2));
        CHECK(num(audit,"checked")== (r->kind?4:17));domains+=num(audit,"checked");CHECK((num(audit,"failures")>0)==concern);
        const char*w=nj_get(audit,"witness");CHECK(w);
        if(concern)CHECK(num(w,"expected")!=num(w,"actual"));else CHECK(!strncmp(w,"null",4));
        if(r->split){next(g,&gold,&gc);eq(gold,"id",id);eq(gold,"expected",r->label);eq(gold,"split","transfer");CHECK(!nj_get(input,"completion") && !nj_get(input,"prompt") && !nj_get(input,"expected"));}
        else {
            eq(input,"completion",concern?"A":"B");CHECK(num(input,"completion_token_id")== (concern?32:33));eq(input,"pair_id",pair);
            char*prompt=str(input,"prompt");CHECK(strstr(prompt,r->context));
            const char*suffix="<|im_start|>assistant\n<think>\n\n</think>\n\n";
            CHECK(strlen(prompt)>=strlen(suffix) && !strcmp(prompt+strlen(prompt)-strlen(suffix),suffix));free(prompt);
        }
        counts[r->split][concern]++;
        if(i%2){CHECK(!strcmp(r->rule,rows[i-1].rule));CHECK(!strcmp(r->file,rows[i-1].file));CHECK(strcmp(r->label,rows[i-1].label));}
        for(int j=0;j<i;j++) {
            CHECK(strcmp(r->context,rows[j].context));
            if(r->split!=rows[j].split)CHECK(strcmp(r->code,rows[j].code));
            else if(!strcmp(r->code,rows[j].code) && strcmp(r->label,rows[j].label))contract_pairs++;
        }
    }
    CHECK(counts[0][0]==64 && counts[0][1]==64 && counts[1][0]==32 && counts[1][1]==32 && domains==2432 && contract_pairs>0);
    CHECK(getline(&input,&ic,t)<0 && getline(&input,&ic,e)<0 && getline(&input,&ic,g)<0 && getline(&input,&ic,a)<0);
    fclose(t);fclose(e);fclose(g);fclose(a);
    FILE*old=fopen("examples/quality-20261106/inputs.jsonl","rb");CHECK(old);int original=0;
    while(getline(&input,&ic,old)>0){char*c=str(input,"context"),*code=str(input,"change_excerpt");for(int i=0;i<192;i++){CHECK(strcmp(c,rows[i].context));CHECK(strcmp(code,rows[i].code));}free(c);free(code);original++;}
    CHECK(original==38);fclose(old);
    for(int i=0;i<192;i++){free(rows[i].code);free(rows[i].context);free(rows[i].rule);free(rows[i].file);free(rows[i].label);}
    free(input);free(audit);free(gold);
    printf("Semantic corpus: %d checks; 2432 native observations, balanced splits, isolated templates, %d same-code/opposite-contract label pairs\n",checks,contract_pairs);
    return 0;
}
