#define _GNU_SOURCE
#define _XOPEN_SOURCE 700
#include "git_context.h"
#include "batch.h"
#include "facts.h"
#include "hash.h"
#include "json.h"
#include "hunk_trial.h"
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
    /* Parsing also runs while recall holds a borrowed AML list. Keep it free of AML execution. */
    return jov_review_validate(&r) || hash_bytes(p->context,strlen(p->context),digest) || strcmp(digest,p->id) ||
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
    char *s = jov_git_command(repo,NULL,(const char *[]){"rev-parse","--verify",
                          "--quiet",spec,NULL}, 128, &n, &code);
    if (!s) return -1;
    free(s);
    if (code) return code == 1 ? 0 : -1;
    s = jov_git_command(repo,NULL,(const char *[]){"merge-base","--is-ancestor",
                    old_head,base,NULL}, 128, &n, &code);
    if (!s) return -1;
    free(s);
    return code == 0 ? 1 : code == 1 ? 0 : -1;
}

/* A rule can survive a rebase of its original head. Its recorded base is
 * required to remain in ancestry and still contains the quoted bytes. */
static int verify_origin_rule(const char *repo, const jov_fact *f) {
    char *oid=jov_git_rule_blob(repo,f->base,f->path);
    if (!oid) return 1;
    size_t size=0;
    int code=0;
    char *blob=jov_git_command(repo,NULL,(const char *[]){"cat-file","blob",oid,NULL},
                               262144,&size,&code);
    free(oid);
    int bad=1;
    if (blob && !code && !memchr(blob,0,size)) {
        size_t pos=0, first=0;
        for (int line=1;pos<size;line++) {
            if (line==f->first) first=pos;
            const char *nl=memchr(blob+pos,'\n',size-pos);
            pos=nl?(size_t)(nl-blob)+1:size;
            if (line==f->last) {
                bad=pos-first!=strlen(f->quote) || memcmp(blob+first,f->quote,pos-first);
                break;
            }
        }
    }
    free(blob); return bad;
}

static jov_batch_item batch_item(const packed_row *p) {
    return (jov_batch_item){p->file,p->id,{p->base,p->head,p->path,p->blob,
                                           p->rule_sha,p->diff_sha,p->first,p->last}};
}

static int matches_git_row(const char *row, const packed_row *expected) {
    const char *src=nj_get(row,"source");
    char *file=nj_string(nj_get(row,"file")), *context=nj_string(nj_get(row,"context"));
    int matches=file && !strcmp(file,expected->file) && context && !strcmp(context,expected->context) &&
        nj_is(nj_get(row,"id"),expected->id) && nj_is(nj_get(src,"base_commit"),expected->base) &&
        nj_is(nj_get(src,"head_commit"),expected->head) && nj_is(nj_get(src,"rules_blob"),expected->blob) &&
        nj_is(nj_get(src,"rules_sha256"),expected->rule_sha) && nj_is(nj_get(src,"diff_sha256"),expected->diff_sha);
    free(file); free(context);
    return matches;
}

/* A single member can be captured on its own. Recover the ordered siblings
 * from Git and bind the digest to the rule receipt supplied with the member. */
static int verify_member(char *lines, const char *batch, const packed_row *member) {
    long long index,count;
    if (!nj_is(nj_get(batch,"schema"),"jovovich.git-batch/1") ||
        !nj_is(nj_get(batch,"scope"),"all_changed_paths") ||
        nj_int(nj_get(batch,"count"),&count) || count<1 || count>JOV_BATCH_MAX_FILES ||
        nj_int(nj_get(batch,"index"),&index) || index<0 || index>=count) return 1;

    packed_row siblings[JOV_BATCH_MAX_FILES]={0};
    jov_batch_item items[JOV_BATCH_MAX_FILES];
    char digest[65];
    int n=0, bad=1;
    for (;n<count;n++) {
        char *end=strchr(lines,'\n');
        if (!end) goto done;
        *end=0;
        if (parse(lines,&siblings[n]) || (n==index && !matches_git_row(lines,member))) goto done;
        items[n]=batch_item(&siblings[n]);
        lines=end+1;
    }
    bad=*lines || jov_batch_digest_fact(items,n,member->fact,digest) || !nj_is(nj_get(batch,"id"),digest);
done:
    for (int i=0;i<count;i++) release(&siblings[i]);
    return bad;
}

/* Repack with the same isolated Git configuration, attributes and ordering
 * as the producer. Compare decoded text so literal tabs, quotes and LF work. */
static int verify_git(const char *repo, packed_row *p, int count, int all, const char *member_batch) {
    char first[16],last[16];
    snprintf(first,sizeof(first),"%d",p->first); snprintf(last,sizeof(last),"%d",p->last);
    const char *single[]={"build/jovovich-pack",repo,p->base,p->head,p->path,p->file,first,last,NULL};
    const char *batch[]={"build/jovovich-pack","--all",repo,p->base,p->head,p->path,first,last,NULL};
    int full=all || member_batch;
    char *actual=command(full?batch:single,full?JOV_BATCH_MAX_BYTES:ROW_LIMIT);
    if (!actual) return 1;
    int bad=0;
    if (member_batch) bad=verify_member(actual,member_batch,p);
    else {
        char *line=actual;
        for (int i=0;i<count;i++) {
            char *end=strchr(line,'\n');
            if (!end) { bad=1; break; }
            *end=0;
            if (!matches_git_row(line,&p[i])) { bad=1; break; }
            line=end+1;
        }
        if (*line) bad=1;
    }
    free(actual);
    return bad || (p->fact && strcmp(p->fact->base,p->base) &&
                   (landed(repo,p->fact->base,p->base)!=1 || verify_origin_rule(repo,p->fact)));
}

/* Keep the case checkpoint in this process. A separate AML reader authenticates
 * the exact historical receipt, including its ordinal, predecessor and clock. */
static int verify_receipt(const char *dir, const jov_fact *f) {
    char seq[16]; snprintf(seq,sizeof(seq),"%d",f->sequence);
    char *json=command((const char *[]){"build/jovovich-pack","--fact",dir,f->repository,f->key,
                                      "--as-of",seq,NULL},ROW_LIMIT);
    jov_fact *known=NULL;
    int bad=!json || jov_fact_decode(json,&known) || !jov_fact_same(f,known);
    jov_fact_free(known); free(json);
    if (bad) fputs("Rule receipt differs from the named journal entry.\n",stderr);
    return bad;
}

/* A private copy, closed for writing before execution. Every call opens the
 * same descriptor via /dev/fd, including shebang scripts. No call resolves
 * the mutable operator path a second time. */
static int snapshot_driver(const char *path, char fdpath[64], char sha[65]) {
    int src=open(path,O_RDONLY|O_NONBLOCK|O_NOCTTY), wr=-1, rd=-1, failed=1;
    struct stat st;

    if (src<0 || fstat(src,&st) || !S_ISREG(st.st_mode) || st.st_size<=0 ||
        (uintmax_t)st.st_size>SIZE_MAX) goto done;
#ifdef __linux__
    wr=memfd_create("jovovich-driver",MFD_ALLOW_SEALING);
    if (wr<0) goto done;
    snprintf(fdpath,64,"/dev/fd/%d",wr);
    rd=open(fdpath,O_RDONLY);
    if (rd<0) goto done;
#else
    const char *dir=getenv("TMPDIR"); if (!dir || !*dir) dir="/tmp";
    size_t n=strlen(dir)+sizeof("/jov-driver-XXXXXX");
    char *tmp=malloc(n); if (!tmp) goto done;
    snprintf(tmp,n,"%s/jov-driver-XXXXXX",dir);
    wr=mkstemp(tmp);
    if (wr>=0) { rd=open(tmp,O_RDONLY); if (unlink(tmp)) { free(tmp); goto done; } }
    free(tmp);
    if (rd<0) goto done;
#endif
    char block[65536]; size_t total=0;
    for (;;) {
        ssize_t got=read(src,block,sizeof(block));
        if (got<0 && errno==EINTR) continue;
        if (got<0 || (size_t)got>(size_t)st.st_size-total) goto done;
        if (!got) break;
        for (ssize_t off=0;off<got;) {
            ssize_t w=write(wr,block+off,(size_t)(got-off));
            if (w<0 && errno==EINTR) continue;
            if (w<=0) goto done;
            off+=w;
        }
        total+=(size_t)got;
    }
    if (total!=(size_t)st.st_size || fchmod(wr,0500)) goto done;
#ifdef __linux__
    if (fcntl(wr,F_ADD_SEALS,F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)) goto done;
#endif
    void *bytes=mmap(NULL,total,PROT_READ,MAP_PRIVATE,rd,0);
    if (bytes==MAP_FAILED) goto done;
    failed=hash_bytes(bytes,total,sha);
    munmap(bytes,total);
    snprintf(fdpath,64,"/dev/fd/%d",rd);
done:
    if (wr>=0 && close(wr)) failed=1;
    if (src>=0) close(src);
    if (failed && rd>=0) { close(rd); rd=-1; }
    return rd;
}

/* Git membership and ordering are checked separately by the real packer. */
static int verify_batch(char **rows, packed_row *p, int count) {
    if (!nj_get(rows[0],"batch")) return count!=1;
    jov_batch_item items[JOV_BATCH_MAX_FILES]; char digest[65];
    for (int i=0;i<count;i++) {
        const char *b=nj_get(rows[i],"batch"); long long index,n;
        if (!nj_is(nj_get(b,"schema"),"jovovich.git-batch/1") || !nj_is(nj_get(b,"scope"),"all_changed_paths") ||
            nj_int(nj_get(b,"index"),&index) || index!=i || nj_int(nj_get(b,"count"),&n) || n!=count ||
            strcmp(p[i].base,p[0].base) || strcmp(p[i].head,p[0].head) || strcmp(p[i].path,p[0].path) ||
            p[i].first!=p[0].first || p[i].last!=p[0].last || !jov_fact_same(p[i].fact,p[0].fact)) return 1;
        items[i]=batch_item(&p[i]);
    }
    if (jov_batch_digest_fact(items,count,p[0].fact,digest)) return 1;
    for (int i=0;i<count;i++) if (!nj_is(nj_get(nj_get(rows[i],"batch"),"id"),digest)) return 1;
    return 0;
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
    if (!g || (stamped && !nj_is(stamped,sha)) ||
        !jov_git_context_matches(p->file,p->rule,p->change,p->context,p->id) || witness(row,p,&t) || !t.differing ||
        hash_bytes(row,strlen(row),r->source_sha)) return 1;
    strcpy(r->base,p->base); strcpy(r->head,p->head); strcpy(r->harness_sha,sha);
    r->mode = t.selected_mode;
    return 0;
}

/* Retain each original row while validating it against the new Git base. */
static int recall(const char *dir, const char *repo, const packed_row *p, const char *sha, jov_replay_ref *r) {
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
        failed = parse(chosen->data,&old);
        const char *batch=nj_get(chosen->data,"batch");
        if (!failed && batch) {
            int available=landed(repo,old.head,old.head);
            failed=available<0 || (available && verify_git(repo,&old,1,0,batch));
        }
        failed = failed || (!jov_fact_same(p->fact,old.fact) && verify_receipt(dir,old.fact)) || origin_ref(chosen->data,&old,sha,r);
        release(&old);
    }
    am_string_free(chosen);
    return failed;
}

/* Preserve the operator's compiler, libraries and fixture variables while
 * giving every driver the same Git object lookup as pack and replay. */
extern char **environ;
static int driver_environment(const char *repo,const char *runner) {
    for (size_t i=0;environ[i];) {
        const char *entry=environ[i], *equal=strchr(entry,'=');
        if (strncmp(entry,"GIT_",4) || !equal) { i++; continue; }
        char *name=strndup(entry,(size_t)(equal-entry));
        if (!name) return 1;
        int bad=unsetenv(name);
        free(name);
        if (bad) return 1;
    }
    const char *vars[][2]={
        {"GIT_NO_REPLACE_OBJECTS","1"},{"GIT_GRAFT_FILE","/dev/null"},{"GIT_SHALLOW_FILE",""},
        {"GIT_NO_LAZY_FETCH","1"},{"GIT_CONFIG_NOSYSTEM","1"},{"GIT_CONFIG_GLOBAL","/dev/null"},
        {"GIT_ATTR_NOSYSTEM","1"},{"GIT_CONFIG_COUNT","3"},
        {"GIT_CONFIG_KEY_0","core.commitGraph"},{"GIT_CONFIG_VALUE_0","false"},
        {"GIT_CONFIG_KEY_1","advice.graftFileDeprecated"},{"GIT_CONFIG_VALUE_1","false"},
        {"GIT_CONFIG_KEY_2","core.attributesFile"},{"GIT_CONFIG_VALUE_2","/dev/null"},
        {"JOV_REPOSITORY_PATH",repo},{"JOV_DRIVER_PATH",runner}
    };
    for (size_t i=0;i<sizeof(vars)/sizeof(*vars);i++)
        if (setenv(vars[i][0],vars[i][1],1)) return 1;
    return 0;
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

/* The base, head and oracle each start with a fresh object view. A driver may
 * create refs or a worktree while running without altering the next call. */
static char *run_callback(const char *source,const char *argv[],const char *kinds) {
    char *view=NULL, *result=NULL;
    if (!jov_git_snapshot(source,argv[3],&view)) {
        argv[2]=view;
        result=runner_json(argv,kinds);
    }
    if (jov_remove_git_snapshot(view)) { free(result); return NULL; }
    return result;
}

static int run_sample(const char *repo, const char *runner, const packed_row *p,
                      int mode, sample *x) {
    char arg[16], first[16], last[16];
    snprintf(arg,sizeof(arg),"%d",mode);
    snprintf(first,sizeof(first),"%d",p->first); snprintf(last,sizeof(last),"%d",p->last);
    x->base=run_callback(repo,(const char *[]){runner,"observe",NULL,p->base,p->file,arg,NULL},"[\"");
    if (x->base)
        x->head=run_callback(repo,(const char *[]){runner,"observe",NULL,p->head,p->file,arg,NULL},"[\"");
    if (x->head)
        x->oracle=run_callback(repo,(const char *[]){runner,"expect",NULL,p->base,p->file,arg,
                               p->path,first,last,NULL},"{");
    return !x->oracle;
}

static int remember(FILE *out, const char *dir, const char *repo, const char *runner, const char *row, const packed_row *p, const char *sha) {
    jov_replay_ref ref = {0};
    if (!p->fact || strlen(row) > 65536 || verify_receipt(dir,p->fact) || origin_ref(row,p,sha,&ref)) {
        fputs("Capture needs a named Git rule and a differing run from this harness.\n",stderr);
        return 1;
    }
    sample x = {0};
    int matches = !run_sample(repo,runner,p,ref.mode,&x) &&
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
    if (run_sample(repo,runner,p,mode,&x)) goto done;
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

/* All coordinates below come from Git. Only the reviewed program's driver
 * supplies observations and the expected effect. */
static int finding_start(FILE *out,const packed_row *p,const char *sha,const char *kind) {
    fputs("{\"schema\":\"jovovich.finding/1\",",out);
    json_field(out,"kind",kind); fputc(',',out); json_field(out,"file",p->file);
    fputc(',',out); json_field(out,"base_commit",p->base); fputc(',',out); json_field(out,"head_commit",p->head);
    fputc(',',out); json_field(out,"harness_sha256",sha); fputc(',',out); json_field(out,"rules_path",p->path);
    fprintf(out,",\"rule_first_line\":%d,\"rule_last_line\":%d,",p->first,p->last);
    json_field(out,"rule_excerpt",p->rule);
    return ferror(out);
}

static char *trial_observe(const char *repo,const char *runner,const char *rev,const char *file,const char *mode) {
    if (!rev) return NULL;
    return run_callback(repo,(const char *[]){runner,"observe",NULL,rev,file,mode,NULL},"[\"");
}

static char *control_observe(const char *repo,const char *runner,const char *rev,const char *file,const char *mode) {
    char spec[80]; snprintf(spec,sizeof(spec),"%s^{tree}",rev);
    char *tree=trial_oid(repo,(const char *[]){"rev-parse","--verify",spec,NULL},strlen(rev));
    char *commit=tree ? trial_commit(repo,tree,rev) : NULL;
    char *result=trial_observe(repo,runner,commit,file,mode);
    free(tree); free(commit);
    return result;
}

static sample test_hunk(const char *work,const char *path,const char *runner,const packed_row *p,
                        const trial_blob *base,const trial_blob *head,hunk h,const char *mode) {
    char *reverse=spliced_commit(work,p->head,p->file,path,head,h.head,base,h.base);
    char *forward=spliced_commit(work,p->base,p->file,path,base,h.base,head,h.head);
    sample observed={
        .base=trial_observe(work,runner,reverse,p->file,mode),
        .head=trial_observe(work,runner,forward,p->file,mode)
    };
    free(reverse); free(forward);
    return observed;
}

static const char *isolate_run(FILE *out,const char *repo,const char *runner,const packed_row *p,
                               const char *gate,int mode,const char *oracle) {
    char arg[16];
    snprintf(arg,sizeof(arg),"%d",mode);
    char *work=NULL, *path=NULL, *control_base=NULL, *control_head=NULL;
    trial_blob base={0},head={0}; hunk hunks[MAX_TRIAL_HUNKS];
    const char *status="unresolved";
    if (jov_git_snapshot(repo,p->head,&work) || !(path=snapshot_path(work,"/trial-blob")) ||
        load_trial_blob(work,p->base,p->file,&base) || load_trial_blob(work,p->head,p->file,&head)) goto done;
    int n=trial_hunks(work,&base,&head,hunks);
    if (n<1) goto done;
    control_base=control_observe(work,runner,p->base,p->file,arg);
    control_head=control_observe(work,runner,p->head,p->file,arg);
    if (!control_base || !control_head || !jov_trace_reproduced(gate,mode,control_base,control_head,oracle)) goto done;

    int matched=0, unknown=0, selected=0;
    fputs(",\"trials\":[",out);
    for (int i=0;i<n;i++) {
        hunk h=hunks[i];
        sample pair=test_hunk(work,path,runner,p,&base,&head,h,arg);
        const char *restored=pair.base,*introduced=pair.head;
        if (i) fputc(',',out);
        fprintf(out,"{\"base_start\":%d,\"base_lines\":%d,\"head_start\":%d,\"head_lines\":%d,"
                "\"after_revert\":%s,\"after_introduction\":%s}",h.base.start,h.base.count,
                h.head.start,h.head.count,restored ? restored : "null",introduced ? introduced : "null");
        if (!restored || !introduced || jov_trace_meets(oracle,restored)<0 || jov_trace_meets(oracle,introduced)<0) unknown++;
        else if (jov_trace_reproduced(gate,mode,restored,introduced,oracle)) { matched++; selected=i; }
        free_sample(&pair);
    }
    fputc(']',out);
    if (!unknown && matched==1) {
        hunk h=hunks[selected];
        sample repeat=test_hunk(work,path,runner,p,&base,&head,h,arg);
        int reproduced=repeat.base && repeat.head && jov_trace_reproduced(gate,mode,repeat.base,repeat.head,oracle);
        free_sample(&repeat);
        if (!reproduced) goto done;
        fprintf(out,",\"location\":{\"base_start\":%d,\"base_lines\":%d,\"head_start\":%d,\"head_lines\":%d}",
                h.base.start,h.base.count,h.head.start,h.head.count);
        status="located";
    } else if (matched>1) status="ambiguous";
done:
    free(control_base); free(control_head); free(path);
    free(base.oid); free(base.text); free(head.oid); free(head.text);
    return jov_remove_git_snapshot(work) ? NULL : status;
}

static int locate_mode(FILE *out,const char *repo,const char *runner,const packed_row *p,
                       const char *sha,const char *gate,int mode) {
    sample x={0};
    int failed=1;
    if (run_sample(repo,runner,p,mode,&x) ||
        !jov_trace_reproduced(gate,mode,x.base,x.head,x.oracle)) goto done;
    int before=jov_trace_meets(x.oracle,x.base), after=jov_trace_meets(x.oracle,x.head);
    if (before<0 || after<0 || finding_start(out,p,sha,"execution")) goto done;
    fprintf(out,",\"mode\":%d,\"before\":%s,\"after\":%s,\"oracle\":%s,",mode,x.base,x.head,x.oracle);
    json_field(out,"review_id",p->id);
    const char *status=after ? "met" : before ? isolate_run(out,repo,runner,p,gate,mode,x.oracle) : "already_failing";
    if (!status) goto done;
    fputc(',',out); json_field(out,"status",status); failed=fputs("}\n",out)==EOF;
done:
    free_sample(&x);
    return failed;
}

static int locate(FILE *out,const char *repo,const char *runner,const char *row,const packed_row *p,const char *sha) {
    const char *gate=nj_get(row,"trace_evidence");
    jov_trace_receipt receipt={0};
    if (!gate || !nj_is(nj_get(gate,"harness_sha256"),sha) || witness(row,p,&receipt) || !receipt.runs) return 1;
    int bad=0;
    for (const char *run=nj_first(nj_get(gate,"runs"),&bad); run; run=nj_next(run,']',&bad)) {
        long long mode;
        if (nj_int(nj_get(run,"mode"),&mode) || locate_mode(out,repo,runner,p,sha,gate,(int)mode)) return 1;
    }
    return bad;
}

/* The driver emits the regenerated snapshot bytes on stdout. The expected
 * bytes always come from the regular blob in the reviewed head. */
static char *render_snapshot(const char *repo,const char *runner,const packed_row *p) {
    char *view=NULL,*result=NULL;
    if (!jov_git_snapshot(repo,p->head,&view))
        result=command((const char *[]){runner,"render",view,p->head,p->file,NULL},TRIAL_BYTES);
    if (jov_remove_git_snapshot(view)) { free(result); return NULL; }
    return result;
}

static int snapshot_check(FILE *out,const char *repo,const char *runner,const packed_row *p,const char *sha) {
    char *view=NULL, *oid=NULL, *gold=NULL, *actual=NULL;
    int failed=1;
    if (jov_git_snapshot(repo,p->head,&view)) goto done;
    oid=jov_git_rule_blob(view,p->head,p->file);
    if (!oid || !(gold=trial_git(view,(const char *[]){"cat-file","blob",oid,NULL}))) goto done;
    actual=render_snapshot(repo,runner,p);
    if (!actual || !report_utf8((unsigned char *)actual,(unsigned char *)actual+strlen(actual),0) ||
        !report_utf8((unsigned char *)gold,(unsigned char *)gold+strlen(gold),0) ||
        finding_start(out,p,sha,"snapshot")) goto done;
    size_t i=0,start=0,line=1;
    while (gold[i] && gold[i]==actual[i]) {
        if (gold[i++]=='\n') { line++; start=i; }
    }
    int equal=gold[i]==actual[i];
    char generated_sha[65];
    if (hash_bytes(actual,strlen(actual),generated_sha)) goto done;
    fputc(',',out); json_field(out,"expected_blob",oid);
    fputc(',',out); json_field(out,"observed_sha256",generated_sha);
    if (!equal) {
        char *again=render_snapshot(repo,runner,p);
        int reproduced=again && !strcmp(again,actual);
        free(again);
        if (!reproduced) { fputs("Snapshot mismatch did not reproduce.\n",stderr); goto done; }
        char *a=strchr(actual+start,'\n'), *g=strchr(gold+start,'\n');
        if (a) a[1]=0;
        if (g) g[1]=0;
        fprintf(out,",\"line\":%zu,\"byte_column\":%zu,",line,i-start+1);
        json_field(out,"expected",gold+start); fputc(',',out); json_field(out,"observed",actual+start);
    }
    fputc(',',out); json_field(out,"status",equal ? "met" : "mismatch"); failed=fputs("}\n",out)==EOF;
done:
    free(oid); free(gold); free(actual);
    return jov_remove_git_snapshot(view) || failed;
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
    int locating=argc==4 && !strcmp(argv[1],"locate");
    int snapshot=argc==4 && !strcmp(argv[1],"snapshot");
    int direct=probe || locating || snapshot;
    int mode=0;
    if ((!direct && !capture && !replay) || (probe && parse_mode(argv[4],&mode))) {
        fputs("Usage: jovovich-replay probe REPO HARNESS MODE | remember DIR REPO HARNESS | run DIR REPO HARNESS < packed.jsonl\n       jovovich-replay locate REPO HARNESS < measured.jsonl\n       jovovich-replay snapshot REPO HARNESS < packed.jsonl\n       jovovich-replay show DIR INPUT_SHA256\n",stderr);
        return 2;
    }
    const char *dir = direct ? NULL : argv[2];
    char *repo = realpath(argv[direct?2:3],NULL);
    char *runner = realpath(argv[direct?3:4],NULL);
    char sha[65], fdpath[64], *lines[JOV_BATCH_MAX_FILES]={0};
    packed_row inputs[JOV_BATCH_MAX_FILES]={0};
    size_t bytes=0; int bad_input=0, writer=-1, driverfd=-1;
    int count=0, at=0, failed=1;
    FILE *out=tmpfile();
    if (!repo || !runner || access(runner,X_OK) || (driverfd=snapshot_driver(runner,fdpath,sha))<0 ||
        driver_environment(repo,runner) || !out) goto done;
    am_init(); am_persistent_mode(1);
    if (replay && open_cases(dir,0,&writer)) goto done;
    for (;;) {
        char *row=report_json_row(stdin,&bytes,&bad_input,ROW_LIMIT,JOV_BATCH_MAX_BYTES);
        if (!row) break;
        if (count==JOV_BATCH_MAX_FILES) { free(row); goto done; }
        at=count+1; lines[count++]=row;
        if (parse(row,inputs+count-1) || (!capture && !locating && nj_get(row,"trace_evidence"))) goto done;
    }
    const char *batch=count ? nj_get(lines[0],"batch") : NULL;
    long long members=0;
    int whole_single=count==1 && batch && !nj_int(nj_get(batch,"count"),&members) && members==1;
    int full_batch=replay || (locating && (count>1 || whole_single));
    if (!count || bad_input || ferror(stdin) || (!full_batch && count!=1) ||
        (full_batch && verify_batch(lines,inputs,count))) goto done;
    if (replay && inputs[0].fact && verify_receipt(dir,inputs[0].fact)) goto done;
    if (verify_git(repo,inputs,count,full_batch && batch,full_batch ? NULL : batch)) goto done;
    for (int i=0;i<count;i++) {
        at=i+1; packed_row *p=inputs+i; const char *line=lines[i];
        jov_replay_ref ref={0}; int bad=0;
        if (replay && p->fact) bad=recall(dir,repo,p,sha,&ref);
        if (locating && (!full_batch || nj_get(line,"trace_evidence")))
            bad=locate(out,repo,fdpath,line,p,sha);
        if (snapshot) bad=snapshot_check(out,repo,fdpath,p,sha);
        if (!bad && capture) bad=remember(out,dir,repo,fdpath,line,p,sha);
        if (!bad && (probe || ref.source_sha[0]))
            bad=measure(out,repo,fdpath,sha,line,p,probe?mode:ref.mode,probe?NULL:&ref);
        else if (!bad && replay) bad=fputs(line,out)==EOF;
        long staged=ftell(out);
        if (bad || staged<0 || (unsigned long)staged>JOV_BATCH_MAX_BYTES) goto done;
    }
    if (fseek(out,0,SEEK_SET)) goto done;
    char block[8192]; size_t n;
    while ((n=fread(block,1,sizeof(block),out))) if (fwrite(block,1,n,stdout)!=n) goto done;
    failed=ferror(out) || fflush(stdout);
done:
    if (failed) fprintf(stderr,"Counterexample %s failed at row %d.\n",argv[1],at);
    if (out && fclose(out)) failed=1;
    for (int i=0;i<count;i++) { release(inputs+i); free(lines[i]); }
    if (driverfd>=0) close(driverfd);
    free(repo); free(runner); am_persistent_mode(0);
    return failed?1:0;
}
