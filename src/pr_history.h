#ifndef JOVOVICH_PR_HISTORY_H
#define JOVOVICH_PR_HISTORY_H
#include "review.h"

typedef struct {
    char repository[142], number[24], opened_at[21];
    int opened[3];
} jov_pr;

/* Decode the five-field GitHub projection and bind it to the checked batch. */
int jov_pr_read(jov_pr *pr, const char *scope, const char *metadata,
                const char *base, const char *head, const jov_fact *fact);
/* The caller has completed Git and driver verification for every emitted finding. */
int jov_pr_record(const char *directory, const jov_pr *pr, const jov_fact *fact,
                  const char *batch, const char *base, const char *head, FILE *findings);
/* A missing number lists checked PRs in the selected repository. */
int jov_pr_history(const char *directory, const char *scope, const char *number, const char *head);
#endif
