#ifndef JOVOVICH_REVIEW_H
#define JOVOVICH_REVIEW_H

#include <stdio.h>

/* Strings are UTF-8 and owned by the caller. Evidence is copied from context. */
typedef struct {
    const char *id;
    const char *model;
    const char *revision;
    const char *question;
    const char *file;
    const char *context;
    const char *rule_excerpt;
    const char *change_excerpt;
    double concern;
    double clean;
} jov_review;

enum { JOV_OK = 0, JOV_INVALID = 1, JOV_IO_ERROR = 2 };

/* Ordered argmax: CONCERN wins an exact tie, matching the A/B readout. */
const char *jov_review_verdict(const jov_review *review);
int jov_review_validate(const jov_review *review);
/* Invalid records return JOV_INVALID before writing anything. */
int jov_review_markdown(FILE *out, const jov_review *review);
int jov_review_json(FILE *out, const jov_review *review);

#endif
