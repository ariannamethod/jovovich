#ifndef JOV_GIT_CONTEXT_H
#define JOV_GIT_CONTEXT_H
#include "ariannamethod.h"
#include "hash.h"
#include <string.h>

static inline const char *jov_git_context(const char *file,const char *rule,const char *diff) {
    if (am_set_var_text("source_file",file) || am_set_var_text("source_rules",rule) ||
        am_set_var_text("source_diff",diff) || am_exec_file("aml/git-context.aml")) return NULL;
    return am_get_var_text("review_context");
}

static inline int jov_git_context_matches(const char *file,const char *rule,const char *diff,
                                          const char *context,const char *id) {
    const char *expected=jov_git_context(file,rule,diff);
    char digest[65];
    return expected && !strcmp(expected,context) && !hash_bytes(context,strlen(context),digest) && !strcmp(digest,id);
}
#endif
