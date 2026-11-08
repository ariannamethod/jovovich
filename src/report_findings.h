#ifndef JOV_REPORT_FINDINGS_H
#define JOV_REPORT_FINDINGS_H
#include "process.h"

/* Each job uses an operator-supplied driver for execution localization, an
 * explicit snapshot, or all snapshot paths selected by a repository policy. */
typedef struct { const char *repo,*driver,*file,*routes; } finding_job;
typedef struct { int json,count; const char *memory; finding_job jobs[JOV_BATCH_MAX_FILES+1]; } report_options;

static int report_arguments(int argc,char **argv,report_options *opts) {
    if (argc<3) return 1;
    int has_locate=0,has_manual=0;
    finding_job automatic={0};
    for (int i=3;i<argc;) {
        const char *flag=argv[i++];
        if (!strcmp(flag,"--json") && !opts->json) { opts->json=1; continue; }
        if (!strcmp(flag,"--memory") && !opts->memory && i<argc) { opts->memory=argv[i++]; continue; }
        if (!strcmp(flag,"--auto-snapshots")) {
            if (automatic.routes || argc-i<3) return 1;
            automatic=(finding_job){.repo=argv[i],.driver=argv[i+1],.routes=argv[i+2]};
            i+=3;
            continue;
        }
        int snapshot=!strcmp(flag,"--snapshot");
        if ((!snapshot && strcmp(flag,"--locate")) || argc-i<2+snapshot || opts->count>=JOV_BATCH_MAX_FILES+1) return 1;
        finding_job job={.repo=argv[i],.driver=argv[i+1],.file=snapshot ? argv[i+2] : NULL};
        for (int j=0;j<opts->count;j++) {
            const char *file=opts->jobs[j].file;
            if ((!file && !job.file) || (file && job.file && !strcmp(file,job.file))) return 1;
        }
        if (snapshot) has_manual=1; else has_locate=1;
        opts->jobs[opts->count++]=job;
        i+=2+snapshot;
    }
    if (automatic.routes) {
        if (has_manual || !opts->memory) return 1;
        opts->jobs[opts->count++]=automatic;
    }
    return opts->memory && !has_locate && !automatic.routes;
}

/* Replay receives the bytes already authenticated against the model answers.
 * Reopening the caller's batch path here could review a later replacement. */
static char *run_finding_job(const finding_job *job,const input inputs[],int count,const char *memory,size_t limit,size_t *size) {
    FILE *rows=tmpfile();
    if (!rows) return NULL;
    char *result=NULL;
    int n=0,status=1;
    for (int i=0;i<count;i++) {
        if (job->file && strcmp(job->file,inputs[i].file)) continue;
        if (fputs(inputs[i].row,rows)==EOF) goto done;
        n++;
    }
    if (!n || fseek(rows,0,SEEK_SET)) goto done;
    const char *args[]={"build/jovovich-replay",job->file ? "snapshot" : "locate",job->repo,job->driver,
                        !job->file && memory ? "--memory" : NULL,memory,NULL};
    const char *routed[]={"build/jovovich-replay","snapshots",job->repo,job->driver,job->routes,"--memory",memory,NULL};
    result=jov_command_input(job->routes ? routed : args,fileno(rows),limit,size,&status);
    if (result && (status || memchr(result,0,*size))) { free(result); result=NULL; }
done:
    fclose(rows);
    return result;
}

static int finding_location(FILE *out,const char *file,const char *range) {
    long long start,lines;
    if (nj_int(nj_get(range,"head_start"),&start) || nj_int(nj_get(range,"head_lines"),&lines)) return 1;
    int deleted=lines==0;
    if (deleted && (nj_int(nj_get(range,"base_start"),&start) || nj_int(nj_get(range,"base_lines"),&lines))) return 1;
    if (start<1 || start>INT_MAX || lines<1 || lines>INT_MAX) return 1;
    jov_markdown_text(out,file,0);
    fprintf(out,":%lld",start);
    if (lines>1) fprintf(out,"–%lld",start+lines-1);
    if (deleted) fputs(" (deleted from base)",out);
    return 0;
}

static int finding_value(FILE *out,const char *label,const char *value) {
    const char *end=value ? report_json_end(value,0) : NULL;
    char *text=end ? strndup(value,(size_t)(end-value)) : NULL;
    if (!text) return 1;
    fprintf(out,"\n- %s ",label);
    jov_markdown_text(out,text,0);
    free(text);
    return 0;
}

static int execution_markdown(FILE *out,const char *f,const input *p) {
    const char *status=nj_get(f,"status"),*oracle=nj_get(f,"oracle");
    long long mode;
    if (nj_int(nj_get(f,"mode"),&mode)) return 1;
    if (nj_is(status,"met")) {
        fputs("\n**Execution check passed** · ",out); jov_markdown_text(out,p->file,0);
    } else if (nj_is(status,"located")) {
        fputs("\n**Verified regression** · ",out);
        if (finding_location(out,p->file,nj_get(f,"location"))) return 1;
    } else {
        if (nj_is(status,"ambiguous")) fputs("\n**Regression with several matching changes** · ",out);
        else if (nj_is(status,"already_failing")) fputs("\n**Requirement already failed on the base** · ",out);
        else if (nj_is(status,"unresolved")) fputs("\n**Regression reproduced, location unresolved** · ",out);
        else return 1;
        jov_markdown_text(out,p->file,0);
    }
    fprintf(out," · mode %lld\n",mode);
    if (nj_is(status,"ambiguous")) {
        int bad=0,n=0;
        for (const char *t=nj_first(nj_get(f,"trials"),&bad); t; t=nj_next(t,']',&bad)) {
            const char *match=nj_get(t,"matches_original_pair");
            if (!match || strncmp(match,"true",4)) continue;
            fputs(n++ ? ", " : "\nMatching changes: ",out);
            if (finding_location(out,p->file,t)) return 1;
        }
        if (bad || n<2) return 1;
        fputc('\n',out);
    }
    fputs("\nRule from ",out); jov_markdown_text(out,p->origin[2],0);
    fprintf(out,":%d–%d (base)\n\n",p->item.source.first_line,p->item.source.last_line);
    jov_markdown_text(out,p->rule,1); fputc('\n',out);
    if (finding_value(out,"Before:",nj_get(f,"before")) || finding_value(out,"After:",nj_get(f,"after")) ||
        finding_value(out,"Required:",nj_get(oracle,"required"))) return 1;
    if (nj_is(nj_get(oracle,"metric"),"count") && finding_value(out,"Counted callback:",nj_get(oracle,"target"))) return 1;
    fputc('\n',out);
    return ferror(out);
}

static int history_markdown(FILE *out,const char *f,const input *p) {
    jov_replay_ref prior;
    if (jov_replay_ref_read(nj_get(f,"replayed_from"),&prior)) return 1;
    if (!prior.source_sha[0]) return 0;
    const char *history=nj_get(f,"historical_observation");
    if (!history) { jov_replay_ref_markdown(out,&prior); return ferror(out); }
    const char *run=nj_get(history,"run");
    jov_fact *fact=NULL;
    if (!p->fact || jov_fact_decode(nj_get(history,"fact"),&fact) || !fact) return 1;
    fputs("\n**Earlier AML observation** · ",out); jov_markdown_text(out,fact->key,0);
    fprintf(out," · rule receipt %d · `%.12s` → `%.12s`\n",fact->sequence,prior.base,prior.head);
    if (fact->sequence!=p->fact->sequence) {
        fprintf(out,"\nEarlier rule (current receipt %d)\n\n",p->fact->sequence);
        jov_markdown_text(out,fact->quote,1); fputc('\n',out);
    }
    jov_fact_free(fact);
    if (finding_value(out,"Earlier base:",nj_get(run,"base")) || finding_value(out,"Earlier head:",nj_get(run,"head")) ||
        finding_value(out,"Earlier requirement:",nj_get(run,"required"))) return 1;
    if (nj_is(nj_get(history,"metric"),"count") && finding_value(out,"Counted callback:",nj_get(history,"target"))) return 1;
    fprintf(out,"\n\nOriginal input `%s`.\n",prior.source_sha);
    return ferror(out);
}

static int snapshot_markdown(FILE *out,const char *f,const input *p) {
    const char *status=nj_get(f,"status");
    if (nj_is(status,"met")) {
        fputs("\n**Snapshot matched** · ",out); jov_markdown_text(out,p->file,0); fputc('\n',out);
        return 0;
    }
    long long line,column;
    if (!nj_is(status,"mismatch") || nj_int(nj_get(f,"line"),&line) || nj_int(nj_get(f,"byte_column"),&column)) return 1;
    fputs("\n**Snapshot mismatch** · ",out); jov_markdown_text(out,p->file,0);
    fprintf(out,":%lld · byte %lld\n",line,column);
    if (finding_value(out,"Expected in Git:",nj_get(f,"expected")) ||
        finding_value(out,"Regenerated:",nj_get(f,"observed"))) return 1;
    fputc('\n',out);
    return ferror(out);
}

static int finding_input(const char *entry,const input inputs[],int count) {
    char *file=nj_string(nj_get(entry,"file"));
    int i=0;
    while (i<count && (!file || strcmp(inputs[i].file,file))) i++;
    free(file);
    return i;
}

/* Check that every path is either rendered once or explicitly accounted for. */
static int snapshot_coverage(FILE *out,const char *line,int json,const input inputs[],int count,
                             int seen[],int matched,int mismatched) {
    long long a,b;
    const char *skips=nj_get(line,"skipped");
    if (!inputs[0].fact || !nj_is(nj_get(line,"repository"),inputs[0].fact->repository) ||
        nj_int(nj_get(line,"matched"),&a) || nj_int(nj_get(line,"mismatched"),&b) ||
        a!=matched || b!=mismatched || !skips || *skips!='[') return 1;
    if (!json) fprintf(out,"\n**Snapshot checks:** %d matched, %d mismatched, %d skipped.\n",matched,mismatched,count-matched-mismatched);
    int bad=0,n=matched+mismatched;
    for (const char *s=nj_first(skips,&bad); s && !bad; s=nj_next(s,']',&bad)) {
        int i=finding_input(s,inputs,count);
        const char *r=nj_get(s,"reason"),*reason=NULL;
        if (nj_is(r,"no_matching_rule")) reason="no matching snapshot rule";
        else if (nj_is(r,"deleted")) reason="deleted in head";
        else if (nj_is(r,"non_regular_head")) reason="head entry is not a regular file";
        if (i==count || seen[i] || !reason) return 1;
        seen[i]=1; n++;
        if (!json) {
            fputs("\n- ",out); jov_markdown_text(out,inputs[i].file,0);
            fprintf(out," — %s",reason);
        }
    }
    if (bad || n!=count) return 1;
    if (json) { fputs("],\"snapshot_coverage\":",out); fputs(line,out); }
    else fputc('\n',out);
    return ferror(out);
}

static int report_findings(FILE *out,const report_options *opts,const input inputs[],int count) {
    if (!opts->count) return 0;
    fputs(opts->json ? ",\"verified_findings\":[" : "\n### Verified checks\n",out);
    int written=0,covered=0;
    size_t total=0;
    for (int j=0;j<opts->count;j++) {
        const finding_job *job=&opts->jobs[j];
        size_t size=0;
        char *data=run_finding_job(job,inputs,count,opts->memory,JOV_BATCH_MAX_BYTES-total,&size);
        if (!data) return 1;
        total+=size;
        int failed=0,seen[JOV_BATCH_MAX_FILES]={0},matched=0,mismatched=0;
        for (char *line=data; *line && !failed;) {
            char *nl=strchr(line,'\n');
            if (!nl) { failed=1; break; }
            *nl=0;
            const char *end=report_json_end(line,0);
            if (!end || *end) { failed=1; break; }
            if (job->routes && nj_is(nj_get(line,"schema"),"jovovich.snapshot-coverage/1")) {
                failed=nl[1]!=0 || snapshot_coverage(out,line,opts->json,inputs,count,seen,matched,mismatched);
                covered=!failed;
                break;
            }
            if (!nj_is(nj_get(line,"schema"),"jovovich.finding/1") ||
                !nj_is(nj_get(line,"kind"),(job->file || job->routes) ? "snapshot" : "execution")) { failed=1; break; }
            int i=finding_input(line,inputs,count);
            if (i==count || (job->file && strcmp(job->file,inputs[i].file)) ||
                !nj_is(nj_get(line,"base_commit"),inputs[i].origin[0]) ||
                !nj_is(nj_get(line,"head_commit"),inputs[i].origin[1])) { failed=1; break; }
            if (job->routes) {
                if (seen[i]) { failed=1; break; }
                seen[i]=1;
                if (nj_is(nj_get(line,"status"),"met")) matched++;
                else if (nj_is(nj_get(line,"status"),"mismatch")) mismatched++;
                else { failed=1; break; }
            }
            if (opts->json) {
                if (written) fputc(',',out);
                fputs(line,out);
            } else if (job->file || job->routes) failed=snapshot_markdown(out,line,inputs+i);
            else failed=execution_markdown(out,line,inputs+i) || history_markdown(out,line,inputs+i);
            written++; line=nl+1;
        }
        free(data);
        if (failed || (job->routes && !covered)) return 1;
    }
    if (covered) return ferror(out);
    if (opts->json) fputc(']',out);
    else if (!written) fputs("\nNo recorded executions in this batch.\n",out);
    return ferror(out);
}
#endif
