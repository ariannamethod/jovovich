#ifndef JOV_BOUNDARY_VIEW_H
#define JOV_BOUNDARY_VIEW_H
#include "boundary.h"
#include "hash.h"
#include "ariannamethod.h"
#include "tools/narrow_json.h"

/* Rebuild the exact AML prompt for a review receipt. A run uses one view policy. */
static inline int jov_verify_boundary_view(const char *answer,const char *ctx,const char *rule,
                                           const char *change,const char *prepare,int index,int *policy) {
    const char *view=nj_get(nj_get(answer,"execution"),"boundary_view");
    int enabled=view!=NULL;
    if(index==0)*policy=enabled;
    if(*policy!=enabled)return 1;
    char code[JOV_BOUNDARY_CODE_SIZE],*model_ctx=NULL;
    if(view) {
        if(!nj_is(nj_get(view,"policy"),"signed-int-comparison/1"))return 1;
        int match=jov_boundary_context(ctx,rule,change,code,&model_ctx);
        const char *listed=nj_get(view,"code");
        if(match<0 || (match?!nj_is(listed,code):listed!=NULL)){free(model_ctx);return 1;}
    }
    int bad=am_set_var_text("review_context",model_ctx?model_ctx:ctx) || am_exec_file(prepare);
    free(model_ctx);
    if(bad || !view)return bad;
    char hash[65];const char *prompt=am_get_var_text("prompt");
    return !prompt || hash_bytes(prompt,strlen(prompt),hash) || !nj_is(nj_get(view,"prompt_sha256"),hash);
}
#endif
