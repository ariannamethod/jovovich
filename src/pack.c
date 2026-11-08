#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "json.h"
#include "hash.h"
#include "review.h"
#include "batch.h"
#include "facts.h"
#include "process.h"
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Literal changed paths at two resolved commits. No shell or working-tree reads. */
#define CAP 262144
static char *git_read(const char *repo,const char *const args[],size_t *length) {
    const char *argv[32]={"git","--no-pager","--no-replace-objects","--literal-pathspecs","-C",repo};
    size_t a=6;
    for(size_t i=0;args[i];i++){if(a>=31)return NULL;argv[a++]=args[i];}
    argv[a]=NULL;
    int code;
    char *data = jov_command(argv, CAP, length, &code);
    if (data && code) { free(data); return NULL; }
    return data;
}
static int oid(const char *s){size_t n=strlen(s);return (n==40 || n==64) && strspn(s,"0123456789abcdef")==n;}
static char *resolve(const char *repo,const char *ref) {
    size_t n=strlen(ref);if(!n || n>4096)return NULL;
    char *spec=malloc(n+10);if(!spec)return NULL;snprintf(spec,n+10,"%s^{commit}",ref);
    size_t len;char *out=git_read(repo,(const char*[]){"rev-parse","--verify","--end-of-options",spec,NULL},&len);free(spec);
    if(!out)return NULL;
    if(len && out[len-1]=='\n')out[--len]=0;
    if(memchr(out,0,len) || !oid(out)){free(out);return NULL;}return out;
}
static int integer(const char*s,int*out){char*end;errno=0;long x=strtol(s,&end,10);if(errno || end==s || *end || x<1 || x>INT_MAX)return 1;*out=(int)x;return 0;}
/* 0 absent; 1 regular blob; 2 symlink/gitlink; -1 directory or failure. */
static int path_kind(const char *repo,const char *commit,const char *path) {
    size_t n;char *s=git_read(repo,(const char*[]){"ls-tree","--full-name","--format=%(objectmode)",commit,"--",path,NULL},&n);
    if(!s)return -1;
    int kind=n==0?0:!strcmp(s,"100644\n") || !strcmp(s,"100755\n")?1:
        !strcmp(s,"120000\n") || !strcmp(s,"160000\n")?2:-1;
    free(s);return kind;
}
static char *select_lines(const char *text,size_t n,int first,int *last) {
    int lines=0;for(size_t i=0;i<n;i++)if(text[i]=='\n')lines++;
    if(n && text[n-1]!='\n')lines++;
    if(*last==0)*last=lines;
    if(first<1 || *last<first || *last>lines)return NULL;
    int line=1;size_t start=0,end=n;
    for(size_t i=0;i<n;i++){if(line==first){start=i;break;}if(text[i]=='\n')line++;}
    line=first;for(size_t i=start;i<n;i++)if(text[i]=='\n' && line++==*last){end=i+1;break;}
    char*out=malloc(end-start+1);if(out){memcpy(out,text+start,end-start);out[end-start]=0;}return out;
}
typedef struct {
    char *file,*diff,*context;
    char id[65],diff_hash[65];
} packed;
static int prepare(packed*p,const char*repo,const char*base,const char*head,const char*rules) {
    size_t n;char *stat=NULL;int rc=1;
    if(path_kind(repo,base,p->file)<0 || path_kind(repo,head,p->file)<0)goto done;
    stat=git_read(repo,(const char*[]){"diff","--no-ext-diff","--no-textconv","--no-renames","--ignore-submodules=none","--numstat","-z",base,head,"--",p->file,NULL},&n);
    if(!stat)goto done;
    if(n && (stat[0]=='-' || (strchr(stat,'\t') && strchr(stat,'\t')[1]=='-'))){fprintf(stderr,"Binary change: %s\n",p->file);goto done;}
    p->diff=git_read(repo,(const char*[]){"diff","--no-ext-diff","--no-textconv","--no-color","--no-renames","--ignore-submodules=none","--submodule=short","--unified=8",base,head,"--",p->file,NULL},&n);
    if(!p->diff || !n || memchr(p->diff,0,n) || hash_bytes(p->diff,n,p->diff_hash))goto done;
    if(am_set_var_text("source_file",p->file) || am_set_var_text("source_rules",rules) || am_set_var_text("source_diff",p->diff) || am_exec_file("aml/git-context.aml"))goto done;
    const char*ctx=am_get_var_text("review_context");
    if(!ctx || !strstr(ctx,p->file) || !strstr(ctx,rules) || !strstr(ctx,p->diff) || !(p->context=strdup(ctx)) || hash_bytes(ctx,strlen(ctx),p->id))goto done;
    rc=0;
done:
    free(stat);if(rc)fprintf(stderr,"Could not capture text change: %s\n",p->file);return rc;
}
static int usage(void) {
    fputs("Usage: jovovich-pack [--remember DIR REPOSITORY KEY [--supersedes N]] [--all] REPO BASE HEAD RULES_PATH [FILE] [FIRST LAST]\n"
          "       jovovich-pack --recall DIR REPOSITORY KEY [--as-of N] [--all] REPO BASE HEAD [FILE]\n"
          "       jovovich-pack --fact DIR REPOSITORY KEY [--as-of N]\n", stderr);
    return 2;
}

int main(int argc,char **argv) {
    int remember = 0, recall = 0, fact_only = 0, horizon = -1, parent = 0;
    const char *directory = NULL, *repository = NULL, *key = NULL;
    char **args = argv + 1;
    int nargs = argc - 1;
    if (nargs > 0) {
        remember = !strcmp(args[0], "--remember");
        recall = !strcmp(args[0], "--recall");
        fact_only = !strcmp(args[0], "--fact");
    }
    if (remember || recall || fact_only) {
        if (nargs < 4) return usage();
        directory = args[1]; repository = args[2]; key = args[3];
        args += 4; nargs -= 4;
        if (nargs >= 2 && !strcmp(args[0], remember ? "--supersedes" : "--as-of")) {
            int value;
            if (integer(args[1], &value) || value > 256) return usage();
            if (remember) parent = value;
            else horizon = value;
            args += 2; nargs -= 2;
        }
    }
    int all = nargs > 0 && !strcmp(args[0], "--all");
    if (all) { args++; nargs--; }
    int required = 3 + !recall + !all;
    if (fact_only ? (all || nargs != 0) :
        (nargs != required && (recall || nargs != required + 2))) return usage();

    int rc=1,first=1,last=0,count=0,writer=-1;size_t n=0,rules_len=0;
    const char *repo = fact_only ? NULL : args[0];
    const char *rules_path = recall || fact_only ? NULL : args[3];
    char *base=NULL,*head=NULL,*spec=NULL,*blob=NULL,*rules=NULL,*selected=NULL,*list=NULL;
    packed records[JOV_BATCH_MAX_FILES]={{0}};jov_batch_item items[JOV_BATCH_MAX_FILES]={{0}};FILE*out=NULL;
    jov_fact *fact = NULL;
    am_init(); am_persistent_mode(1);
    if (recall || fact_only) {
        if (jov_memory_select(directory, repository, key, horizon, 0, NULL, &fact, &writer)) goto done;
        if (fact_only) {
            jov_fact_json(stdout, fact);
            rc = fputc('\n', stdout) == EOF || fflush(stdout);
            goto done;
        }
        rules_path = fact->path; first = fact->first; last = fact->last;
    }
    if(nargs == required + 2 && (integer(args[required],&first) || integer(args[required+1],&last)))goto done;
    if(!*rules_path || !(base=resolve(repo,args[1])) || !(head=resolve(repo,args[2])))goto done;
    if (recall) {
        char *ancestor = git_read(repo, (const char *[]){"merge-base", "--is-ancestor", fact->base, base, NULL}, &n);
        if (!ancestor) { fputs("Remembered rule comes from a different Git history.\n", stderr); goto done; }
        free(ancestor);
    }
    if(path_kind(repo,base,rules_path)!=1)goto done;
    spec=malloc(strlen(base)+strlen(rules_path)+2);if(!spec)goto done;sprintf(spec,"%s:%s",base,rules_path);
    blob=git_read(repo,(const char*[]){"rev-parse","--verify","--end-of-options",spec,NULL},&n);
    if(!blob)goto done;
    if(n && blob[n-1]=='\n')blob[--n]=0;
    if(memchr(blob,0,n) || !oid(blob))goto done;
    rules=git_read(repo,(const char*[]){"cat-file","blob",blob,NULL},&rules_len);
    if(!rules || !rules_len || memchr(rules,0,rules_len) || !(selected=select_lines(rules,rules_len,first,&last)))goto done;
    if (recall && strcmp(selected, fact->quote)) {
        fputs("Remembered rule differs at the selected Git base. Record its correction explicitly.\n", stderr);
        goto done;
    }
    if(all) {
        list=git_read(repo,(const char*[]){"diff","--no-ext-diff","--no-textconv","--no-renames","--ignore-submodules=none","--name-only","-z",base,head,NULL},&n);
        if(!list || !n || list[n-1]!=0)goto done;
        for(size_t at=0;at<n;) {
            const char*end=memchr(list+at,0,n-at);if(!end || end==list+at || count==JOV_BATCH_MAX_FILES)goto done;
            records[count].file=strdup(list+at);if(!records[count].file)goto done;count++;at=(size_t)(end-list)+1;
        }
    }else {
        const char *file = args[recall ? 3 : 4];
        if(!*file || !(records[0].file=strdup(file)))goto done;
        count=1;
    }
    char rh[65],batch_id[65];if(hash_bytes(selected,strlen(selected),rh))goto done;
    size_t total=0;
    for(int i=0;i<count;i++) {
        if(prepare(records+i,repo,base,head,selected))goto done;
        total+=strlen(records[i].context)+strlen(records[i].diff);
        if(total>JOV_BATCH_MAX_BYTES)goto done;
        items[i]=(jov_batch_item){records[i].file,records[i].id,{base,head,rules_path,blob,rh,records[i].diff_hash,first,last}};
        if(jov_source_validate(&items[i].source))goto done;
    }
    if (remember) {
        jov_fact origin = {.base=base, .head=head, .path=(char *)rules_path, .quote=selected, .first=first, .last=last};
        if (jov_memory_select(directory, repository, key, -1, parent, &origin, &fact, &writer)) goto done;
    }
    if(all && jov_batch_digest_fact(items,count,fact,batch_id))goto done;
    out=tmpfile();if(!out)goto done;
    for(int i=0;i<count;i++) {
        packed*p=records+i;long start=ftell(out);
        fputc('{',out);json_field(out,"id",p->id);fputc(',',out);json_field(out,"file",p->file);fputc(',',out);
        json_field(out,"context",p->context);fputc(',',out);json_field(out,"rule_excerpt",selected);fputc(',',out);
        json_field(out,"change_excerpt",p->diff);fputs(",\"source\":",out);jov_source_json(out,&items[i].source);
        if (fact) { fputs(",\"fact\":", out); jov_fact_json(out, fact); }
        if(all){fputs(",\"batch\":{\"schema\":\"jovovich.git-batch/1\",\"scope\":\"all_changed_paths\",",out);json_field(out,"id",batch_id);fprintf(out,",\"index\":%d,\"count\":%d}",i,count);}
        fputs("}\n",out);long end=ftell(out);
        if(start<0 || end<start || end-start>1048576 || (unsigned long)end>JOV_BATCH_MAX_BYTES || ferror(out))goto done;
    }
    if(fseek(out,0,SEEK_SET))goto done;
    if (remember) {
        if (jov_memory_commit()) goto done;
        close(writer);
        writer = -1;
    }
    char chunk[8192];size_t got;while((got=fread(chunk,1,sizeof(chunk),out)))if(fwrite(chunk,1,got,stdout)!=got)break;
    rc=ferror(out) || ferror(stdout) || fflush(stdout);
done:
    if(rc && !fact_only)fprintf(stderr,"Could not pack Git review (256 KiB per Git read, 64 paths, 16 MiB total)\n");
    if (writer >= 0) close(writer);
    jov_fact_free(fact);
    if(out && fclose(out))rc=1;
    for(int i=0;i<JOV_BATCH_MAX_FILES;i++){free(records[i].file);free(records[i].diff);free(records[i].context);}
    am_persistent_mode(0);free(base);free(head);free(spec);free(blob);free(rules);free(selected);free(list);return rc?1:0;
}
