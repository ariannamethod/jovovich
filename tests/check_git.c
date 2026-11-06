#include "tools/narrow_json.h"
#include "hash.h"
#include <math.h>
static int checks;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"FAIL Git evidence line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static void eq(const char*obj,const char*key,const char*want){char*s=nj_string(nj_get(obj,key));CHECK(s && !strcmp(s,want));free(s);}
int main(int argc,char**argv){
    CHECK(argc==10 || argc==3);
    char*j=nj_load(argv[1],NULL);CHECK(j);
    if(argc==3){
        char*input=nj_load(argv[2],NULL);CHECK(input);const char*src=nj_get(j,"source"),*before=nj_get(input,"source");
        const char*keys[]={"base_commit","head_commit","rules_path","rules_blob","rules_sha256","diff_sha256"};
        for(int i=0;i<6;i++){char*s=nj_string(nj_get(before,keys[i]));CHECK(s);eq(src,keys[i],s);free(s);}
        const char*in=nj_get(j,"input");const char*fields[]={"context","rule_excerpt","change_excerpt"};
        for(int i=0;i<3;i++){char*s=nj_string(nj_get(input,fields[i]));CHECK(s);eq(in,fields[i],s);free(s);}
        char*s=nj_string(nj_get(input,"id"));CHECK(s);eq(j,"id",s);free(s);
        double a,b;const char*c=nj_get(j,"choice"),*p=nj_get(c,"probabilities");
        CHECK(!nj_number(nj_get(p,"CONCERN"),&a) && !nj_number(nj_get(p,"CLEAN"),&b));
        CHECK(isfinite(a) && isfinite(b) && a>=0 && b>=0 && fabs(a+b-1)<1e-6);eq(c,"verdict",a>=b?"CONCERN":"CLEAN");
        eq(nj_get(j,"execution"),"engine","NoTorch");eq(nj_get(j,"execution"),"language","AML");
        free(input);
    }else{
        char*rules=nj_load(argv[2],NULL),*diff=nj_load(argv[3],NULL);CHECK(rules && diff);
        eq(j,"file",argv[9]);eq(j,"rule_excerpt",rules);eq(j,"change_excerpt",diff);
        char*context=nj_string(nj_get(j,"context"));CHECK(context);
        CHECK(strstr(context,argv[9]) && strstr(context,rules) && strstr(context,diff));
        char h[65];CHECK(!hash_bytes(context,strlen(context),h));eq(j,"id",h);
        const char*s=nj_get(j,"source");eq(s,"kind","git");eq(s,"base_commit",argv[4]);eq(s,"head_commit",argv[5]);eq(s,"rules_blob",argv[6]);
        CHECK(!hash_bytes(rules,strlen(rules),h));eq(s,"rules_sha256",h);
        CHECK(!hash_bytes(diff,strlen(diff),h));eq(s,"diff_sha256",h);
        long long a,b;CHECK(!nj_int(nj_get(s,"rule_first_line"),&a) && a==atoi(argv[7]));
        CHECK(!nj_int(nj_get(s,"rule_last_line"),&b) && b==atoi(argv[8]));free(context);free(rules);free(diff);
    }
    free(j);printf("Git evidence: %d checks passed\n",checks);return 0;
}
