#define _XOPEN_SOURCE 700
#include "visual_compare.h"
#include "visual_memory.h"
#include "git_command.h"
#include "report_json.h"
#include "json.h"
#include "hash.h"
#include "ariannamethod.h"
#include <limits.h>

static char *field(const char *row,const char *key,size_t limit) {
    char *s=nj_string(nj_get(row,key));
    if(s && (!*s || strlen(s)>limit)){free(s);s=NULL;}
    return s;
}
static int integer(const char *row,const char *key,int low,int high,int *out) {
    long long n;
    if(nj_int(nj_get(row,key),&n) || n<low || n>high)return 1;
    *out=(int)n;return 0;
}
static int path_ok(const char *p) {
    if(!p || !*p || *p=='/')return 0;
    for(const char *s=p;*s;) {
        size_t n=strcspn(s,"/");
        if(!n || (n==1 && *s=='.') || (n==2 && !memcmp(s,"..",2)))return 0;
        s+=n;if(*s && !*++s)return 0;
    }
    return 1;
}
static char *read_git(const char *repo,const char *const args[],size_t cap,size_t *n) {
    int status=1;char *s=jov_git_command(repo,NULL,args,cap,n,&status);
    if(status){free(s);s=NULL;}return s;
}
static char *quote(const char *s,size_t n,int first,int last) {
    if(memchr(s,0,n))return NULL;
    size_t start=0,end=0;int line=1;
    for(size_t i=0;i<n;i++) {
        if(line<first)start=i+1;
        if(line<=last)end=i+1;
        if(s[i]=='\n')line++;
    }
    int lines=line-(n>0 && s[n-1]=='\n');
    return last<=lines && end>start && end-start<=16384?strndup(s+start,end-start):NULL;
}
/* The comparison checkout must contain the same commit, leaf and image bytes
 * recorded by inference. Working-tree files and replacement refs are unused. */
static int image_source(const char *repo,const char *receipt,char **commit,char **path) {
    const char *origin=nj_get(receipt,"origin"),*src=nj_get(origin,"source");
    *commit=field(src,"commit",64);*path=field(src,"path",4096);
    char *blob=NULL,*data=NULL;size_t n=0;int bad=1;
    if(!*commit || !*path)goto done;
    data=read_git(repo,(const char*[]){"cat-file","-t",*commit,NULL},32,&n);
    if(!data || strcmp(data,"commit\n"))goto done;
    free(data);data=NULL;
    blob=jov_git_regular_blob(repo,*commit,*path,NULL);
    if(!blob || !nj_is(nj_get(src,"blob"),blob))goto done;
    data=read_git(repo,(const char*[]){"cat-file","blob",blob,NULL},32*1024*1024,&n);
    char digest[65];
    if(!data || hash_bytes(data,n,digest) ||
       !nj_is(nj_get(nj_get(nj_get(origin,"observation"),"image"),"sha256"),digest))goto done;
    bad=0;
done:
    free(blob);free(data);return bad;
}
static char *observed(const char *row) {
    return field(row,nj_is(nj_get(row,"letter"),"A")?"choice_a":"choice_b",2048);
}
int jov_visual_comparison(const char *directory,const char *input,char **receipt) {
    *receipt=NULL;
    const char *req=nj_get(input,"compare"),*rules=nj_get(req,"rules");
    char *repository=field(req,"repository",128),*key=field(req,"key",128),*repo=field(req,"checkout",4096);
    char *path=field(rules,"path",4096),*id=field(input,"id",256);
    char *before=NULL,*after=NULL,*base=NULL,*head=NULL,*old_path=NULL,*new_path=NULL;
    char *blob=NULL,*data=NULL,*rule=NULL,*question=NULL,*value_before=NULL,*value_after=NULL;
    char *oa=NULL,*ob=NULL,*na=NULL,*nb=NULL;int from,to,first,last,seq,bad=1;
    size_t n=0,length=0;
    int reverse=nj_is(nj_get(input,"concern_letter"),"B");
    if(!repository || !key || !repo || !id || !path_ok(path) ||
       nj_get(input,"image") || nj_get(input,"remember") || nj_get(input,"recall") ||
       nj_get(input,"question") || nj_get(input,"choice_a") || nj_get(input,"choice_b") ||
       (nj_get(input,"concern_letter") && !reverse && !nj_is(nj_get(input,"concern_letter"),"A")) ||
       integer(req,"before",1,256,&from) || integer(req,"after",1,256,&to) || from>=to ||
       integer(rules,"first",1,INT_MAX,&first) || integer(rules,"last",first,INT_MAX,&last))goto done;
    if(jov_visual_remembered(directory,repository,key,from,&before) ||
       integer(before,"sequence",1,256,&seq) || seq!=from ||
       jov_visual_remembered(directory,repository,key,to,&after) ||
       integer(after,"sequence",1,256,&seq) || seq!=to ||
       image_source(repo,before,&base,&old_path) || image_source(repo,after,&head,&new_path) ||
       strcmp(old_path,new_path) || !strcmp(base,head))goto done;
    data=read_git(repo,(const char*[]){"merge-base","--is-ancestor",base,head,NULL},32,&n);
    if(!data)goto done;
    free(data);data=NULL;
    blob=jov_git_regular_blob(repo,base,path,NULL);
    if(!blob || !(data=read_git(repo,(const char*[]){"cat-file","blob",blob,NULL},262144,&n)) ||
       !(rule=quote(data,n,first,last)))goto done;
    const char *old=nj_get(nj_get(before,"origin"),"observation"),*now=nj_get(nj_get(after,"origin"),"observation");
    question=field(old,"question",4096);value_before=observed(old);value_after=observed(now);
    oa=field(old,"choice_a",2048);ob=field(old,"choice_b",2048);
    na=field(now,"choice_a",2048);nb=field(now,"choice_b",2048);
    if(!question || !value_before || !value_after || !oa || !ob || !na || !nb ||
       !nj_is(nj_get(now,"question"),question) ||
       !((!strcmp(oa,na) && !strcmp(ob,nb)) || (!strcmp(oa,nb) && !strcmp(ob,na))))goto done;
    float order[1]={(float)reverse};
    if(am_set_var_text("compare_rule",rule) || am_set_var_text("compare_question",question) ||
       am_set_var_text("compare_before",value_before) || am_set_var_text("compare_after",value_after) ||
       am_set_var_array("compare_order",order,1) || am_exec_file("aml/visual-compare.aml"))goto done;
    const char *state=am_get_var_text("visual_state");
    if(!state || !am_get_var_text("visual_question") || !am_get_var_text("visual_a") || !am_get_var_text("visual_b"))goto done;
    char rule_hash[65],input_hash[65];
    if(hash_bytes(rule,strlen(rule),rule_hash) || hash_bytes(input,strlen(input),input_hash))goto done;
    FILE *out=open_memstream(receipt,&length);if(!out)goto done;
    fputs("{\"schema\":\"jovovich.visual-comparison/1\",",out);json_field(out,"id",id);
    fputc(',',out);json_field(out,"input_sha256",input_hash);
    fputc(',',out);json_field(out,"repository",repository);fputc(',',out);json_field(out,"key",key);
    fprintf(out,",\"before\":%s,\"after\":%s,\"rule\":{",before,after);
    json_field(out,"commit",base);fputc(',',out);json_field(out,"path",path);fputc(',',out);json_field(out,"blob",blob);
    fprintf(out,",\"first\":%d,\"last\":%d,",first,last);json_field(out,"quote",rule);
    fputc(',',out);json_field(out,"sha256",rule_hash);fputs("},",out);
    json_field(out,"state",state);fputc('}',out);
    if(fclose(out))goto done;
    bad=0;
done:
    free(repository);free(key);free(repo);free(path);free(id);free(before);free(after);free(base);free(head);
    free(old_path);free(new_path);free(blob);free(data);free(rule);free(question);free(value_before);free(value_after);
    free(oa);free(ob);free(na);free(nb);
    if(bad){free(*receipt);*receipt=NULL;fputs("Cannot bind visual comparison to its history and Git rule\n",stderr);}
    return bad;
}
int jov_visual_compare_preview(int argc,char **argv) {
    if(argc!=3)return 2;
    am_init();am_persistent_mode(1);int rc=1,bad=0;size_t n=0;
    char *line=NULL,*receipt=NULL;
    while((line=report_json_row(stdin,&n,&bad,65536,1048576))) {
        if(jov_visual_comparison(argv[2],line,&receipt) || puts(receipt)==EOF || fflush(stdout))goto done;
        free(receipt);receipt=NULL;free(line);line=NULL;
    }
    rc=bad?1:0;
done:
    free(line);free(receipt);am_persistent_clear();am_persistent_mode(0);return rc;
}
