#include "readout.h"
#include "hash.h"
#include "report_json.h"
#include "notorch.h"
#include <math.h>

int jov_readout_vector(const char *json, float out[JOV_WIDTH]) {
    if (!json || *json != '[') return 1;
    int bad=0, n=0;
    for (const char *v=nj_first(json,&bad); v; v=nj_next(v,']',&bad)) {
        double x;
        if (n==JOV_WIDTH || nj_number(v,&x) || !isfinite((float)x)) return 1;
        out[n++]=(float)x;
    }
    return bad || n!=JOV_WIDTH;
}

int jov_readout_load(jov_readout *head, const char *path, const char *weights,
                     const char *tokenizer, char digest[65]) {
    size_t size;
    char *json=nj_load(path,&size);
    if (!json) return 1;
    const char *end=report_json_end(json,0);
    double scale, bias;
    int bad=!end || *nj_ws(end) || !nj_is(nj_get(json,"schema"),"jovovich.readout/1")
        || !nj_is(nj_get(json,"weights_sha256"),weights)
        || !nj_is(nj_get(json,"tokenizer_sha256"),tokenizer)
        || nj_number(nj_get(json,"scale"),&scale) || !isfinite((float)scale) || (float)scale<=0
        || nj_number(nj_get(json,"bias"),&bias) || !isfinite((float)bias)
        || jov_readout_vector(nj_get(json,"center"),head->center)
        || jov_readout_vector(nj_get(json,"weight"),head->weight)
        || hash_bytes(json,size,digest);
    if (!bad) {head->scale=(float)scale;head->weight[JOV_WIDTH]=(float)bias;}
    free(json);
    return bad;
}

int jov_readout_margin(const jov_readout *head, const float unit[JOV_WIDTH],
                       float base_margin, float *adjusted) {
    float centered[JOV_WIDTH], delta;
    for (int j=0; j<JOV_WIDTH; j++) centered[j]=(unit[j]-head->center[j])/head->scale;
    if (nt_linear_values(head->weight,head->weight+JOV_WIDTH,centered,1,JOV_WIDTH,&delta)) return 1;
    *adjusted=base_margin+delta;
    return !isfinite(*adjusted);
}
