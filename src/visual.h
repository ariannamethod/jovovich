#ifndef JOV_VISUAL_H
#define JOV_VISUAL_H
#include "harness/qwen35_vision.h"
#include "examples/bpe.h"
nt_qwen35_vision *jov_visual_load(const char *path,const char *manifest,char hash[65]);
int jov_visual_choice(const char *line,size_t bytes,void *model,bpe_tokenizer *tok,
    nt_qwen35_vision *vision,float *logits,const char *weights,const char *tokenizer,const char *vision_hash);
#endif
