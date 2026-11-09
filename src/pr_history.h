#ifndef JOVOVICH_PR_HISTORY_H
#define JOVOVICH_PR_HISTORY_H
#include "review.h"

typedef struct {
    char repository[142], number[24], opened_at[21];
    int opened[3];
    struct {
        char commit[65], parent[65], source_base[65], source_head[65], merged_at[21];
        int clock[3];
        char source_version[65], *proof;
    } landing;
} jov_pr;

/* Bind GitHub metadata to the batch and, on landing, the event's independent SHA. */
int jov_pr_read(jov_pr *pr, const char *scope, const char *metadata,
                const char *base, const char *head, const jov_fact *fact, const char *landing_sha);
/* Add previously mismatched source paths and capture their verified first-parent order.
 * The caller owns the appended paths and landing.proof. */
int jov_pr_prepare_landing(const char *directory, jov_pr *pr, const char *repo, const char *batch,
                           const jov_fact *fact, const char *policy, const char *driver, char *paths[], int *count);
/* The caller has completed Git and driver verification for every emitted finding. */
int jov_pr_record(const char *directory, const jov_pr *pr, const jov_fact *fact,
                  const char *batch, const char *base, const char *head, FILE *findings, const char *coverage);
/* Cite earlier PR evidence for the currently measured paths, through the new PR base. */
int jov_pr_recall_snapshots(FILE *out, int json, const char *directory, const jov_pr *current,
                            const jov_fact *fact, const char *repo, const char *base, const char *coverage,
                            const char *const files[], int count);
/* A missing number lists checked PRs in the selected repository. */
int jov_pr_history(const char *directory, const char *scope, const char *number, const char *head,
                   const char *checkout, const char *file);
/* Record or check a spore fingerprint against one verified observation. */
int jov_pr_spore(const char *directory, const char *scope, const char *number,
                 const char *observation, const char *file, int write);
/* Compare the observations available at two knowledge cutoffs for one exact SHA. */
int jov_pr_compare_history(const char *directory, const char *scope, const char *number, const char *head,
                           const char *checkout, const char *file, const char *from, const char *to,
                           const char *from_journal, const char *through);
#endif
