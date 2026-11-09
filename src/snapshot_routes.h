#ifndef JOV_SNAPSHOT_ROUTES_H
#define JOV_SNAPSHOT_ROUTES_H
#include <fnmatch.h>
#include <strings.h>

/* The operator supplies the policy outside the reviewed tree. It identifies
 * the repository and the exact renderer bytes already sealed by replay. */
typedef struct {
    char digest[65];
    char *patterns[JOV_BATCH_MAX_FILES];
    int count;
} snapshot_routes;

static int load_routes(const char *path,const char *repository,const char *sha,snapshot_routes *routes) {
    char json[16385];
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_NOCTTY);
    if (fd<0) return 1;
    struct stat st;
    FILE *f=NULL;
    if (!fstat(fd,&st) && S_ISREG(st.st_mode)) f=fdopen(fd,"rb");
    if (!f) { close(fd); return 1; }
    size_t n=fread(json,1,sizeof(json),f);
    int bad=ferror(f) || n==sizeof(json) || memchr(json,0,n)!=NULL;
    fclose(f);
    if (bad) return 1;
    json[n]=0;
    const char *end=report_json_end(json,0);
    if (!end || *nj_ws(end) || !nj_is(nj_get(json,"schema"),"jovovich.snapshot-routes/1") ||
        !nj_is(nj_get(json,"harness_sha256"),sha) || hash_bytes(json,n,routes->digest)) return 1;
    int keys=0;
    for (const char *k=nj_first(json,&bad); k && !bad; ) {
        const char *v=nj_value(k,&bad);
        keys++;
        k=nj_next(v,'}',&bad);
    }
    if (bad || keys!=4) return 1;
    char *name=nj_string(nj_get(json,"repository"));
    bad=!name || strcasecmp(name,repository);
    free(name);
    const char *paths=nj_get(json,"paths");
    if (bad || !paths || *paths!='[') return 1;
    for (const char *v=nj_first(paths,&bad); v && !bad; v=nj_next(v,']',&bad)) {
        if (routes->count==JOV_BATCH_MAX_FILES) return 1;
        char *pattern=nj_string(v);
        if (!pattern) return 1;
        routes->patterns[routes->count++]=pattern;
        if (!*pattern || strlen(pattern)>1024 || *pattern=='/' || pattern[strlen(pattern)-1]=='/') return 1;
    }
    return bad || !routes->count;
}

static int route_snapshots(FILE *out,const char *repo,const char *runner,const char *sha,
                           const snapshot_routes *routes,packed_row revision,char *const paths[],int count,char **coverage) {
    const char *skip[JOV_BATCH_MAX_FILES]={0},*repository=revision.fact->repository;
    char *view=NULL;
    int failed=1,matched=0,mismatched=0;
    if (jov_git_snapshot(repo,revision.head,&view)) goto done;
    for (int i=0;i<count;i++) {
        revision.file=paths[i];
        int j=0;
        while (j<routes->count && fnmatch(routes->patterns[j],revision.file,FNM_PATHNAME|FNM_PERIOD)!=0) j++;
        if (j==routes->count) { skip[i]="no_matching_rule"; continue; }
        int kind=jov_git_path_kind(view,revision.head,revision.file);
        if (kind<0) goto done;
        if (kind!=1) { skip[i]=kind==0 ? "deleted" : "non_regular_head"; continue; }
        int equal=0;
        if (snapshot_check(out,repo,runner,&revision,sha,&equal)) goto done;
        if (equal) matched++; else mismatched++;
        long size=ftell(out);
        if (size<0 || (unsigned long)size>JOV_BATCH_MAX_BYTES) goto done;
    }
    size_t length=0;
    FILE *summary=open_memstream(coverage,&length);
    if (!summary) goto done;
    fputs("{\"schema\":\"jovovich.snapshot-coverage/1\",",summary);
    json_field(summary,"repository",repository); fputc(',',summary);
    json_field(summary,"routes_sha256",routes->digest); fputc(',',summary);
    json_field(summary,"harness_sha256",sha);
    fprintf(summary,",\"matched\":%d,\"mismatched\":%d,\"skipped\":[",matched,mismatched);
    int skipped=0;
    for (int i=0;i<count;i++) {
        if (!skip[i]) continue;
        if (skipped++) fputc(',',summary);
        fputc('{',summary); json_field(summary,"file",paths[i]);
        fputc(',',summary); json_field(summary,"reason",skip[i]); fputc('}',summary);
    }
    fputs("]}",summary);
    int bad=fclose(summary);
    long total=ftell(out);
    failed=bad || ferror(out) || total<0 || (unsigned long)total+length+1>JOV_BATCH_MAX_BYTES;
done:
    return jov_remove_git_snapshot(view) || failed;
}
#endif
