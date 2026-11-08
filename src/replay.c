#define _XOPEN_SOURCE 700
#include "ariannamethod.h"
#include "batch.h"
#include "facts.h"
#include "hash.h"
#include "json.h"
#include "process.h"
#include "report_json.h"
#include <limits.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>

#define ROW_LIMIT 1048576u
typedef struct {
    char *id, *file, *context, *rule, *change;
    char *base, *head, *path, *blob, *rule_sha, *diff_sha;
    int first, last;
    jov_fact *fact;
} packed_row;

static void release(packed_row *p) {
    free(p->id); free(p->file); free(p->context); free(p->rule); free(p->change);
    free(p->base); free(p->head); free(p->path); free(p->blob); free(p->rule_sha); free(p->diff_sha);
    jov_fact_free(p->fact);
}

static int parse(const char *row, packed_row *p) {
    const char *end = report_json_end(row, 0);
    if (!end || *nj_ws(end)) return 1;
    const char *s = nj_get(row, "source");
    long long first, last;
    if (!nj_is(nj_get(s, "kind"), "git") || nj_int(nj_get(s, "rule_first_line"), &first) ||
        nj_int(nj_get(s, "rule_last_line"), &last) || first < 1 || last < first || last > INT_MAX) return 1;
    p->first = (int)first; p->last = (int)last;
    p->id = nj_string(nj_get(row, "id")); p->file = nj_string(nj_get(row, "file"));
    p->context = nj_string(nj_get(row, "context")); p->rule = nj_string(nj_get(row, "rule_excerpt"));
    p->change = nj_string(nj_get(row, "change_excerpt"));
    p->base = nj_string(nj_get(s, "base_commit")); p->head = nj_string(nj_get(s, "head_commit"));
    p->path = nj_string(nj_get(s, "rules_path")); p->blob = nj_string(nj_get(s, "rules_blob"));
    p->rule_sha = nj_string(nj_get(s, "rules_sha256")); p->diff_sha = nj_string(nj_get(s, "diff_sha256"));
    if (jov_fact_decode(nj_get(row, "fact"), &p->fact)) return 1;
    jov_source source = {p->base,p->head,p->path,p->blob,p->rule_sha,p->diff_sha,p->first,p->last};
    jov_review r = {.id=p->id,.model="input",.revision="input",.question="input",.file=p->file,
        .context=p->context,.rule_excerpt=p->rule,.change_excerpt=p->change,.source=&source,.fact=p->fact,.concern=.5,.clean=.5};
    char digest[65];
    return jov_review_validate(&r) || hash_bytes(p->context, strlen(p->context), digest) || strcmp(digest,p->id) ||
        hash_bytes(p->rule, strlen(p->rule), digest) || strcmp(digest,p->rule_sha) ||
        hash_bytes(p->change, strlen(p->change), digest) || strcmp(digest,p->diff_sha);
}

static char *command(const char *const argv[], size_t limit) {
    size_t bytes; int code;
    char *p = jov_command(argv, limit, &bytes, &code);
    if (p && (code || memchr(p, 0, bytes))) { free(p); p = NULL; }
    return p;
}

/* Return 1 for a merged ancestor, 0 for an off-branch or unavailable origin
 * head, and -1 for a broken repository/command. The current pair is Git-verified. */
static int landed(const char *repo, const char *old_head, const char *base) {
    size_t n; int code;
    char spec[80];
    snprintf(spec,sizeof(spec),"%s^{commit}",old_head);
    char *s = jov_command((const char *[]){"git","--no-replace-objects","-C",repo,"rev-parse","--verify",
                          "--quiet",spec,NULL}, 128, &n, &code);
    if (!s) return -1;
    free(s);
    if (code) return code == 1 ? 0 : -1;
    s = jov_command((const char *[]){"git","--no-replace-objects","-C",repo,"merge-base","--is-ancestor",
                    old_head,base,NULL}, 128, &n, &code);
    if (!s) return -1;
    free(s);
    return code == 0 ? 1 : code == 1 ? 0 : -1;
}

static int verify_git(const char *repo, const packed_row *p) {
    char first[16], last[16];
    snprintf(first,sizeof(first),"%d",p->first); snprintf(last,sizeof(last),"%d",p->last);
    char *actual = command((const char *[]){"build/jovovich-pack",repo,p->base,p->head,p->path,p->file,first,last,NULL},ROW_LIMIT);
    if (!actual) return 1;
    const char *src = nj_get(actual,"source");
    int ok = nj_is(nj_get(actual,"id"),p->id) && nj_is(nj_get(src,"base_commit"),p->base) &&
        nj_is(nj_get(src,"head_commit"),p->head) && nj_is(nj_get(src,"rules_blob"),p->blob) &&
        nj_is(nj_get(src,"rules_sha256"),p->rule_sha) && nj_is(nj_get(src,"diff_sha256"),p->diff_sha);
    free(actual);
    return !ok || (p->fact && landed(repo,p->fact->base,p->base) != 1);
}

static int file_digest(const char *path, char digest[65]) {
    int fd = open(path,O_RDONLY);
    if (fd < 0) return 1;
    int failed = 1;
    struct stat st;
    if (!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size > 0 && (uintmax_t)st.st_size <= SIZE_MAX) {
        void *data = mmap(NULL,(size_t)st.st_size,PROT_READ,MAP_PRIVATE,fd,0);
        if (data != MAP_FAILED) {
            failed = hash_bytes(data,(size_t)st.st_size,digest);
            munmap(data,(size_t)st.st_size);
        }
    }
    close(fd);
    return failed;
}

static int witness(const char *row, const packed_row *p, jov_trace_receipt *r) {
    return am_set_var_text("review_context",p->context) || jov_apply_trace_gate(row,p->id,p->rule,p->change,r);
}

static int open_cases(const char *dir, int writing, int *writer) {
    if (jov_journal_open(dir,"cases",writing,writer) || am_exec_file("aml/open-counterexamples.aml")) {
        fprintf(stderr,"Could not open counterexample memory: %s\n",am_get_error());
        return 1;
    }
    return 0;
}

static int journal(const packed_row *p, const char *harness_sha, const char *row) {
    if (am_set_var_text("repository_name",p->fact->repository) || am_set_var_text("fact_key",p->fact->key) ||
        am_set_var_text("case_file",p->file) || am_set_var_text("harness_sha",harness_sha) ||
        am_set_var_text("capture_row",row) || am_exec_file("aml/counterexamples.aml")) {
        fprintf(stderr,"AML counterexample memory: %s\n",am_get_error());
        return 1;
    }
    return 0;
}

static int origin_ref(const char *row, const packed_row *p, const char *sha, jov_replay_ref *r) {
    jov_trace_receipt t = {0};
    const char *g = nj_get(row,"trace_evidence");
    const char *stamped = nj_get(g,"harness_sha256");
    if (!g || (stamped && !nj_is(stamped,sha)) || witness(row,p,&t) || !t.differing ||
        hash_bytes(row,strlen(row),r->source_sha)) return 1;
    strcpy(r->base,p->base); strcpy(r->head,p->head); strcpy(r->harness_sha,sha);
    r->mode = t.selected_mode;
    return 0;
}

/* Retain each original row while validating it against the new Git base. */
static int recall(const char *repo, const packed_row *p, const char *sha, jov_replay_ref *r) {
    if (journal(p,sha,"")) return 1;
    const AM_List *matches = am_get_var_list("matches");
    if (!matches) return 1;
    AM_String *chosen = NULL;
    int failed = 0;
    for (int i=matches->len-1; i>=0; i--) {
        AM_String *saved = am_list_get(matches,i);
        packed_row old = {0};
        failed = !saved || parse(saved->data,&old) || !old.fact || strcmp(old.file,p->file) ||
            strcmp(old.fact->repository,p->fact->repository) || strcmp(old.fact->key,p->fact->key);
        int merged = 0;
        if (!failed && (strcmp(old.base,p->base) || strcmp(old.head,p->head))) {
            int compatible = landed(repo,old.base,p->base);
            if (compatible == 1) {
                merged = landed(repo,old.head,p->base);
                if (merged == 1 || (!chosen && merged == 0)) {
                    am_string_free(chosen);
                    chosen = saved; saved = NULL;
                }
            }
            failed = compatible < 0 || merged < 0;
        }
        release(&old); am_string_free(saved);
        if (failed || merged) break;
    }
    if (!failed && chosen) {
        packed_row old = {0};
        failed = parse(chosen->data,&old) || origin_ref(chosen->data,&old,sha,r);
        release(&old);
    }
    am_string_free(chosen);
    return failed;
}

/* A pretty-printed runner reply must still fit one packed JSONL row. */
static char *runner_json(const char *const argv[], const char *kinds) {
    char *s = command(argv,16384);
    if (!s) return NULL;
    const char *v = nj_ws(s), *end = report_json_end(v,0);
    if (!end || *nj_ws(end) || !strchr(kinds,*v)) { free(s); return NULL; }
    char *out = s;
    while (v < end) {
        if (*v == '"') {
            const char *next = nj_str_end(v);
            size_t n = (size_t)(next-v); memmove(out,v,n); out+=n; v=next;
        } else if (strchr(" \t\r\n",*v)) v++;
        else *out++ = *v++;
    }
    *out=0;
    return s;
}

static int raw_value(FILE *out, const char *p) {
    const char *end = p ? report_json_end(p,0) : NULL;
    return !end || fwrite(p,1,(size_t)(end-p),out) != (size_t)(end-p);
}

typedef struct { char *base, *head, *oracle; } sample;

static void free_sample(sample *x) { free(x->base); free(x->head); free(x->oracle); }

static int run_sample(const char *repo, const char *runner, const char *sha, const packed_row *p,
                      int mode, sample *x) {
    char arg[16], first[16], last[16];
    snprintf(arg,sizeof(arg),"%d",mode);
    snprintf(first,sizeof(first),"%d",p->first); snprintf(last,sizeof(last),"%d",p->last);
    x->base = runner_json((const char *[]){runner,"observe",repo,p->base,p->file,arg,NULL},"[\"");
    x->head = x->base ? runner_json((const char *[]){runner,"observe",repo,p->head,p->file,arg,NULL},"[\"") : NULL;
    x->oracle = x->head ? runner_json((const char *[]){runner,"expect",repo,p->base,p->file,arg,
                                      p->path,first,last,NULL},"{") : NULL;
    char check[65];
    return !x->oracle || file_digest(runner,check) || strcmp(check,sha);
}

static int remember(FILE *out, const char *dir, const char *repo, const char *runner, const char *row, const packed_row *p, const char *sha) {
    jov_replay_ref ref = {0};
    if (!p->fact || strlen(row) > 65536 || origin_ref(row,p,sha,&ref)) {
        fputs("Capture needs a named Git rule and a differing run from this harness.\n",stderr);
        return 1;
    }
    sample x = {0};
    int matches = !run_sample(repo,runner,sha,p,ref.mode,&x) &&
        jov_trace_reproduced(nj_get(row,"trace_evidence"),ref.mode,x.base,x.head,x.oracle);
    free_sample(&x);
    if (!matches) { fputs("The original execution or requirement did not reproduce.\n",stderr); return 1; }
    int writer = -1;
    int failed = open_cases(dir,1,&writer) || journal(p,sha,row) || jov_memory_commit();
    if (writer >= 0) close(writer);
    if (failed) return 1;
    jov_replay_ref_json(out,&ref);
    return fputc('\n',out)==EOF;
}

static int measure(FILE *out, const char *repo, const char *runner, const char *sha,
                   const char *row, const packed_row *p, int mode, const jov_replay_ref *ref) {
    sample x = {0};
    char *line = NULL; size_t size = 0; int failed = 1;
    if (run_sample(repo,runner,sha,p,mode,&x)) goto done;
    FILE *f = open_memstream(&line,&size);
    if (!f) goto done;
    const char *end=report_json_end(row,0);
    fwrite(row,1,(size_t)(end-row-1),f);
    fputs(",\"trace_evidence\":{\"schema\":\"jovovich.paired-traces/1\",",f);
    json_field(f,"review_id",p->id); fputc(',',f); json_field(f,"rule_sha256",p->rule_sha); fputc(',',f);
    json_field(f,"change_sha256",p->diff_sha); fputc(',',f); json_field(f,"base_commit",p->base); fputc(',',f);
    json_field(f,"head_commit",p->head); fputc(',',f); json_field(f,"harness_sha256",sha);
    if (ref) { fputs(",\"replayed_from\":",f); jov_replay_ref_json(f,ref); }
    fputs(",\"metric\":",f);
    int bad = raw_value(f,nj_get(x.oracle,"metric"));
    if (nj_get(x.oracle,"target")) { fputs(",\"target\":",f); bad |= raw_value(f,nj_get(x.oracle,"target")); }
    fprintf(f,",\"runs\":[{\"mode\":%d,\"base\":%s,\"head\":%s,\"required\":",mode,x.base,x.head);
    bad |= raw_value(f,nj_get(x.oracle,"required"));
    fputs("}]}}\n",f);
    if (fclose(f) || bad || size > ROW_LIMIT) goto done;
    jov_trace_receipt t = {0};
    if (!witness(line,p,&t) && fwrite(line,1,size,out)==size) failed = 0;
done:
    free_sample(&x); free(line);
    return failed;
}

static int show(const char *dir, const char *digest) {
    if (strlen(digest) != 64 || strspn(digest,"0123456789abcdef") != 64) return 2;
    int writer = -1, failed = 1;
    am_init(); am_persistent_mode(1);
    if (!open_cases(dir,0,&writer) && !am_set_var_text("requested_sha",digest) &&
        !am_exec_file("aml/read-counterexample.aml")) {
        const char *original = am_get_var_text("original");
        if (original) failed = fputs(original,stdout)==EOF || fflush(stdout);
    }
    if (failed) fprintf(stderr,"Could not restore input %s: %s\n",digest,am_get_error());
    am_persistent_mode(0);
    return failed;
}

static int parse_mode(const char *s, int *mode) {
    char *end; errno=0;
    long long n=strtoll(s,&end,10);
    if (errno || end==s || *end || n<INT_MIN || n>INT_MAX) return 1;
    *mode=(int)n;
    return 0;
}

int main(int argc, char **argv) {
    if (argc==4 && !strcmp(argv[1],"show")) return show(argv[2],argv[3]);
    int probe=argc==5 && !strcmp(argv[1],"probe");
    int capture=argc==5 && !strcmp(argv[1],"remember");
    int replay=argc==5 && !strcmp(argv[1],"run");
    int mode=0;
    if ((!probe && !capture && !replay) || (probe && parse_mode(argv[4],&mode))) {
        fputs("Usage: jovovich-replay probe REPO HARNESS MODE | remember DIR REPO HARNESS | run DIR REPO HARNESS < packed.jsonl\n       jovovich-replay show DIR INPUT_SHA256\n",stderr);
        return 2;
    }
    const char *dir = probe?NULL:argv[2];
    char *repo = realpath(argv[probe?2:3],NULL);
    char *runner = realpath(argv[probe?3:4],NULL);
    char sha[65], *line=NULL; size_t bytes=0; int bad_input=0, writer=-1;
    int count=0, failed=1;
    FILE *out=tmpfile();
    if (!repo || !runner || access(runner,X_OK) || file_digest(runner,sha) || !out) goto done;
    am_init(); am_persistent_mode(1);
    if (replay && open_cases(dir,0,&writer)) goto done;
    while ((line=report_json_row(stdin,&bytes,&bad_input,ROW_LIMIT,JOV_BATCH_MAX_BYTES))) {
        if (++count>JOV_BATCH_MAX_FILES) goto done;
        size_t length=strlen(line);
        if ((capture || probe) && (fgetc(stdin)!=EOF || ferror(stdin))) goto done;
        packed_row p={0}; jov_replay_ref ref={0};
        int bad=parse(line,&p);
        if (!bad && !capture && nj_get(line,"trace_evidence")) {
            fputs("Supply a fresh Git pack before attaching executions.\n",stderr); bad=1;
        }
        if (!bad && (capture || probe || p.fact)) bad=verify_git(repo,&p);
        if (!bad && capture) bad=remember(out,dir,repo,runner,line,&p,sha);
        if (!bad && replay && p.fact) bad=recall(repo,&p,sha,&ref);
        if (!bad && (probe || ref.source_sha[0]))
            bad=measure(out,repo,runner,sha,line,&p,probe?mode:ref.mode,probe?NULL:&ref);
        else if (!bad && replay) bad=fwrite(line,1,(size_t)length,out)!=(size_t)length;
        release(&p); free(line); line=NULL;
        if (bad) goto done;
        long staged=ftell(out);
        if (staged<0 || (unsigned long)staged>JOV_BATCH_MAX_BYTES) goto done;
    }
    if (!count || bad_input || ferror(stdin) || fseek(out,0,SEEK_SET)) goto done;
    char block[8192]; size_t n;
    while ((n=fread(block,1,sizeof(block),out))) if (fwrite(block,1,n,stdout)!=n) goto done;
    failed=ferror(out) || fflush(stdout);
done:
    if (failed) fprintf(stderr,"Counterexample %s failed at row %d.\n",argv[1],count);
    if (out && fclose(out)) failed=1;
    free(repo); free(runner); free(line); am_persistent_mode(0);
    return failed?1:0;
}
