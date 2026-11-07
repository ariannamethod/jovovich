#ifndef JOVOVICH_READOUT_H
#define JOVOVICH_READOUT_H

enum { JOV_WIDTH = 1024 };
typedef struct {
    float center[JOV_WIDTH], scale;
    float weight[JOV_WIDTH+1]; /* Last entry is the intercept. */
} jov_readout;

int jov_readout_load(jov_readout *head, const char *path, const char *weights,
                     const char *tokenizer, char digest[65]);
int jov_readout_vector(const char *json, float out[JOV_WIDTH]);
int jov_readout_margin(const jov_readout *head, const float unit[JOV_WIDTH],
                       float base_margin, float *adjusted);
#endif
