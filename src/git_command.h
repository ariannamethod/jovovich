#ifndef JOV_GIT_COMMAND_H
#define JOV_GIT_COMMAND_H
#include "process.h"
#include <stdio.h>
#include <string.h>

/* pack and replay use the same object and history lookup. */
static inline char *jov_git_command(const char *repo, const char *attr_commit,
                                    const char *const args[], size_t limit, size_t *length, int *code) {
    const char *path = getenv("PATH");
    if (!path) path = "/usr/bin:/bin";
    char *path_env = malloc(strlen(path) + 6);
    if (!path_env) return NULL;
    sprintf(path_env, "PATH=%s", path);
    /* Resolve revision expressions through the parents stored in the commits.
     * Grafts, shallow markers, replacement refs and cached commit graphs can
     * otherwise change the history selected by e.g. HEAD^ or --recall. */
    const char *argv[48] = {"env", "-i", path_env, "LC_ALL=C", "GIT_CONFIG_NOSYSTEM=1",
        "GIT_CONFIG_GLOBAL=/dev/null", "GIT_ATTR_NOSYSTEM=1", "GIT_NO_LAZY_FETCH=1",
        "GIT_GRAFT_FILE=/dev/null", "GIT_SHALLOW_FILE=", "git",
        "--no-pager", "--no-replace-objects", "--literal-pathspecs", "-c", "core.attributesFile=/dev/null",
        "-c", "advice.graftFileDeprecated=false", "-c", "core.commitGraph=false", "-C", repo};
    size_t a=0;
    while (argv[a]) a++;
    if (attr_commit) { argv[a++]="--attr-source"; argv[a++]=attr_commit; }
    for(size_t i=0;args[i];i++){if(a>=47){free(path_env);return NULL;}argv[a++]=args[i];}
    argv[a]=NULL;
    char *data = jov_command(argv, limit, length, code);
    free(path_env);
    return data;
}

/* A symlink is also stored as a blob. Bind the exact rule path, tree mode
 * and object ID before reading any historical quote. The -z listing uses
 * actual filename bytes, including tabs and newlines. */
static inline char *jov_git_rule_blob(const char *repo, const char *commit, const char *path) {
    const char *args[]={"ls-tree","--full-tree","-z",commit,"--",path,NULL};
    size_t len=0, width=strlen(commit), path_len=strlen(path);
    int status=1;
    char *entry=jov_git_command(repo,NULL,args,262144,&len,&status);
    const size_t prefix=sizeof("100644 blob ")-1;
    if (!entry || status || len!=prefix+width+1+path_len+1 ||
        (memcmp(entry,"100644 blob ",prefix) && memcmp(entry,"100755 blob ",prefix)) ||
        strspn(entry+prefix,"0123456789abcdef")!=width || entry[prefix+width]!='\t' ||
        memcmp(entry+prefix+width+1,path,path_len+1)) {
        free(entry);
        return NULL;
    }
    memmove(entry,entry+prefix,width);
    entry[width]=0;
    return entry;
}
#endif
