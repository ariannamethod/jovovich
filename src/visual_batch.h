#ifndef JOV_VISUAL_BATCH_H
#define JOV_VISUAL_BATCH_H
#include <stdio.h>
typedef struct {
    char *request,*comparison,*file,*id;
    char digest[65];
} jov_visual_batch;
/* The request is captured without surrounding JSONL whitespace. The digest
 * binds its exact bytes, both memory receipts and the verified base rule. */
int jov_visual_batch_load(jov_visual_batch *v,const char *memory,const char *request,
    const char *repository,int pr,const char *base,const char *head);
void jov_visual_batch_free(jov_visual_batch *v);
int jov_visual_batch_answer(const jov_visual_batch *v,const char *answer,const char *manifest,float *concern);
int jov_visual_batch_markdown(FILE *out,const jov_visual_batch *v,const char *answer);
#endif
