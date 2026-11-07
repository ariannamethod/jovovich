#ifndef JOV_TRACE_GATE_H
#define JOV_TRACE_GATE_H

/* Bounded display for two sequences of up to 32 callback identifiers. */
typedef struct {
    int runs, differing, selected_mode;
    char observation[4800], prompt_sha256[65];
} jov_trace_receipt;

/* With review_context already set in AML, append at most one differential
 * observation. The required value comes from the supplied contract oracle. */
int jov_apply_trace_gate(const char *row,const char *id,const char *rule,const char *change,
                         jov_trace_receipt *receipt);
int jov_verify_trace_receipt(const char *listed,const jov_trace_receipt *receipt,const char *prompt);
#endif
