#ifndef JOV_SNAPSHOT_COMPARE_H
#define JOV_SNAPSHOT_COMPARE_H

typedef struct { const char *from, *to, *from_journal, *through; } history_window;

typedef struct {
    snapshot_point point;
    int clock[3], known_before;
    const char *id;
} timed_check;

static int clock_order(const int left[3], const int right[3], int *order) {
    int args[] = {left[0], left[1], left[2], right[0], right[1], right[2]};
    AM_CalendarReply reply;
    if (am_calendar_query(AM_CAL_COMPARE, args, 6, &reply)) return 1;
    *order = reply.scalar;
    return 0;
}

/* The public CLI takes UTC to the same precision as a recorded JANUS instant. */
static int cutoff_time(const char *text, int clock[3]) {
    if (strlen(text) == 24) {
        if (text[19] != '.' || strspn(text + 20, "0123456789") != 3 || text[23] != 'Z') return 1;
        char seconds[21];
        memcpy(seconds, text, 19);
        memcpy(seconds + 19, "Z", 2);
        if (github_clock(seconds, clock)) return 1;
        clock[2] = (text[20]-'0')*100 + (text[21]-'0')*10 + text[22]-'0';
    } else if (github_clock(text, clock)) return 1;
    return 0;
}

static int checked_time(const char *entry, int clock[3]) {
    const char *instant = nj_get(entry, "checked_at");
    const char *fields[] = {"unix_day", "second", "millisecond"};
    if (!nj_is(nj_get(instant, "schema"), "janus.instant/1") ||
        !nj_is(nj_get(instant, "time_scale"), "posix")) return 1;
    for (int i = 0; i < 3; i++) {
        long long n;
        if (nj_int(nj_get(instant, fields[i]), &n) || n < INT_MIN || n > INT_MAX) return 1;
        clock[i] = (int)n;
    }
    return 0;
}

static int compare_checks(const void *left, const void *right) {
    const timed_check *a = left, *b = right;
    int order = strcmp(a->point.stream, b->point.stream);
    if (order) return order;
    if (a->known_before != b->known_before) return b->known_before - a->known_before;
    for (int i = 0; i < 3; i++)
        if (a->clock[i] != b->clock[i]) return a->clock[i] < b->clock[i] ? -1 : 1;
    return a->point.ordinal - b->point.ordinal;
}

/* A cursor binds the namespace, insertion order and complete original rows,
 * including their clocks. Later appends cannot change a pinned answer. */
static int collect_checks(const jov_pr *pr, const AM_List *rows, const AM_List *keys, const char *head,
                          const char *file, const history_window *window, const int from[3], const int to[3],
                          timed_check checks[256], int *count, char cursor[65]) {
    char scope[180];
    snprintf(scope, sizeof(scope), "%s/%s", pr->repository, pr->number);
    if (!keys || rows->len != keys->len || rows->len > 256 || hash_bytes(scope, strlen(scope), cursor)) return 1;
    int saw_first = window->from_journal && !strcmp(window->from_journal, cursor);
    for (int i = 0; i < rows->len && (!window->through || strcmp(window->through, cursor)); i++) {
        int in_first = !window->from_journal || !saw_first;
        const char *row = rows->items[i]->data, *id = keys->items[i]->data;
        const char *evidence = nj_get(row, "evidence");
        char digest[65], chain[129];
        if (json_digest(evidence, digest) || strcmp(digest, id)) return 1;
        memcpy(chain, cursor, 64);
        if (hash_bytes(row, strlen(row), chain + 64) || hash_bytes(chain, 128, cursor)) return 1;
        if (window->from_journal && !strcmp(cursor, window->from_journal)) saw_first = 1;
        if (!nj_is(nj_get(evidence, "head_commit"), head)) continue;
        timed_check check = {.point.ordinal = i, .id = id};
        int order;
        if (checked_time(row, check.clock) || clock_order(check.clock, to, &order)) return 1;
        if (order > 0) continue;
        if (clock_order(check.clock, from, &order)) return 1;
        check.known_before = in_first && order <= 0;
        int got = read_snapshot_point(&check.point, row, file);
        if (got < 0) return 1;
        if (got) checks[(*count)++] = check;
    }
    return (window->from_journal && !saw_first) || (window->through && strcmp(cursor, window->through));
}

static const char *verdict_at(const timed_check *checks, int count) {
    snapshot_point points[256];
    if (!count) return "unverified";
    for (int i = 0; i < count; i++) points[i] = checks[i].point;
    if (resolve_snapshots(points, count)) return NULL;
    const AM_List *states = am_get_var_list("states");
    if (!states || states->len != count) return NULL;
    for (int i = 0; i < count; i++) {
        const char *s = states->items[i]->data;
        if (!strcmp(s, "met")) return "met";
        if (!strcmp(s, "mismatch")) return "mismatch";
        if (!strcmp(s, "conflicting")) return "conflicting";
        if (strcmp(s, "skipped")) return NULL;
    }
    return "unverified";
}

static void write_verdict(FILE *out, const char *status, const timed_check *checks, int count) {
    fputc('{', out); json_field(out, "status", status);
    fputs(",\"receipt_ids\":[", out);
    for (int i = 0; i < count; i++) {
        if (i) fputc(',', out);
        json_string(out, checks[i].id);
    }
    fputs("]}", out);
}

static int compare_stream(FILE *out, const timed_check *checks, int count) {
    int first_new = 0;
    while (first_new < count && checks[first_new].known_before) first_new++;
    const char *before = verdict_at(checks, first_new);
    const char *after = first_new == count ? before : verdict_at(checks, count);
    if (!before || !after) return 1;
    const snapshot_point *p = &checks[0].point;
    fputc('{', out); json_field(out, "stream_id", p->stream);
    if (write_member(out, "fact", p->fact) || write_member(out, "routes_sha256", nj_get(p->coverage, "routes_sha256")) ||
        write_member(out, "harness_sha256", nj_get(p->coverage, "harness_sha256"))) return 1;
    fputs(",\"before\":", out); write_verdict(out, before, checks, first_new);
    fputs(",\"after\":", out); write_verdict(out, after, checks, count);
    fprintf(out, ",\"verdict_changed\":%s,\"new_checks\":[", strcmp(before, after) ? "true" : "false");
    for (int i = first_new; i < count; i++) {
        const snapshot_point *item = &checks[i].point;
        if (i > first_new) fputc(',', out);
        fputc('{', out); json_field(out, "id", checks[i].id);
        if (write_member(out, "checked_at", nj_get(item->entry, "checked_at")) ||
            write_member(out, "result", item->result)) return 1;
        fputc('}', out);
    }
    fputs("]}", out);
    return 0;
}

static int compare_snapshots(const jov_pr *pr, const AM_List *rows, const AM_List *keys, const char *repo,
                             const char *head, const char *file, const history_window *window) {
    timed_check checks[256];
    int from[3], to[3], order;
    char cursor[65], *data = NULL;
    int count = 0;
    if (!*file || cutoff_time(window->from, from) || cutoff_time(window->to, to) || clock_order(from, to, &order) || order > 0 ||
        commit_available(repo, head) != 1 ||
        collect_checks(pr, rows, keys, head, file, window, from, to, checks, &count, cursor)) return 1;
    qsort(checks, (size_t)count, sizeof(*checks), compare_checks);
    size_t size = 0;
    FILE *out = open_memstream(&data, &size);
    if (!out) return 1;
    fputs("{\"schema\":\"jovovich.snapshot-comparison/1\",", out);
    json_field(out, "repository", pr->repository); fprintf(out, ",\"number\":%s,", pr->number);
    json_field(out, "head_commit", head); fputc(',', out); json_field(out, "file", file);
    fputc(',', out); json_field(out, "from", window->from); fputc(',', out); json_field(out, "to", window->to);
    fputc(',', out); json_field(out, "from_journal", window->from_journal ? window->from_journal : cursor);
    fputc(',', out); json_field(out, "journal_head", cursor); fputs(",\"streams\":[", out);
    int bad = 0;
    for (int i = 0; i < count && !bad;) {
        int end = i + 1;
        while (end < count && !strcmp(checks[i].point.stream, checks[end].point.stream)) end++;
        if (i) fputc(',', out);
        bad = compare_stream(out, checks + i, end-i);
        i = end;
    }
    fputs("]}\n", out);
    if (fclose(out)) bad = 1;
    if (!bad) bad = fwrite(data, 1, size, stdout) != size || fflush(stdout);
    free(data);
    return bad;
}
#endif
