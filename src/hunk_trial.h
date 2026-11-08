#ifndef JOV_HUNK_TRIAL_H
#define JOV_HUNK_TRIAL_H
#include "git_snapshot.h"
#include <limits.h>

/* Construct each intervention from the original raw blobs. Git hunk positions
 * refer to lines in those blobs, including an unterminated final line. */
enum { MAX_TRIAL_HUNKS = 16, TRIAL_BYTES = 1024*1024 };
typedef struct { int start, count; } line_span;
typedef struct { line_span base, head; } hunk;
typedef struct { char *oid, *text; char mode[7]; } trial_blob;

static char *trial_git(const char *repo, const char *const args[]) {
    size_t n; int status;
    char *s=jov_git_command(repo,NULL,args,TRIAL_BYTES,&n,&status);
    if (s && (status || memchr(s,0,n))) { free(s); s=NULL; }
    return s;
}

static char *trial_oid(const char *repo, const char *const args[], size_t width) {
    char *s=trial_git(repo,args);
    if (!s) return NULL;
    if (strspn(s,"0123456789abcdef")!=width || strcmp(s+width,"\n")) { free(s); return NULL; }
    s[width]=0;
    return s;
}

static int load_trial_blob(const char *repo,const char *rev,const char *file,trial_blob *b) {
    b->oid=jov_git_regular_blob(repo,rev,file,b->mode);
    if (!b->oid) return 1;
    b->text=trial_git(repo,(const char *[]){"cat-file","blob",b->oid,NULL});
    return !b->text;
}

static int parse_span(const char **p, char sign, line_span *span) {
    if (**p != sign) return 1;
    (*p)++;
    char *end;
    long start=strtol(*p,&end,10), count=1;
    if (end==*p || start<0 || start>INT_MAX) return 1;
    if (*end==',') {
        const char *digits=end+1;
        count=strtol(digits,&end,10);
        if (end==digits || count<0 || count>INT_MAX) return 1;
    }
    span->start=(int)start; span->count=(int)count; *p=end;
    return !start && count;
}

static int trial_hunks(const char *repo,const trial_blob *base,const trial_blob *head,hunk hunks[]) {
    char *diff=trial_git(repo,(const char *[]){"diff","--no-color","--no-ext-diff","--no-textconv",
        "--unified=0","--inter-hunk-context=0","--diff-algorithm=myers",base->oid,head->oid,NULL});
    if (!diff) return -1;
    int n=0;
    for (char *line=diff; line && *line; ) {
        if (!strncmp(line,"@@ ",3)) {
            const char *p=line+3;
            if (n==MAX_TRIAL_HUNKS || parse_span(&p,'-',&hunks[n].base) || *p++!=' ' ||
                parse_span(&p,'+',&hunks[n].head) || strncmp(p," @@",3)) { n=-1; break; }
            n++;
        }
        line=strchr(line,'\n');
        if (line) line++;
    }
    free(diff); return n;
}

/* The zero-length side of an insertion/deletion starts after 'start' lines. */
static const char *after_lines(const char *text,int n) {
    while (n--) {
        if (!*text) return NULL;
        const char *lf=strchr(text,'\n');
        text=lf ? lf+1 : text+strlen(text);
    }
    return text;
}

static int write_splice(const char *path,const char *original,line_span removed,
                        const char *other,line_span inserted) {
    const char *from=after_lines(original,removed.start-(removed.count!=0));
    const char *to=from ? after_lines(from,removed.count) : NULL;
    const char *part=after_lines(other,inserted.start-(inserted.count!=0));
    const char *end=part ? after_lines(part,inserted.count) : NULL;
    if (!to || !end) return 1;
    FILE *f=fopen(path,"wb");
    if (!f) return 1;
    size_t prefix=(size_t)(from-original), n=(size_t)(end-part);
    int bad=fwrite(original,1,prefix,f)!=prefix || fwrite(part,1,n,f)!=n || fputs(to,f)==EOF;
    return fclose(f) || bad;
}

static char *trial_commit(const char *repo,const char *tree,const char *parent) {
    return trial_oid(repo,(const char *[]){"-c","user.name=Jovovich","-c","user.email=trial@localhost",
        "commit-tree",tree,"-p",parent,"-m","Isolated hunk trial",NULL},strlen(parent));
}

static char *spliced_commit(const char *repo,const char *rev,const char *file,const char *path,
                            const trial_blob *original,line_span removed,const trial_blob *other,line_span inserted) {
    if (write_splice(path,original->text,removed,other->text,inserted)) return NULL;
    char *blob=trial_oid(repo,(const char *[]){"hash-object","-w","--no-filters","--",path,NULL},strlen(rev));
    char *index=blob ? trial_git(repo,(const char *[]){"read-tree",rev,NULL}) : NULL;
    char *updated=index ? trial_git(repo,(const char *[]){"update-index","--cacheinfo",original->mode,blob,file,NULL}) : NULL;
    char *tree=updated ? trial_oid(repo,(const char *[]){"write-tree",NULL},strlen(rev)) : NULL;
    char *commit=tree ? trial_commit(repo,tree,rev) : NULL;
    free(tree); free(updated); free(index); free(blob);
    return commit;
}
#endif
