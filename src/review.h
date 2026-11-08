#ifndef JOVOVICH_REVIEW_H
#define JOVOVICH_REVIEW_H

#include <stdio.h>
#include "trace_gate.h"

typedef struct {
    const char *code; /* NULL when the original view passed through. */
    const char *prompt_sha256;
} jov_boundary_receipt;

typedef struct {
    const char *input_sha256, *weights_sha256, *tokenizer_sha256;
    int unix_day, second, millisecond;
    const char *readout_sha256; /* Present when an output adapter was active. */
    const jov_boundary_receipt *boundary;
    const jov_trace_receipt *trace;
} jov_execution;

typedef struct {
    const char *base, *head, *rules_path, *rules_blob;
    const char *rules_sha256, *diff_sha256;
    int first_line, last_line;
} jov_source;

/* A remembered repository rule and the Git review that first supplied this revision. */
typedef struct {
    char *repository, *key, *recorded_at;
    int sequence, supersedes;
    char *base, *head, *path, *quote;
    int first, last;
} jov_fact;

int jov_fact_valid(const jov_fact *fact);
void jov_fact_origin_json(FILE *out, const jov_fact *fact);
void jov_fact_json(FILE *out, const jov_fact *fact);
int jov_fact_same(const jov_fact *left, const jov_fact *right);

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
    const jov_execution *execution; /* optional for historical recorded demos */
    const jov_source *source; /* optional commit-resolved Git evidence */
    const jov_fact *fact; /* optional receipt for the selected rule */
} jov_review;

enum { JOV_OK = 0, JOV_INVALID = 1, JOV_IO_ERROR = 2 };

/* Ordered argmax: CONCERN wins an exact tie, matching the A/B readout. */
const char *jov_review_verdict(const jov_review *review);
int jov_review_validate(const jov_review *review);
/* Invalid records return JOV_INVALID before writing anything. */
int jov_review_markdown(FILE *out, const jov_review *review);
int jov_review_markdown_view(FILE *out, const jov_review *review, const char *model_code);
int jov_review_markdown_evidence(FILE *out, const jov_review *review, const char *model_code, const char *observation);
int jov_review_json(FILE *out, const jov_review *review);
int jov_source_validate(const jov_source *source);
int jov_source_json(FILE *out, const jov_source *source);

#endif
