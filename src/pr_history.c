#define _POSIX_C_SOURCE 200809L
#include "pr_history.h"
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
static int opening_clock(const char *s, int parts[3]) {
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
                const char *base, const char *head, const jov_fact *fact) {
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
    failed = !url || strcasecmp(expected, url) || opening_clock(stamp, pr->opened);
    if (!failed) memcpy(pr->opened_at, stamp, sizeof(pr->opened_at));
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

static int journal(const char *directory, const jov_pr *pr, int write, int *writer) {
    char prefix[69], name[100];
    float mode = (float)write;
    if (history_prefix(pr->repository, prefix)) return 1;
    snprintf(name, sizeof(name), "%s%s", prefix, pr->number);
    return jov_journal_open(directory, name, write, writer) ||
        am_set_var_text("repository_name", pr->repository) || am_set_var_text("pr_number", pr->number) ||
        am_set_var_text("opened_utc", pr->opened_at) || am_set_var_array("pr_mode", &mode, 1) ||
        am_exec_file("aml/pr-history.aml");
}

static void instant(FILE *out, const int parts[3]) {
    fprintf(out, "{\"schema\":\"janus.instant/1\",\"time_scale\":\"posix\",\"unix_day\":%d,"
            "\"second\":%d,\"millisecond\":%d}", parts[0], parts[1], parts[2]);
}

static char *evidence(FILE *findings, const jov_fact *fact, const char *batch, const char *base, const char *head, const char *coverage) {
    long length = ftell(findings);
    if (length < 0 || length > AM_MAX_STRING_BYTES || fseek(findings, 0, SEEK_SET)) return NULL;
    char *data = NULL, *line = NULL;
    size_t size = 0, cap = 0;
    FILE *out = open_memstream(&data, &size);
    if (!out) return NULL;
    fputc('{', out);
    json_field(out, "batch_id", batch);
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
    fputc('}', out);
    int failed = ferror(findings) || (!count && !coverage);
    free(line);
    if (fclose(out) || failed) { free(data); return NULL; }
    return data;
}

int jov_pr_record(const char *directory, const jov_pr *pr, const jov_fact *fact,
                  const char *batch, const char *base, const char *head, FILE *findings, const char *coverage) {
    struct timespec now;
    if (clock_gettime(CLOCK_REALTIME, &now) || now.tv_sec < 0) return 1;
    int checked[] = {(int)(now.tv_sec / 86400), (int)(now.tv_sec % 86400), (int)(now.tv_nsec / 1000000)};
    char *result = evidence(findings, fact, batch, base, head, coverage), *row = NULL;
    char key[65];
    int failed = 1, writer = -1;
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
        journal(directory, pr, 1, &writer) || jov_memory_commit();
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
#include "snapshot_recall.h"

int jov_pr_history(const char *directory, const char *scope, const char *number, const char *head,
                   const char *checkout, const char *file) {
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
        if (snapshot) failed = snapshot_history(&pr, snapshot, checkout, head, file);
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
