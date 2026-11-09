#ifndef JOV_SNAPSHOT_RECALL_H
#define JOV_SNAPSHOT_RECALL_H

#include "batch.h"

typedef struct {
    int number, expected_byte, observed_byte;
    char mismatch[65], recovery[65], landing[65], source_head[65];
    const char *landing_status, *source_status;
    long long line, column;
} snapshot_citation;

/* Git exit 1 means unrelated. A missing historical object (e.g. after a
 * squash in a fresh clone) cannot supply a citation on the reviewed base. */
static int ancestor_of(const char *repo, const char *old, const char *tip) {
    const char *args[] = {"merge-base", "--is-ancestor", old, tip, NULL};
    size_t size;
    int status;
    char *out = jov_git_command(repo, NULL, args, 0, &size, &status);
    if (!out) return -1;
    free(out);
    return status == 0 ? 1 : status == 1 ? 0 : -1;
}

static int commit_available(const char *repo, const char *head) {
    char name[80];
    snprintf(name, sizeof(name), "%.64s^{commit}", head);
    size_t size;
    int status;
    const char *args[] = {"rev-parse", "--verify", "--quiet", name, NULL};
    char *out = jov_git_command(repo, NULL, args, 65, &size, &status);
    if (!out) return -1;
    size_t width = strlen(head);
    int exact = size == width+1 && !memcmp(out, head, width) && out[width] == '\n';
    free(out);
    return status == 0 ? exact : status == 1 ? 0 : -1;
}

/* Follow first parents while they contain the historical mismatch. At the
 * merge which introduced it, follow its source branch. A pass on an incidental
 * second parent cannot close a mismatch already present on the first parent. */
static int rank_case(const char *repo, const char *base, const char *mismatch,
                     snapshot_point *points, int count) {
    char cursor[65];
    strcpy(cursor, base);
    long distance = 0;
    for (;;) {
        size_t size;
        int status;
        const char *args[] = {"rev-list", "--first-parent", "--parents", "--max-count=256", cursor, "--", NULL};
        char *page = jov_git_command(repo, NULL, args, 262144, &size, &status);
        if (!page || status || !size) { free(page); return 1; }
        /* All earlier merges on this page follow their first parent when the
         * mismatch is visible on the page or already present at its oldest SHA. */
        if (page[size-1] != '\n') { free(page); return 1; }
        page[size-1] = 0;
        const char *last = strrchr(page, '\n');
        last = last ? last+1 : page;
        char oldest[65], needle[67];
        size_t width = strlen(base);
        if (strcspn(last, " ") != width) { free(page); return 1; }
        memcpy(oldest, last, width); oldest[width] = 0;
        snprintf(needle, sizeof(needle), "\n%.64s", mismatch);
        int direct = !strcmp(cursor, mismatch) || strstr(page, needle) != NULL;
        int through_oldest = direct ? 0 : ancestor_of(repo, mismatch, oldest);
        if (through_oldest < 0) { free(page); return 1; }
        char *lines = NULL;
        for (char *row = strtok_r(page, "\n", &lines); row; row = strtok_r(NULL, "\n", &lines)) {
            char *parents = NULL;
            char *head = strtok_r(row, " ", &parents);
            if (!head || strcmp(head, cursor)) { free(page); return 1; }
            for (int i = 0; i < count; i++)
                if (!strcmp(points[i].head, head)) points[i].distance = distance;
            if (!strcmp(head, mismatch)) { free(page); return 0; }

            char *parent = strtok_r(NULL, " ", &parents);
            int switched = 0;
            if (parent && parents && *parents && !direct && !(through_oldest && strcmp(head, oldest))) {
                while (parent) {
                    int reachable = ancestor_of(repo, mismatch, parent);
                    if (reachable < 0) { free(page); return 1; }
                    if (reachable) break;
                    switched = 1;
                    parent = strtok_r(NULL, " ", &parents);
                }
            }
            if (!parent || strlen(parent) != strlen(base)) { free(page); return 1; }
            strcpy(cursor, parent);
            distance++;
            if (switched) break; /* The rest of the page follows another parent. */
        }
        free(page);
    }
}

/* A byte at the end of the captured line denotes EOF on that side. */
static int mismatch_byte(const char *result, const char *field, long long column, int *byte) {
    char *line = nj_string(nj_get(result, field));
    if (!line) return 1;
    size_t length = strlen(line);
    int invalid = (unsigned long long)(column-1) > length;
    if (!invalid) *byte = (size_t)(column-1) == length ? -1 : (unsigned char)line[column-1];
    free(line);
    return invalid;
}

static int cite_mismatch(snapshot_citation *citation, int number, const snapshot_point *p, const char *fix) {
    if (nj_int(nj_get(p->result, "line"), &citation->line) || citation->line < 1 ||
        nj_int(nj_get(p->result, "byte_column"), &citation->column) || citation->column < 1) return 1;
    if (mismatch_byte(p->result, "expected", citation->column, &citation->expected_byte) ||
        mismatch_byte(p->result, "observed", citation->column, &citation->observed_byte) ||
        citation->expected_byte == citation->observed_byte) return 1;
    if (*fix && (strlen(fix)!=strlen(p->head) || strspn(fix,"0123456789abcdef")!=strlen(p->head))) return 1;
    citation->number = number;
    strcpy(citation->mismatch, p->head);
    strcpy(citation->recovery, fix);
    return 0;
}

/* Reconstruct the source PR from the measured Git order saved at integration.
 * Use the current immutable observations for those SHAs, including corrections
 * learned after the merge. The landing is the last, independently measured point. */
static int recall_landing(snapshot_point *points, int count, const char *repo, const char *base,
                          int number, snapshot_citation *citation) {
    const char *proof=NULL;
    char commit[65]={0};
    for (int i=0;i<count;i++) {
        const char *landing=nj_get(nj_get(points[i].entry,"evidence"),"landing");
        if (!landing) continue;
        if (!nj_is(nj_get(landing,"schema"),"jovovich.pr-landing/1") ||
            !nj_is(nj_get(landing,"merge_commit"),points[i].head) || (*commit && strcmp(commit,points[i].head))) return 1;
        strcpy(commit,points[i].head);
        proof=landing; /* Later receipts can include previously unmeasured source revisions. */
    }
    if (!proof || strlen(commit)!=strlen(base)) return 0;
    int reachable=commit_available(repo,commit);
    if (reachable==1) reachable=ancestor_of(repo,commit,base);
    if (reachable<=0) return reachable<0;

    char *source=nj_string(nj_get(proof,"source_head"));
    if (!source || strlen(source)!=strlen(base) || strspn(source,"0123456789abcdef")!=strlen(base)) { free(source); return 1; }
    strcpy(citation->source_head,source); free(source);
    int bad=0, sources=0, final_seen=0;
    /* Negative ranks here mark absence. Give the newest source SHA distance 1
     * after reading the oldest-first list, leaving zero for the landed SHA. */
    for (const char *v=nj_first(nj_get(proof,"source_history"),&bad); v && !bad; v=nj_next(v,']',&bad)) {
        char *head=nj_string(v);
        if (!head || strlen(head)!=strlen(base) || strspn(head,"0123456789abcdef")!=strlen(base) || final_seen || ++sources>256) { free(head); return 1; }
        final_seen=!strcmp(citation->source_head,head);
        for (int i=0;i<count;i++) if (!strcmp(points[i].head,head)) points[i].distance=sources;
        free(head);
    }
    if (bad || !final_seen) return 1;
    int used=0;
    for (int i=0;i<count;i++) {
        snapshot_point p=points[i];
        if (!strcmp(p.head,commit)) p.distance=0;
        else if (p.distance>0) p.distance=sources+1-p.distance;
        else continue;
        points[used++]=p;
    }
    qsort(points,(size_t)used,sizeof(*points),oldest_first);
    if (!used || resolve_snapshots(points,used)) return 1;
    const AM_List *states=am_get_var_list("states"),*fixes=am_get_var_list("recoveries");
    if (!states || !fixes || states->len!=used || fixes->len!=used) return 1;
    int source_mismatch=-1, landed_mismatch=-1;
    citation->source_status="unverified"; citation->landing_status="unverified";
    for (int i=0;i<used;i++) {
        const snapshot_point *p=points+i;
        const char *state=states->items[used-1-i]->data;
        if (!p->outcome) continue;
        const char *status=!strcmp(state,"conflicting") ? "conflicting" : p->outcome==1 ? "met" : "mismatch";
        if (!p->distance) citation->landing_status=status;
        if (!strcmp(p->head,citation->source_head)) citation->source_status=status;
        if (!strcmp(status,"mismatch")) {
            if (!p->distance) landed_mismatch=i;
            else source_mismatch=i;
        }
    }
    int i=source_mismatch>=0 ? source_mismatch : landed_mismatch;
    if (i>=0) {
        if (cite_mismatch(citation,number,points+i,fixes->items[used-1-i]->data)) return 1;
        strcpy(citation->landing,commit);
    }
    return 0;
}

/* Resolve the old PR's checks using the same AML program as an explicit
 * history query. Keep the closest unambiguous mismatch on the selected route. */
static int recall_path(const AM_List *rows, const char *file, const char *stream, const char *repo,
                       const char *base, int number, snapshot_citation *citation) {
    snapshot_point source[256], route[256];
    int count = 0;
    for (int i = 0; i < rows->len; i++) {
        snapshot_point p = {.ordinal=count};
        int read = read_snapshot_point(&p, rows->items[i]->data, file);
        if (read < 0) return 1;
        if (read && !strcmp(p.stream, stream)) source[count++] = p;
    }
    memcpy(route,source,(size_t)count*sizeof(*route));
    if (recall_landing(route,count,repo,base,number,citation)) return 1;
    if (citation->number) return 0;
    int visited[256] = {0};
    long closest = LONG_MAX;
    for (int i = 0; i < count; i++) {
        if (source[i].outcome != 2 || visited[i] || strlen(source[i].head) != strlen(base)) continue;
        int reachable = commit_available(repo, source[i].head);
        if (reachable == 1) reachable = ancestor_of(repo, source[i].head, base);
        if (reachable < 0) return 1;
        if (!reachable) continue;
        memcpy(route, source, (size_t)count * sizeof(*route));
        if (rank_case(repo, base, source[i].head, route, count)) return 1;
        qsort(route, (size_t)count, sizeof(*route), oldest_first);
        int n = count;
        while (n && route[n-1].distance < 0) n--;
        if (!n || resolve_snapshots(route, n)) return 1;
        const AM_List *states = am_get_var_list("states"), *fixes = am_get_var_list("recoveries");
        if (!states || !fixes || states->len != n || fixes->len != n) return 1;
        for (int j = 0; j < n; j++) {
            const snapshot_point *p = &route[j];
            if (p->outcome != 2) continue;
            visited[p->ordinal] = 1;
            if (strcmp(states->items[n-1-j]->data, "mismatch") || p->distance > closest ||
                (p->distance == closest && strcmp(p->head, citation->mismatch) >= 0)) continue;
            if (cite_mismatch(citation, number, p, fixes->items[n-1-j]->data)) return 1;
            closest = p->distance;
        }
    }
    return 0;
}

static int newest_number(const void *a, const void *b) {
    return *(const int *)b - *(const int *)a;
}

static void write_byte(FILE *out, int byte, int json) {
    if (byte < 0) fputs(json ? "null" : "EOF", out);
    else if (json) fprintf(out, "%d", byte);
    else if (byte < 128 && isalnum(byte)) fprintf(out, "`%c` (0x%02X)", byte, (unsigned)byte);
    else fprintf(out, "0x%02X", (unsigned)byte);
}

static void write_citations(FILE *out, int json, const char *repository, const char *const files[],
                            const snapshot_citation cases[], int count) {
    int written = 0;
    if (json) fputs(",\"prior_snapshot_cases\":[", out);
    for (int i = 0; i < count; i++) {
        const snapshot_citation *c = cases+i;
        if (!c->number) continue;
        if (json) {
            if (written) fputc(',', out);
            fputc('{', out); json_field(out, "repository", repository);
            fprintf(out, ",\"number\":%d,", c->number); json_field(out, "file", files[i]);
            fprintf(out, ",\"line\":%lld,\"byte_column\":%lld,", c->line, c->column);
            fputs("\"expected_byte\":", out); write_byte(out, c->expected_byte, 1);
            fputs(",\"observed_byte\":", out); write_byte(out, c->observed_byte, 1);
            fputc(',', out); json_field(out, "mismatch_commit", c->mismatch);
            fputs(",\"first_checked_match\":", out);
            if (*c->recovery) json_string(out, c->recovery); else fputs("null", out);
            if (*c->landing) {
                fputs(",\"landing\":{",out); json_field(out,"source_head",c->source_head);
                fputc(',',out); json_field(out,"source_status",c->source_status);
                fputc(',',out); json_field(out,"commit",c->landing);
                fputc(',',out); json_field(out,"status",c->landing_status); fputc('}',out);
            }
            fputc('}', out);
        } else {
            if (!written) fputs("\n### Earlier snapshot checks\n\n", out);
            fprintf(out, "- [#%d](https://github.com/%s/pull/%d) · ", c->number, repository, c->number);
            jov_markdown_text(out, files[i], 0);
            fprintf(out, " · line %lld, byte %lld · mismatch [`%.12s`](https://github.com/%s/commit/%s)",
                    c->line, c->column, c->mismatch, repository, c->mismatch);
            fputs(" · expected ", out); write_byte(out, c->expected_byte, 0);
            fputs(", regenerated ", out); write_byte(out, c->observed_byte, 0);
            if (*c->recovery) fprintf(out, " · first checked match [`%.12s`](https://github.com/%s/commit/%s)",
                                      c->recovery, repository, c->recovery);
            else fputs(" · no later match verified in that PR through this base", out);
            if (*c->landing) fprintf(out," · source [`%.12s`](https://github.com/%s/commit/%s) %s"
                " · landed [`%.12s`](https://github.com/%s/commit/%s) %s",
                c->source_head,repository,c->source_head,c->source_status,c->landing,repository,c->landing,c->landing_status);
            fputc('\n', out);
        }
        written++;
    }
    if (json) fputc(']', out);
}

int jov_pr_recall_snapshots(FILE *out, int json, const char *directory, const jov_pr *current,
                            const jov_fact *fact, const char *repo, const char *base, const char *coverage,
                            const char *const files[], int count) {
    snapshot_citation cases[JOV_BATCH_MAX_FILES] = {0};
    int *numbers = NULL, remaining = count, failed = 1, writer = -1;
    size_t total = 0, length = 0;
    char *encoded = NULL, stream[65];
    if (count < 0 || count > JOV_BATCH_MAX_FILES) return 1;
    if (count) {
        FILE *receipt = open_memstream(&encoded, &length);
        if (!receipt) return 1;
        jov_fact_json(receipt, fact);
        if (fclose(receipt) || snapshot_stream(encoded, coverage, stream) ||
            checkpoint_numbers(directory, current->repository, &numbers, &total)) goto done;
        if (total > 1) qsort(numbers, total, sizeof(*numbers), newest_number);
    }
    for (size_t j = 0; j < total && remaining; j++) {
        if (numbers[j] >= atoi(current->number)) continue;
        jov_pr prior = *current;
        snprintf(prior.number, sizeof(prior.number), "%d", numbers[j]);
        prior.opened_at[0] = 0;
        if (journal(directory, &prior, 0, &writer)) goto done;
        const char *opened = am_get_var_text("opened");
        if (!opened || strlen(opened) != 20) goto done;
        if (strcmp(opened, current->opened_at) > 0) continue;
        AM_List *rows = am_list_clone(am_get_var_list("observations"));
        if (!rows) goto done;
        int error = rows->len > 256;
        for (int i = 0; i < count && !error; i++) {
            if (cases[i].number) continue;
            error = recall_path(rows, files[i], stream, repo, base, numbers[j], cases+i);
            if (cases[i].number) remaining--;
        }
        am_list_free(rows);
        if (error) goto done;
    }
    write_citations(out, json, current->repository, files, cases, count);
    failed = ferror(out);
done:
    free(encoded); free(numbers);
    return failed;
}
#endif
