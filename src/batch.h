#ifndef JOVOVICH_BATCH_H
#define JOVOVICH_BATCH_H
#include "review.h"
#define JOV_BATCH_MAX_FILES 64
#define JOV_BATCH_MAX_BYTES (16u*1024u*1024u)
typedef struct {
    const char *file,*id;
    jov_source source;
} jov_batch_item;
/* Domain-separated digest of ordered paths, context IDs and source records. */
int jov_batch_digest(const jov_batch_item *items,int count,char out[65]);
#endif
