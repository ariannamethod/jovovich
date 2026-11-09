#define _XOPEN_SOURCE 700
#include "facts.h"
#include "ariannamethod.h"
#include "report_json.h"
#include <fcntl.h>
#include <limits.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int number(const char *json, const char *key, int *value) {
    long long raw;
    if (nj_int(nj_get(json, key), &raw) || raw < 0 || raw > INT_MAX) return 1;
    *value = (int)raw;
    return 0;
}

static int member_count(const char *json) {
    int bad = 0, count = 0;
    for (const char *k = nj_first(json, &bad); k && !bad; ) {
        const char *v = nj_value(k, &bad);
        if (bad) break;
        ++count;
        k = nj_next(v, '}', &bad);
    }
    return bad ? -1 : count;
}

static int read_origin(const char *json, jov_fact *f) {
    if (member_count(json) != 6) return 1;
    f->base = nj_string(nj_get(json, "base_commit"));
    f->head = nj_string(nj_get(json, "head_commit"));
    f->path = nj_string(nj_get(json, "rules_path"));
    f->quote = nj_string(nj_get(json, "rule_excerpt"));
    return !f->base || !f->head || !f->path || !f->quote ||
        number(json, "rule_first_line", &f->first) || number(json, "rule_last_line", &f->last);
}

void jov_fact_free(jov_fact *f) {
    if (!f) return;
    free(f->repository);
    free(f->key);
    free(f->recorded_at);
    free(f->base);
    free(f->head);
    free(f->path);
    free(f->quote);
    free(f);
}

int jov_fact_decode(const char *json, jov_fact **result) {
    *result = NULL;
    if (!json) return 0;
    if (!report_json_end(json, 0) || member_count(json) != 7 || !nj_is(nj_get(json, "schema"), "jovovich.rule-fact/1")) return 1;
    jov_fact *f = calloc(1, sizeof(*f));
    if (!f) return 1;
    f->repository = nj_string(nj_get(json, "repository"));
    f->key = nj_string(nj_get(json, "key"));
    f->recorded_at = nj_string(nj_get(json, "recorded_at"));
    if (number(json, "sequence", &f->sequence) || number(json, "supersedes", &f->supersedes) ||
        read_origin(nj_get(json, "origin"), f) || !jov_fact_valid(f)) {
        jov_fact_free(f);
        return 1;
    }
    *result = f;
    return 0;
}

static int lock_writer(const char *path) {
    int fd = open(path, O_CREAT | O_RDWR | O_NOFOLLOW, 0600);
    struct flock lock = {.l_type = F_WRLCK, .l_whence = SEEK_SET};
    struct stat info;
    if (fd < 0) return -1;
    int rc = -1;
    if (!fstat(fd, &info) && S_ISREG(info.st_mode)) {
        do { rc = fcntl(fd, F_SETLKW, &lock); } while (rc < 0 && errno == EINTR);
    }
    if (rc == 0) return fd;
    close(fd);
    return -1;
}

/* Journal callers construct checkpoint names from validated inputs. */
int jov_journal_open(const char *directory, const char *name, int writing, int *writer) {
    char *root = realpath(directory, NULL);
    if (!root) { perror(directory); return 1; }
    size_t capacity = strlen(root) + strlen(name) + sizeof("/.checkpoint");
    char *path = malloc(capacity);
    int failed = 1;
    if (!path) goto done;
    if (writing) {
        snprintf(path, capacity, "%s/%s.lock", root, name);
        *writer = lock_writer(path);
        if (*writer < 0) { perror(path); goto done; }
    }
    snprintf(path, capacity, "%s/%s.checkpoint", root, name);
    struct stat info;
    if (lstat(path, &info) == 0 ? !S_ISREG(info.st_mode) : errno != ENOENT) goto done;
    failed = am_set_var_text("memory_path", path);
done:
    free(path);
    free(root);
    return failed;
}

static int stage_origin(const jov_fact *origin) {
    struct timespec now;
    struct tm utc;
    char stamp[32];
    if (strlen(origin->quote) > 16384) {
        fputs("Remembered rule exceeds 16 KiB. Select a smaller line range.\n", stderr);
        return 1;
    }
    if (clock_gettime(CLOCK_REALTIME, &now) ||
        !gmtime_r(&now.tv_sec, &utc) || strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &utc) != 19)
        return 1;
    snprintf(stamp + 19, sizeof(stamp) - 19, ".%03dZ", (int)(now.tv_nsec / 1000000));
    char *json = NULL;
    size_t length = 0;
    FILE *out = open_memstream(&json, &length);
    if (!out) return 1;
    jov_fact_origin_json(out, origin);
    int failed = fclose(out) || am_set_var_text("new_origin", json) || am_set_var_text("recorded_utc", stamp);
    free(json);
    return failed;
}

int jov_memory_select(const char *directory, const char *repository, const char *key,
                      int known_through, int expected_parent, const jov_fact *origin,
                      jov_fact **result, int *writer) {
    *result = NULL;
    int failed = 1;
    if (jov_journal_open(directory, "rules", origin != NULL, writer) || (origin && stage_origin(origin))) return 1;
    float args[] = {origin != NULL, (float)known_through, (float)expected_parent};
    if (am_set_var_text("repository_name", repository) ||
        am_set_var_text("fact_key", key) || am_set_var_array("memory_args", args, 3) ||
        am_exec_file("aml/rule-memory.aml")) {
        fprintf(stderr, "AML fact memory: %s\n", am_get_error());
        goto done;
    }
    const char *json = am_get_var_text("fact_origin");
    const char *clock = am_get_var_text("fact_clock");
    jov_fact *f = calloc(1, sizeof(*f));
    if (!f) goto done;
    f->repository = strdup(repository);
    f->key = strdup(key);
    f->sequence = (int)am_get_var_float("revision");
    f->supersedes = (int)am_get_var_float("predecessor");
    f->recorded_at = clock ? strdup(clock) : NULL;
    if (!json || read_origin(json, f) || !jov_fact_valid(f)) {
        jov_fact_free(f);
        goto done;
    }
    *result = f;
    failed = 0;
done:
    return failed;
}

int jov_memory_commit(void) {
    if (am_exec_file("aml/commit-memory.aml")) {
        fprintf(stderr, "AML fact commit: %s\n", am_get_error());
        return 1;
    }
    if (am_get_var_float("save_status") == 2)
        fputs("Fact committed; directory synchronization unconfirmed. Read back the receipt.\n", stderr);
    return 0;
}
