#ifndef JOVOVICH_FACTS_H
#define JOVOVICH_FACTS_H

#include "review.h"

/* A missing JSON member is an absent receipt. A malformed member is an error. */
int jov_fact_decode(const char *json, jov_fact **result);
void jov_fact_free(jov_fact *fact);

/* The caller owns the writer descriptor through staging and commit.
 * Readers open one immutable checkpoint snapshot and need no lock. */
int jov_memory_select(const char *directory, const char *repository, const char *key,
                      int known_through, int expected_parent, const jov_fact *origin,
                      jov_fact **result, int *writer);
int jov_memory_commit(void);

#endif
