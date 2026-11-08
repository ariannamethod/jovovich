#ifndef JOV_GIT_SNAPSHOT_H
#define JOV_GIT_SNAPSHOT_H
#include "git_command.h"
#include <ftw.h>

static inline char *snapshot_path(const char *a, const char *suffix) {
    char *p = malloc(strlen(a) + strlen(suffix) + 1);
    if (p) sprintf(p, "%s%s", a, suffix);
    return p;
}

static int remove_snapshot_entry(const char *path, const struct stat *st, int kind, struct FTW *pos) {
    (void)st; (void)kind; (void)pos;
    return remove(path);
}

/* A bare view retains the named repository's objects and excludes its
 * worktree, index, refs, info/attributes, and repository configuration. */
static inline int jov_git_snapshot(const char *source, const char *base, char **directory) {
    size_t n = 0;
    int status=1;
    char *objects = jov_git_command(source,NULL,(const char*[]){"rev-parse","--path-format=absolute","--git-path","objects",NULL},262144,&n,&status);
    if (!objects || status || n < 2 || objects[n-1] != '\n' || objects[0] != '/' || memchr(objects,0,n)) {
        free(objects); return 1;
    }
    objects[n-1] = 0;
    const char *tmp = getenv("TMPDIR");
    char *root=realpath(tmp && *tmp ? tmp : "/tmp",NULL);
    char *work=root?snapshot_path(root,"/jovovich-snapshot-XXXXXX"):NULL;
    free(root);
    if (!work || !mkdtemp(work)) { free(work); free(objects); return 1; }
    *directory = work;
    char *init = jov_git_command(work,NULL,(const char*[]){"init","--bare","-q","--template=",
        strlen(base)==64 ? "--object-format=sha256" : "--object-format=sha1",NULL},262144,&n,&status);
    char *link = snapshot_path(work,"/source-objects"), *alt = snapshot_path(work,"/objects/info/alternates");
    int bad = !init || status || !link || !alt || symlink(objects,link);
    if (!bad) {
        FILE *f = fopen(alt,"w");
        if (!f) bad = 1;
        else { bad = fputs("../source-objects\n",f)==EOF; if (fclose(f)) bad=1; }
    }
    if (!bad) {
        char *head=snapshot_path(work,"/HEAD");
        FILE *f=head?fopen(head,"w"):NULL;
        free(head);
        if (!f) bad=1;
        else { bad=fprintf(f,"%s\n",base)<0; if (fclose(f)) bad=1; }
    }
    free(objects); free(init); free(link); free(alt);
    return bad;
}

static inline int jov_remove_git_snapshot(char *work) {
    if (!work) return 0;
    int rc=nftw(work,remove_snapshot_entry,16,FTW_DEPTH|FTW_PHYS);
    free(work);
    return rc;
}

#endif
