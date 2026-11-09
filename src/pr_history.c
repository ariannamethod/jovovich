#define _POSIX_C_SOURCE 200809L
#include "pr_history.h"
#include "batch.h"
#include "facts.h"
#include "ariannamethod.h"
#include "hash.h"
#include "json.h"
#include "report_json.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <strings.h>
#include <time.h>
#include <unistd.h>

static int repository_name(const char *scope, char out[142]) {
    const char *slash = strchr(scope, '/');
    size_t n = strlen(scope);
    if (!slash || slash == scope || slash - scope > 39 || !slash[1] ||
        strlen(slash + 1) > 100 || !strcmp(slash + 1, ".") || !strcmp(slash + 1, "..")) return 1;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)scope[i];
        if (c >= 128 || !(isalnum(c) || c == '-' || scope + i == slash ||
            (scope + i > slash && (c == '.' || c == '_')))) return 1;
        out[i] = (char)tolower(c);
    }
    out[n] = 0;
    return 0;
}

/* GitHub createdAt is UTC, with whole seconds. AML validates the civil date. */
static int github_clock(const char *s, int parts[3]) {
    if (!s || strlen(s) != 20) return 1;
    const char *shape = "0000-00-00T00:00:00Z";
    for (int i = 0; i < 20; i++) {
        if (shape[i] == '0' ? !isdigit((unsigned char)s[i]) : s[i] != shape[i]) return 1;
    }
    int y, m, d, h, min, sec, day;
    if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2dZ", &y, &m, &d, &h, &min, &sec) != 6 ||
        h > 23 || min > 59 || sec > 59 || am_calendar_from_gregorian(y, m, d, &day)) return 1;
    parts[0] = day + AM_CALENDAR_UNIX_EPOCH_DAY;
    parts[1] = h * 3600 + min * 60 + sec;
    parts[2] = 0;
    return 0;
}

int jov_pr_read(jov_pr *pr, const char *scope, const char *metadata,
                const char *base, const char *head, const jov_fact *fact, const char *landing_sha) {
    if (repository_name(scope, pr->repository) || !fact || strcasecmp(pr->repository, fact->repository)) return 1;
    FILE *in = fopen(metadata, "rb");
    if (!in) return 1;
    char json[8193];
    size_t n = fread(json, 1, sizeof(json), in);
    int failed = ferror(in) || n == sizeof(json) || memchr(json, 0, n) != NULL;
    fclose(in);
    if (failed) return 1;
    json[n] = 0;
    const char *end = report_json_end(json, 0);
    long long number;
    if (!end || *nj_ws(end) || nj_int(nj_get(json, "number"), &number) || number <= 0 ||
        number > INT_MAX || !nj_is(nj_get(json, "baseRefOid"), base) || !nj_is(nj_get(json, "headRefOid"), head)) return 1;
    snprintf(pr->number, sizeof(pr->number), "%lld", number);
    char expected[212];
    snprintf(expected, sizeof(expected), "https://github.com/%s/pull/%s", pr->repository, pr->number);
    char *url = nj_string(nj_get(json, "url")), *stamp = nj_string(nj_get(json, "createdAt"));
    failed = !url || strcasecmp(expected, url) || github_clock(stamp, pr->opened);
    if (!failed) memcpy(pr->opened_at, stamp, sizeof(pr->opened_at));
    if (!failed && landing_sha) {
        char *merged = nj_string(nj_get(json, "mergedAt"));
        size_t width = strlen(head);
        failed = (width != 40 && width != 64) || strlen(landing_sha) != width ||
            strspn(landing_sha, "0123456789abcdef") != width || !strcmp(landing_sha, head) ||
            !nj_is(nj_get(json, "state"), "MERGED") ||
            !nj_is(nj_get(nj_get(json, "mergeCommit"), "oid"), landing_sha) || github_clock(merged, pr->landing.clock);
        if (!failed) {
            strcpy(pr->landing.commit, landing_sha);
            strcpy(pr->landing.source_head, head);
            strcpy(pr->landing.source_base, base);
            memcpy(pr->landing.merged_at, merged, sizeof(pr->landing.merged_at));
        }
        free(merged);
    }
    free(url);
    free(stamp);
    return failed;
}

static int history_prefix(const char *scope, char prefix[69]) {
    char digest[65];
    if (hash_bytes(scope, strlen(scope), digest)) return 1;
    snprintf(prefix, 69, "pr-%s-", digest);
    return 0;
}

static int open_pr_journal(const char *directory, const jov_pr *pr, int write, int *writer) {
    char prefix[69], name[100];
    if (history_prefix(pr->repository, prefix)) return 1;
    snprintf(name, sizeof(name), "%s%s", prefix, pr->number);
    return jov_journal_open(directory, name, write, writer);
}

static int read_or_stage(const jov_pr *pr, float mode) {
    return am_set_var_text("repository_name", pr->repository) || am_set_var_text("pr_number", pr->number) ||
        am_set_var_text("opened_utc", pr->opened_at) || am_set_var_array("pr_mode", &mode, 1) ||
        am_exec_file("aml/pr-history.aml");
}

static int journal(const char *directory, const jov_pr *pr, int write, int *writer) {
    return open_pr_journal(directory, pr, write, writer) || read_or_stage(pr, (float)write);
}

static void instant(FILE *out, const int parts[3]) {
    fprintf(out, "{\"schema\":\"janus.instant/1\",\"time_scale\":\"posix\",\"unix_day\":%d,"
            "\"second\":%d,\"millisecond\":%d}", parts[0], parts[1], parts[2]);
}

static char *evidence(FILE *findings, const jov_fact *fact, const char *batch, const char *base, const char *head, const char *coverage, const char *landing) {
    long length = ftell(findings);
    if (length < 0 || length > AM_MAX_STRING_BYTES || fseek(findings, 0, SEEK_SET)) return NULL;
    char *data = NULL, *line = NULL;
    size_t size = 0, cap = 0;
    FILE *out = open_memstream(&data, &size);
    if (!out) return NULL;
    fputc('{', out);
    json_field(out, landing ? "source_batch_id" : "batch_id", batch);
    fputc(',', out); json_field(out, "base_commit", base);
    fputc(',', out); json_field(out, "head_commit", head);
    fputs(",\"fact\":", out); jov_fact_json(out, fact);
    fputs(",\"findings\":[", out);
    int count = 0;
    ssize_t n;
    while ((n = getline(&line, &cap, findings)) > 0) {
        if (count++) fputc(',', out);
        fwrite(line, 1, (size_t)n - (line[n-1] == '\n'), out);
    }
    fputc(']', out);
    if (coverage) fprintf(out, ",\"snapshot_coverage\":%s", coverage);
    if (landing) fprintf(out, ",\"landing\":%s", landing);
    fputc('}', out);
    int failed = ferror(findings) || (!count && !coverage);
    free(line);
    if (fclose(out) || failed) { free(data); return NULL; }
    return data;
}

/* Ignore concurrent landing retries. Any new source observation requires a
 * new plan before publishing results from a renderer that runs outside the lock. */
static int source_version(const AM_List *rows, const AM_List *keys, char digest[65]) {
    char buffer[256*64];
    size_t used = 0;
    if (!rows || !keys || rows->len != keys->len || rows->len > 256) return 1;
    for (int i = 0; i < rows->len; i++) {
        if (nj_get(nj_get(rows->items[i]->data, "evidence"), "landing")) continue;
        const char *key = keys->items[i]->data;
        if (strlen(key) != 64 || strspn(key, "0123456789abcdef") != 64) return 1;
        memcpy(buffer + used, key, 64); used += 64;
    }
    return hash_bytes(buffer, used, digest);
}

int jov_pr_record(const char *directory, const jov_pr *pr, const jov_fact *fact,
                  const char *batch, const char *base, const char *head, FILE *findings, const char *coverage) {
    struct timespec now;
    if (clock_gettime(CLOCK_REALTIME, &now) || now.tv_sec < 0) return 1;
    int checked[] = {(int)(now.tv_sec / 86400), (int)(now.tv_sec % 86400), (int)(now.tv_nsec / 1000000)};
    char *result = NULL, *row = NULL;
    const char *landing = pr->landing.proof;
    char key[65];
    int failed = 1, writer = -1;
    if (open_pr_journal(directory, pr, 1, &writer)) goto done;
    if (*pr->landing.commit) {
        char version[65];
        if (!landing || !coverage || read_or_stage(pr, 0) ||
            source_version(am_get_var_list("observations"), am_get_var_list("keys"), version)) goto done;
        if (strcmp(version, pr->landing.source_version)) {
            fputs("Source checks changed during rendering; retry the landing.\n", stderr);
            goto done;
        }
        float merge_clock[] = {pr->landing.clock[0], pr->landing.clock[1], pr->landing.clock[2]};
        char identity[225];
        snprintf(identity, sizeof(identity), "%s/%s/%s/%s", pr->landing.source_base, pr->landing.source_head,
                 pr->landing.commit, pr->landing.merged_at);
        if (am_set_var_text("merge_identity", identity) || am_set_var_array("merge_clock", merge_clock, 3)) goto done;
    }
    result = evidence(findings, fact, batch, base, head, coverage, landing);
    if (!result || hash_bytes(result, strlen(result), key)) goto done;
    size_t n = 0;
    FILE *out = open_memstream(&row, &n);
    if (!out) goto done;
    fputs("{\"opened_at\":", out); instant(out, pr->opened);
    fputs(",\"checked_at\":", out); instant(out, checked);
    fprintf(out, ",\"evidence\":%s}", result);
    if (fclose(out) || n > AM_MAX_STRING_BYTES) goto done;
    float opening[] = {pr->opened[0], pr->opened[1], pr->opened[2]};
    float ending[] = {checked[0], checked[1], checked[2]};
    failed = am_set_var_array("open_clock", opening, 3) || am_set_var_array("check_clock", ending, 3) ||
        am_set_var_text("observation_key", key) || am_set_var_text("observation", row) ||
        read_or_stage(pr, landing ? 2 : 1) || jov_memory_commit();
done:
    if (writer >= 0) close(writer);
    free(row); free(result);
    return failed;
}

typedef struct { int number, checks; char opened[21]; } pr_summary;

static int opening_order(const void *left, const void *right) {
    const pr_summary *a = left, *b = right;
    int order = strcmp(a->opened, b->opened);
    return order ? order : a->number - b->number;
}

static int valid_number(const char *s, size_t n) {
    if (!n || n > 10 || s[0] == '0' || strspn(s, "0123456789") != n) return 0;
    return strtoll(s, NULL, 10) <= INT_MAX;
}

/* Open only checkpoint names belonging to this repository; concurrent additions
 * can appear on the next listing. Every opened checkpoint is a complete snapshot. */
static int checkpoint_numbers(const char *directory, const char *repository, int **numbers, size_t *count) {
    char prefix[69];
    if (history_prefix(repository, prefix)) return 1;
    DIR *dir = opendir(directory);
    if (!dir) return 1;
    size_t capacity = 0;
    int failed = 1;
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(dir);
        if (!entry) { failed = errno != 0; break; }
        if (strncmp(entry->d_name, prefix, strlen(prefix))) continue;
        const char *number = entry->d_name + strlen(prefix);
        size_t n = strspn(number, "0123456789");
        if (strcmp(number + n, ".checkpoint") || !valid_number(number, n)) continue;
        if (*count == capacity) {
            capacity = capacity ? capacity * 2 : 16;
            int *grown = realloc(*numbers, capacity * sizeof(**numbers));
            if (!grown) break;
            *numbers = grown;
        }
        (*numbers)[(*count)++] = atoi(number);
    }
    closedir(dir);
    return failed;
}

static int list_prs(const char *directory, jov_pr *pr) {
    int *numbers = NULL, writer = -1, failed = 1;
    size_t count = 0;
    pr_summary *list = NULL;
    if (checkpoint_numbers(directory, pr->repository, &numbers, &count)) goto done;
    if (count && !(list = calloc(count, sizeof(*list)))) goto done;
    for (size_t i = 0; i < count; i++) {
        snprintf(pr->number, sizeof(pr->number), "%d", numbers[i]);
        if (journal(directory, pr, 0, &writer)) goto done;
        const char *opened = am_get_var_text("opened");
        const AM_List *rows = am_get_var_list("observations");
        if (!rows || !opened || strlen(opened) != 20) goto done;
        list[i] = (pr_summary){.number=numbers[i], .checks=rows->len};
        memcpy(list[i].opened, opened, 21);
    }
    if (count > 1) qsort(list, count, sizeof(*list), opening_order);
    printf("{\"schema\":\"jovovich.repository-prs/1\",\"repository\":\"%s\",\"pull_requests\":[", pr->repository);
    for (size_t i = 0; i < count; i++) {
        if (i) fputc(',', stdout);
        printf("{\"number\":%d,\"created_at\":", list[i].number);
        json_string(stdout, list[i].opened);
        printf(",\"observations\":%d}", list[i].checks);
    }
    puts("]}");
    failed = ferror(stdout) || fflush(stdout);
done:
    free(numbers); free(list);
    return failed;
}

#include "snapshot_history.h"
/* A previously failing snapshot can be reverted out of the final source diff.
 * Recheck it on integration, under the same route and renderer. */
static int include_mismatches(const char *evidence, char *paths[], int *count) {
    int bad = 0;
    for (const char *f = nj_first(nj_get(evidence, "findings"), &bad); f && !bad; f = nj_next(f, ']', &bad)) {
        if (!nj_is(nj_get(f, "kind"), "snapshot") || !nj_is(nj_get(f, "status"), "mismatch")) continue;
        char *path = nj_string(nj_get(f, "file"));
        if (!path || !*path) { free(path); return 1; }
        int i = 0;
        while (i < *count && strcmp(paths[i], path)) i++;
        if (i < *count) free(path);
        else if (*count == JOV_BATCH_MAX_FILES) { free(path); return 1; }
        else paths[(*count)++] = path;
    }
    return bad;
}

int jov_pr_prepare_landing(const char *directory, jov_pr *pr, const char *repo, const char *batch,
                           const jov_fact *fact, const char *policy, const char *driver, char *paths[], int *path_count) {
    int writer = -1;
    if (journal(directory, pr, 0, &writer)) return 1;
    const char *opened = am_get_var_text("opened");
    if (!opened || strcmp(opened, pr->opened_at)) return 1;
    const AM_List *rows = am_get_var_list("observations"), *keys = am_get_var_list("keys");
    if (source_version(rows, keys, pr->landing.source_version)) return 1;
    snapshot_point points[256] = {0};
    int count = 0, final = 0;
    for (int i = 0; i < rows->len; i++) {
        const char *e = nj_get(rows->items[i]->data, "evidence");
        const char *cov = nj_get(e, "snapshot_coverage");
        if (nj_get(e, "landing") || !nj_is(nj_get(cov, "schema"), "jovovich.snapshot-coverage/1") ||
            !nj_is(nj_get(cov, "routes_sha256"), policy) || !nj_is(nj_get(cov, "harness_sha256"), driver)) continue;
        jov_fact *saved = NULL;
        if (jov_fact_decode(nj_get(e, "fact"), &saved)) return 1;
        int same = jov_fact_same(fact, saved);
        jov_fact_free(saved);
        if (!same) continue;
        char *head = nj_string(nj_get(e, "head_commit"));
        if (!head || strlen(head) != strlen(pr->landing.source_head) ||
            strspn(head, "0123456789abcdef") != strlen(head)) { free(head); return 1; }
        snapshot_point *p = &points[count++];
        strcpy(p->head, head); free(head);
        p->ordinal = i; p->distance = -1; p->entry = e;
        if (!strcmp(p->head, pr->landing.source_head) && nj_is(nj_get(e, "batch_id"), batch) &&
            nj_is(nj_get(e, "base_commit"), pr->landing.source_base)) final = 1;
    }
    if (!final || rank_history(repo, pr->landing.source_head, points, count)) return 1;
    qsort(points, (size_t)count, sizeof(*points), oldest_first);
    while (count && points[count-1].distance < 0) count--;
    size_t size = 0;
    FILE *out = open_memstream(&pr->landing.proof, &size);
    if (!out) return 1;
    fputs("{\"schema\":\"jovovich.pr-landing/1\",", out);
    json_field(out, "source_base", pr->landing.source_base); fputc(',', out);
    json_field(out, "source_head", pr->landing.source_head); fputc(',', out);
    json_field(out, "merge_commit", pr->landing.commit);
    fputs(",\"merged_at\":", out); instant(out, pr->landing.clock);
    fputs(",\"source_observations\":[", out);
    int bad = 0;
    for (int i = 0; i < count; i++) {
        if (include_mismatches(points[i].entry, paths, path_count)) { bad = 1; break; }
        if (i) fputc(',', out);
        json_string(out, keys->items[points[i].ordinal]->data);
    }
    fputs("],\"source_history\":[", out);
    for (int i = 0; i < count; i++) {
        if (i && points[i].distance == points[i-1].distance) continue;
        if (i) fputc(',', out);
        json_string(out, points[i].head);
    }
    fputs("]}", out);
    return fclose(out) || bad;
}

#include "snapshot_recall.h"
#include "snapshot_compare.h"

static int read_pr_history(const char *directory, const char *scope, const char *number, const char *head,
                           const char *checkout, const char *file, const history_window *window) {
    jov_pr pr = {0};
    if (repository_name(scope, pr.repository) ||
        (number && !valid_number(number, strlen(number))) ||
        (head && ((strlen(head) != 40 && strlen(head) != 64) || strspn(head, "0123456789abcdef") != strlen(head)))) return 1;
    int writer = -1, failed = 1, count = 0;
    am_init(); am_persistent_mode(1);
    if (!number) { failed = list_prs(directory, &pr); goto done; }
    memcpy(pr.number, number, strlen(number) + 1);
    if (journal(directory, &pr, 0, &writer)) goto done;
    const AM_List *rows = am_get_var_list("observations");
    const char *opened = am_get_var_text("opened");
    if (!rows || !opened) goto done;
    if (file) {
        /* The AML resolution program executes while the JSON views are in use. */
        AM_List *snapshot = am_list_clone(rows);
        if (snapshot && window) {
            AM_List *keys = am_list_clone(am_get_var_list("keys"));
            if (keys) failed = compare_snapshots(&pr, snapshot, keys, checkout, head, file, window);
            am_list_free(keys);
        } else if (snapshot) failed = snapshot_history(&pr, snapshot, checkout, head, file);
        am_list_free(snapshot);
        goto done;
    }
    printf("{\"schema\":\"jovovich.pr-history/1\",\"repository\":\"%s\",\"number\":%s,\"created_at\":", pr.repository, number);
    if (*opened) json_string(stdout, opened); else fputs("null", stdout);
    fputs(",\"requested_head\":", stdout);
    if (head) json_string(stdout, head); else fputs("null", stdout);
    fputs(",\"observations\":[", stdout);
    int measured = 0;
    for (int i = 0; i < rows->len; i++) {
        AM_String *row = am_list_get(rows, i);
        if (!row) goto done;
        if (!head || nj_is(nj_get(nj_get(row->data, "evidence"), "head_commit"), head)) {
            int bad = 0;
            if (nj_first(nj_get(nj_get(row->data, "evidence"), "findings"), &bad)) measured++;
            if (bad) { am_string_free(row); goto done; }
            if (count++) fputc(',', stdout);
            fputs(row->data, stdout);
        }
        am_string_free(row);
    }
    printf("],\"status\":\"%s\"}\n", measured ? "checked" : "unverified");
    failed = ferror(stdout) || fflush(stdout);
done:
    if (failed) fprintf(stderr, "Cannot read PR history: %s\n", am_get_error());
    am_persistent_mode(0);
    return failed;
}

int jov_pr_history(const char *directory, const char *scope, const char *number, const char *head,
                   const char *checkout, const char *file) {
    return read_pr_history(directory, scope, number, head, checkout, file, NULL);
}

int jov_pr_compare_history(const char *directory, const char *scope, const char *number, const char *head,
                           const char *checkout, const char *file, const char *from, const char *to,
                           const char *from_journal, const char *through) {
    history_window window = {from, to, from_journal, through};
    return read_pr_history(directory, scope, number, head, checkout, file, &window);
}
