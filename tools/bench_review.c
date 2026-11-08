/* Time one fresh reviewer and five serial requests to the same process. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "hash.h"
#include "json.h"
#include "report_json.h"

enum { WARM_RUNS = 5 };
static const char input_path[] = "examples/run-selection/git-input.jsonl";
static const char answer_path[] = "examples/run-selection/git-answer.jsonl";

static double now_ms(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) { perror("clock_gettime"); exit(1); }
    return t.tv_sec * 1000.0 + t.tv_nsec / 1e6;
}

static int json_object(const char *s) {
    if (!s || *nj_ws(s) != '{') return 0;
    const char *end = report_json_end(s, 0);
    return end && !*nj_ws(end);
}

static int same_string(const char *actual, const char *ref, const char *key) {
    char *wanted = nj_string(nj_get(ref, key));
    int ok = wanted && nj_is(nj_get(actual, key), wanted);
    free(wanted);
    return ok;
}

static int matches_reference(const char *row, const char *ref) {
    if (!json_object(row) || !same_string(row, ref, "id")) return 0;
    const char *exec = nj_get(row, "execution"), *ref_exec = nj_get(ref, "execution");
    const char *trace = nj_get(exec, "trace_witness"), *ref_trace = nj_get(ref_exec, "trace_witness");
    const char *choice = nj_get(row, "choice"), *ref_choice = nj_get(ref, "choice");
    const char *names[] = {"CONCERN", "CLEAN"};
    long long mode, ref_mode;
    if (!same_string(exec, ref_exec, "weights_sha256") ||
        !same_string(exec, ref_exec, "tokenizer_sha256") ||
        !same_string(exec, ref_exec, "input_sha256") ||
        !same_string(trace, ref_trace, "prompt_sha256") ||
        nj_int(nj_get(trace, "selected_mode"), &mode) ||
        nj_int(nj_get(ref_trace, "selected_mode"), &ref_mode) || mode != ref_mode ||
        !same_string(choice, ref_choice, "verdict")) return 0;
    for (size_t i = 0; i < 2; i++) {
        double p, target;
        if (nj_number(nj_get(nj_get(choice, "probabilities"), names[i]), &p) ||
            nj_number(nj_get(nj_get(ref_choice, "probabilities"), names[i]), &target) ||
            !isfinite(p) || !isfinite(target) || fabs(p - target) > 2e-4) return 0;
    }
    return 1;
}

static int compare_ms(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s MODEL.gguf TOKENIZER.gguf (from the repository root)\n", argv[0]);
        return 2;
    }
    size_t size;
    char *input = nj_load(input_path, &size), *ref = nj_load(answer_path, NULL);
    char reference_hash[65];
    if (!input || !size || strchr(input, '\n') != input + size - 1 ||
        !json_object(input) || !json_object(ref) || hash_bytes(ref, strlen(ref), reference_hash)) {
        fputs("Benchmark requires the recorded single review and answer.\n", stderr);
        return 1;
    }
    if (setenv("NT_ATTN_THREADS", "4", 1) || setenv("OPENBLAS_NUM_THREADS", "4", 1) ||
        setenv("VECLIB_MAXIMUM_THREADS", "4", 1)) { perror("setenv"); return 1; }
    struct utsname host;
    if (uname(&host)) { perror("uname"); return 1; }
    int in[2], out[2];
    if (pipe(in) || pipe(out)) { perror("pipe"); return 1; }
    double start = now_ms();
    pid_t child = fork();
    if (child < 0) { perror("fork"); return 1; }
    if (!child) {
        if (dup2(in[0], STDIN_FILENO) < 0 || dup2(out[1], STDOUT_FILENO) < 0) _exit(126);
        if (in[0] != STDIN_FILENO) close(in[0]);
        close(out[0]); close(in[1]); close(out[1]);
        execl("./build/jovovich", "jovovich", argv[1], argv[2], "--json",
              "--canonical-boundaries", (char *)NULL);
        perror("./build/jovovich");
        _exit(127);
    }
    close(in[0]); close(out[1]);
    signal(SIGPIPE, SIG_IGN);
    FILE *requests = fdopen(in[1], "w"), *answers = fdopen(out[0], "r");
    int ok = requests && answers;
    if (!ok) perror("fdopen");
    char *row = NULL;
    size_t capacity = 0;
    double samples[1 + WARM_RUNS];
    for (int i = 0; ok && i <= WARM_RUNS; i++) {
        if (i) start = now_ms();
        if (fputs(input, requests) == EOF || fflush(requests)) { perror("review input"); ok = 0; break; }
        ssize_t n = getline(&row, &capacity, answers);
        samples[i] = now_ms() - start;
        ok = n > 0 && row[n-1] == '\n' && (size_t)n == strlen(row) && matches_reference(row, ref);
        if (!ok) fprintf(stderr, "Review %d missing or different from %s\n", i + 1, answer_path);
    }
    if (requests) { if (fclose(requests)) ok = 0; } else close(in[1]);
    if (answers) {
        if (ok && (fgetc(answers) != EOF || ferror(answers))) {
            fputs("Unexpected output after the last review.\n", stderr); ok = 0;
        }
        fclose(answers);
    } else close(out[0]);
    int status;
    pid_t waited;
    do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
    free(row); free(ref); free(input);
    if (!ok || waited < 0 || !WIFEXITED(status) || WEXITSTATUS(status)) return 1;

    fputs("{\"schema\":\"jovovich.review-latency/1\",", stdout);
    json_field(stdout, "system", host.sysname); fputc(',', stdout);
    json_field(stdout, "release", host.release); fputc(',', stdout);
    json_field(stdout, "arch", host.machine); fputc(',', stdout);
    json_field(stdout, "reference", answer_path); fputc(',', stdout);
    json_field(stdout, "reference_sha256", reference_hash);
    printf(",\"requested_threads\":4,\"first_answer_ms\":%.3f,\"resident_ms\":[", samples[0]);
    for (int i = 1; i <= WARM_RUNS; i++) printf("%s%.3f", i > 1 ? "," : "", samples[i]);
    qsort(samples + 1, WARM_RUNS, sizeof(samples[0]), compare_ms);
    printf("],\"resident_median_ms\":%.3f}\n", samples[1 + WARM_RUNS / 2]);
    return fflush(stdout) || ferror(stdout);
}
