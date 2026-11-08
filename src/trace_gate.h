#ifndef JOV_TRACE_GATE_H
#define JOV_TRACE_GATE_H

#include <stdio.h>
typedef struct {
    char base[65], head[65], source_sha[65], harness_sha[65];
    int mode;
} jov_replay_ref;

int jov_replay_ref_read(const char *json, jov_replay_ref *ref);
void jov_replay_ref_json(FILE *out, const jov_replay_ref *ref);
void jov_replay_ref_markdown(FILE *out, const jov_replay_ref *ref);

/* The run points into the validated input row. */
typedef struct {
    const char *run;
    int meets_requirement;
    int unchanged_replay;
} jov_trace_measurement;

/* Bounded display for two sequences of up to 32 callback identifiers. */
typedef struct {
    int runs, differing, selected_mode;
    jov_replay_ref replay;
    jov_trace_measurement measurement;
    char observation[4800], prompt_sha256[65];
} jov_trace_receipt;

/* With review_context already set in AML, append at most one differential
 * observation. The required value comes from the supplied contract oracle. */
int jov_apply_trace_gate(const char *row,const char *id,const char *rule,const char *change,
                         jov_trace_receipt *receipt);
int jov_apply_trace_gate_source(const char *row,const char *id,const char *rule,const char *change,
                                jov_trace_receipt *receipt,const char *source);
/* Render the selected execution from an already verified input/answer pair. */
int jov_trace_write_change(FILE *out,const char *gate,const jov_trace_measurement *measurement,
                           const char *file,int json);
int jov_trace_reproduced(const char *gate, int mode, const char *base, const char *head, const char *oracle);
int jov_verify_trace_receipt(const char *listed,const jov_trace_receipt *receipt,const char *prompt);
#endif
