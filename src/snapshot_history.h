#ifndef JOV_SNAPSHOT_HISTORY_H
#define JOV_SNAPSHOT_HISTORY_H
#include "git_command.h"

/* All borrowed JSON values below refer to an immutable AML checkpoint row. */
typedef struct {
    const char *entry, *result, *coverage, *fact;
    char head[65], stream[65];
    long distance;
    int ordinal, outcome;
} snapshot_point;

static int same_file(const char *item, const char *file) {
    char *path = nj_string(nj_get(item, "file"));
    int same = path && !strcmp(path, file);
    free(path);
    return same;
}

static int json_digest(const char *value, char digest[65]) {
    const char *end = value ? report_json_end(value, 0) : NULL;
    return !end || hash_bytes(value, (size_t)(end - value), digest);
}

static int snapshot_stream(const char *fact, const char *coverage, char stream[65]) {
    char *policy = nj_string(nj_get(coverage, "routes_sha256"));
    char *driver = nj_string(nj_get(coverage, "harness_sha256"));
    char parts[3*64];
    int failed = !policy || strlen(policy)!=64 || strspn(policy,"0123456789abcdef")!=64 ||
        !driver || strlen(driver)!=64 || strspn(driver,"0123456789abcdef")!=64 || json_digest(fact,parts);
    if (!failed) {
        memcpy(parts+64,policy,64); memcpy(parts+128,driver,64);
        failed = hash_bytes(parts,sizeof(parts),stream);
    }
    free(policy); free(driver);
    return failed;
}

/* Return one observation of this path, or zero for a legacy execution record
 * or a PR update which did not touch it. */
static int read_snapshot_point(snapshot_point *p, const char *entry, const char *file) {
    const char *e = nj_get(entry, "evidence");
    p->coverage = nj_get(e, "snapshot_coverage");
    if (!p->coverage) return 0;
    if (!nj_is(nj_get(p->coverage, "schema"), "jovovich.snapshot-coverage/1")) return -1;
    int bad = 0;
    const char *findings = nj_get(e, "findings");
    for (const char *f = nj_first(findings, &bad); f && !bad; f = nj_next(f, ']', &bad)) {
        if (!nj_is(nj_get(f, "kind"), "snapshot") || !same_file(f, file)) continue;
        p->result = f;
        if (nj_is(nj_get(f,"status"),"met")) p->outcome = 1;
        else if (nj_is(nj_get(f,"status"),"mismatch")) p->outcome = 2;
        else return -1;
        break;
    }
    if (bad) return -1;
    if (!p->result) {
        const char *skips = nj_get(p->coverage,"skipped");
        for (const char *s = nj_first(skips,&bad); s && !bad; s = nj_next(s,']',&bad))
            if (same_file(s,file)) { p->result = s; break; }
    }
    if (bad || !p->result) return bad ? -1 : 0;
    p->entry = entry;
    p->fact = nj_get(e,"fact");
    char *head = nj_string(nj_get(e,"head_commit"));
    if (!head || (strlen(head)!=40 && strlen(head)!=64) || strspn(head,"0123456789abcdef")!=strlen(head) ||
        snapshot_stream(p->fact,p->coverage,p->stream)) bad=1;
    else strcpy(p->head,head);
    free(head);
    p->distance = -1;
    return bad ? -1 : 1;
}

/* Read bounded pages of the actual first-parent chain. Journal insertion
 * order and commit timestamps can both differ from Git ancestry. */
static int rank_history(const char *repo, const char *tip, snapshot_point *points, int count) {
    enum { PAGE = 1024 };
    size_t width = strlen(tip) + 1;
    char cursor[65];
    strcpy(cursor, tip);
    long offset = 0;
    int remaining = count;
    for (;;) {
        const char *args[] = {"rev-list","--first-parent","--max-count=1025",cursor,"--",NULL};
        int code;
        size_t n;
        char *page = jov_git_command(repo,NULL,args,(PAGE+1)*width,&n,&code);
        if (!page || code || n<width || n%width || strncmp(page,cursor,width-1) || page[width-1]!='\n') {
            free(page); return 1;
        }
        size_t lines = n/width;
        for (int i=0;i<count;i++) {
            if (points[i].distance>=0 || strlen(points[i].head)!=width-1) continue;
            const char *pos = strstr(page,points[i].head);
            if (!pos) continue;
            size_t rank = (size_t)(pos-page)/width;
            if (rank==PAGE) continue;
            points[i].distance=offset+(long)rank;
            remaining--;
        }
        if (!remaining || lines<=PAGE) { free(page); return 0; }
        memcpy(cursor,page+PAGE*width,width-1);
        free(page);
        offset+=PAGE;
    }
}

static int oldest_first(const void *left,const void *right) {
    const snapshot_point *a=left,*b=right;
    if (a->distance!=b->distance) return a->distance>b->distance ? -1 : 1;
    return a->ordinal-b->ordinal;
}

static int push_text(AM_List *list,const char *text) {
    AM_String *s=am_string_new(text);
    int bad=!s || am_list_push(list,s)<0;
    am_string_free(s);
    return bad;
}

static int resolve_snapshots(snapshot_point *points,int n) {
    AM_List *heads=am_list_new(),*streams=am_list_new(),*outputs=am_list_new();
    float outcomes[256];
    int failed=1;
    if (!heads || !streams || !outputs || n<1 || n>256) goto done;
    for (int i=0;i<n;i++) {
        if (push_text(heads,points[i].head) || push_text(streams,points[i].stream)) goto done;
        char *sha = points[i].outcome ? nj_string(nj_get(points[i].result,"observed_sha256")) : NULL;
        int bad = (points[i].outcome && (!sha || strlen(sha)!=64 || strspn(sha,"0123456789abcdef")!=64)) ||
            push_text(outputs,sha ? sha : "");
        free(sha);
        if (bad) goto done;
        outcomes[i]=(float)points[i].outcome;
    }
    failed=am_set_var_list("history_heads",heads) || am_set_var_list("history_streams",streams) ||
        am_set_var_list("history_outputs",outputs) || am_set_var_array("history_outcomes",outcomes,n) ||
        am_exec_file("aml/snapshot-history.aml");
done:
    am_list_free(heads); am_list_free(streams); am_list_free(outputs);
    return failed;
}

static int write_member(FILE *out,const char *key,const char *value) {
    const char *end=value ? report_json_end(value,0) : NULL;
    if (!end) return 1;
    fprintf(out,",\"%s\":",key);
    return fwrite(value,1,(size_t)(end-value),out)!=(size_t)(end-value);
}

static int snapshot_history(const jov_pr *pr,const AM_List *rows,const char *repo,const char *tip,const char *file) {
    snapshot_point points[256]={0};
    int count=0;
    if (!*file || rows->len>256) return 1;
    for (int i=0;i<rows->len;i++) {
        snapshot_point point={.ordinal=i};
        int result=read_snapshot_point(&point,rows->items[i]->data,file);
        if (result<0) return 1;
        if (result) points[count++]=point;
    }
    if (rank_history(repo,tip,points,count)) return 1;
    qsort(points,(size_t)count,sizeof(*points),oldest_first);
    while (count && points[count-1].distance<0) count--;
    if (count && resolve_snapshots(points,count)) return 1;
    const AM_List *states=am_get_var_list("states"),*fixes=am_get_var_list("recoveries");
    if (count && (!states || !fixes || states->len!=count || fixes->len!=count)) return 1;
    fputs("{\"schema\":\"jovovich.snapshot-history/1\",",stdout);
    json_field(stdout,"repository",pr->repository); fprintf(stdout,",\"number\":%s,",pr->number);
    json_field(stdout,"file",file); fputc(',',stdout); json_field(stdout,"through_head",tip);
    fputs(",\"checks\":[",stdout);
    int tip_status=0;
    for (int i=0;i<count;i++) {
        const snapshot_point *p=points+i;
        const char *state=states->items[count-1-i]->data,*fix=fixes->items[count-1-i]->data;
        if (!p->distance) tip_status |= !strcmp(state,"conflicting") ? 3 : p->outcome;
        if (i) fputc(',',stdout);
        fputc('{',stdout); json_field(stdout,"head_commit",p->head); fputc(',',stdout); json_field(stdout,"status",state);
        if (write_member(stdout,"checked_at",nj_get(p->entry,"checked_at")) ||
            write_member(stdout,"rule_sequence",nj_get(p->fact,"sequence")) ||
            write_member(stdout,"routes_sha256",nj_get(p->coverage,"routes_sha256")) ||
            write_member(stdout,"harness_sha256",nj_get(p->coverage,"harness_sha256")) ||
            write_member(stdout,"result",p->result)) return 1;
        if (p->outcome==2) {
            fputs(",\"first_checked_match\":",stdout);
            if (*fix) json_string(stdout,fix); else fputs("null",stdout);
        }
        fputc('}',stdout);
    }
    const char *status[]={"unverified","met","mismatch","mixed"};
    fprintf(stdout,"],\"status_at_head\":\"%s\"}\n",status[tip_status]);
    return ferror(stdout) || fflush(stdout);
}
#endif
