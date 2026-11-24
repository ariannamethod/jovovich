#define _XOPEN_SOURCE 700
#include "visual_memory.h"
#include "facts.h"
#include "git_command.h"
#include "hash.h"
#include "json.h"
#include "report_json.h"
#include "ariannamethod.h"
#include <limits.h>
#include <math.h>
#include <unistd.h>

static int name_ok(const char *s) {
    return s && *s && strlen(s)<=128 &&
        strspn(s,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./_-")==strlen(s);
}
static int hex_ok(const char *s, size_t n) {
    return s && strlen(s)==n && strspn(s,"0123456789abcdef")==n;
}
static char *text(const char *row,const char *key,size_t limit) {
    char *s=nj_string(nj_get(row,key));
    if(s && (!*s || strlen(s)>limit)){free(s);s=NULL;}
    return s;
}
static int integer(const char *row,const char *key,int lo,int hi,int *out) {
    long long n;
    if(nj_int(nj_get(row,key),&n) || n<lo || n>hi)return 1;
    *out=(int)n;return 0;
}
static int path_ok(const char *p) {
    if(!p || !*p || *p=='/' || strlen(p)>4096)return 0;
    for(const char *s=p;*s;) {
        size_t n=strcspn(s,"/");
        if(!n || (n==1 && *s=='.') || (n==2 && !memcmp(s,"..",2)))return 0;
        s+=n;
        if(*s && !*++s)return 0;
    }
    return 1;
}

/* Match the captured image bytes to the regular blob at an exact commit, not
 * to a mutable checkout, replacement ref, symlink, or symbolic revision. */
static char *source(const char *input,const char *image_hash,char **repository,char **key,int *parent) {
    const char *src=nj_get(input,"remember");
    char *repo=text(src,"checkout",4096),*commit=text(src,"commit",64),*path=text(src,"path",4096);
    *repository=text(src,"repository",128);*key=text(src,"key",128);
    char *blob=NULL,*data=NULL,*result=NULL;size_t n=0,length=0;int status=1,pr=0;
    if(!name_ok(*repository) || !name_ok(*key) || !repo ||
       !(hex_ok(commit,40) || hex_ok(commit,64)) || !path_ok(path) ||
       integer(src,"pull_request",1,INT_MAX,&pr) || integer(src,"supersedes",0,256,parent))goto done;
    const char *kind_args[]={"cat-file","-t",commit,NULL};
    data=jov_git_command(repo,NULL,kind_args,32,&n,&status);
    if(!data || status || strcmp(data,"commit\n"))goto done;
    free(data);data=NULL;
    blob=jov_git_regular_blob(repo,commit,path,NULL);
    if(!blob)goto done;
    const char *blob_args[]={"cat-file","blob",blob,NULL};
    data=jov_git_command(repo,NULL,blob_args,32*1024*1024,&n,&status);
    char digest[65];
    if(!data || status || hash_bytes(data,n,digest) || strcmp(digest,image_hash))goto done;
    FILE *out=open_memstream(&result,&length);
    if(!out)goto done;
    fputc('{',out);json_field(out,"repository",*repository);fputc(',',out);json_field(out,"key",*key);
    fprintf(out,",\"pull_request\":%d,",pr);json_field(out,"commit",commit);fputc(',',out);json_field(out,"path",path);
    fputc(',',out);json_field(out,"blob",blob);fputc('}',out);
    if(fclose(out)){free(result);result=NULL;}
done:
    free(repo);free(commit);free(path);free(blob);free(data);return result;
}

/* Bounds and binding are also checked on reads, before any saved text reaches
 * inference. The persisted observation is returned verbatim. */
static int observation_ok(const char *raw) {
    const char *end=raw?report_json_end(raw,0):NULL;
    if(!end || *nj_ws(end) || strlen(raw)>32768 || !nj_is(nj_get(raw,"schema"),"jovovich.visual-choice/1"))return 0;
    const char *strings[]={"id","question","choice_a","choice_b"};
    const size_t bounds[]={256,4096,2048,2048};
    for(int i=0;i<4;i++){char *s=text(raw,strings[i],bounds[i]);if(!s)return 0;free(s);}
    const char *hashes[]={"input_sha256","prompt_sha256","weights_sha256","tokenizer_sha256","vision_weights_sha256"};
    for(int i=0;i<5;i++){char *h=text(raw,hashes[i],64);int ok=hex_ok(h,64);free(h);if(!ok)return 0;}
    char *h=text(nj_get(raw,"image"),"sha256",64);int ok=hex_ok(h,64);free(h);
    if(!ok || (!nj_is(nj_get(raw,"letter"),"A") && !nj_is(nj_get(raw,"letter"),"B")))return 0;
    double la,lb,pa,pb;
    if(nj_number(nj_get(raw,"logit_a"),&la) || nj_number(nj_get(raw,"logit_b"),&lb) ||
       nj_number(nj_get(raw,"p_a"),&pa) || nj_number(nj_get(raw,"p_b"),&pb) ||
       !isfinite(la) || !isfinite(lb) || !isfinite(pa) || !isfinite(pb) ||
       pa<0 || pb<0 || pa>1 || pb>1 || fabs(pa+pb-1)>1e-6 ||
       !nj_is(nj_get(raw,"letter"),pa>=pb?"A":"B"))return 0;
    const char *clock=nj_get(raw,"observed_at");int day,second,ms;
    return nj_is(nj_get(clock,"schema"),"janus.instant/1") && nj_is(nj_get(clock,"time_scale"),"posix") &&
        !integer(clock,"unix_day",-10000000,10000000,&day) && !integer(clock,"second",0,86399,&second) &&
        !integer(clock,"millisecond",0,999,&ms);
}
static char *copy_object(const char *p) {
    const char *end=p?report_json_end(p,0):NULL;
    return end?strndup(p,(size_t)(end-p)):NULL;
}
static int origin_ok(const char *raw,const char *repository,const char *key) {
    const char *end=raw?report_json_end(raw,0):NULL;
    if(!end || *nj_ws(end) || strlen(raw)>40000)return 0;
    const char *src=nj_get(raw,"source");
    char *r=text(src,"repository",128),*k=text(src,"key",128),*c=text(src,"commit",64),*b=text(src,"blob",64),*p=text(src,"path",4096);
    char *obs=copy_object(nj_get(raw,"observation"));int pr;
    int ok=r && k && !strcmp(r,repository) && !strcmp(k,key) &&
        (hex_ok(c,40) || hex_ok(c,64)) && b && strlen(b)==strlen(c) && hex_ok(b,strlen(c)) &&
        path_ok(p) && !integer(src,"pull_request",1,INT_MAX,&pr) && observation_ok(obs);
    free(r);free(k);free(c);free(b);free(p);free(obs);return ok;
}
static int select_memory(const char *directory,const char *repository,const char *key,int through,
                          int parent,const char *origin,const char *identity,char **receipt) {
    *receipt=NULL;int writer=-1,failed=1;
    if(!name_ok(repository) || !name_ok(key) || through < -1 || through>256 ||
       (origin && !origin_ok(origin,repository,key)) ||
       jov_journal_open(directory,"visual",origin!=NULL,&writer))goto done;
    float args[3]={origin!=NULL,(float)through,(float)parent};
    if(am_set_var_text("visual_repository",repository) || am_set_var_text("visual_key",key) ||
       am_set_var_array("visual_memory_args",args,3) ||
       (origin && (am_set_var_text("visual_origin",origin) || am_set_var_text("visual_identity",identity))) ||
       am_exec_file("aml/visual-memory.aml"))goto done;
    const char *saved=am_get_var_text("visual_origin");
    int seq=(int)am_get_var_float("revision"),prev=(int)am_get_var_float("predecessor");
    if(seq<1 || seq>256 || prev<0 || prev>=seq || !origin_ok(saved,repository,key))goto done;
    size_t length=0;FILE *out=open_memstream(receipt,&length);
    if(!out)goto done;
    fputs("{\"schema\":\"jovovich.visual-fact/1\",",out);json_field(out,"repository",repository);
    fputc(',',out);json_field(out,"key",key);
    fprintf(out,",\"sequence\":%d,\"supersedes\":%d,\"origin\":%s}",seq,prev,saved);
    if(fclose(out) || (origin && jov_memory_commit()))goto done;
    failed=0;
done:
    if(writer>=0)close(writer);
    if(failed){free(*receipt);*receipt=NULL;fprintf(stderr,"Visual memory: %s\n",am_get_error());}
    return failed;
}
int jov_visual_remember(const char *directory,const char *input,const char *observation,char **receipt) {
    *receipt=NULL;
    if(!observation_ok(observation))return 1;
    char input_hash[65];
    if(hash_bytes(input,strlen(input),input_hash) || !nj_is(nj_get(observation,"input_sha256"),input_hash))return 1;
    const char *fields[]={"id","question","choice_a","choice_b"};
    for(int i=0;i<4;i++) {
        char *a=nj_string(nj_get(input,fields[i])),*b=nj_string(nj_get(observation,fields[i]));
        int same=a && b && !strcmp(a,b);free(a);free(b);if(!same)return 1;
    }
    char *h=text(nj_get(observation,"image"),"sha256",64),*repository=NULL,*key=NULL;int parent=0,failed=1;
    if(!nj_is(nj_get(nj_get(input,"image"),"sha256"),h)){free(h);return 1;}
    char *src=source(input,h,&repository,&key,&parent),*origin=NULL,*observed=copy_object(observation);size_t length=0;
    if(!src || !observed)goto done;
    FILE *out=open_memstream(&origin,&length);
    if(!out)goto done;
    fprintf(out,"{\"source\":%s,\"observation\":%s}",src,observed);
    if(fclose(out))goto done;
    /* Retry identity includes exact input, Git source and inference results.
     * Only the new measurement clock is excluded; the first clock is kept. */
    const char *clock=strstr(origin,",\"observed_at\":");char identity[65];
    if(!clock || hash_bytes(origin,(size_t)(clock-origin),identity))goto done;
    failed=select_memory(directory,repository,key,-1,parent,origin,identity,receipt);
done:
    free(h);free(repository);free(key);free(src);free(origin);free(observed);return failed;
}
int jov_visual_remembered(const char *directory,const char *repository,const char *key,int through,char **receipt) {
    return select_memory(directory,repository,key,through,0,NULL,NULL,receipt);
}
int jov_visual_history(int argc,char **argv) {
    int through=-1;
    if(argc==7 && !strcmp(argv[5],"--as-of")) {
        char *end;long n=strtol(argv[6],&end,10);
        if(end==argv[6] || *end || n<0 || n>256)return 2;
        through=(int)n;
    } else if(argc!=5)return 2;
    am_init();am_persistent_mode(1);
    char *receipt=NULL;
    int rc=jov_visual_remembered(argv[2],argv[3],argv[4],through,&receipt);
    if(!rc)rc=puts(receipt)==EOF || fflush(stdout);
    free(receipt);am_persistent_clear();am_persistent_mode(0);return rc;
}
