#ifndef JOV_REVIEW_HISTORY_H
#define JOV_REVIEW_HISTORY_H
#include <math.h>

/* Offline views of complete, already-validated mixed review receipts. */
typedef struct {
    char *path;
    const char *input, *answer;
    int visual, concern;
} saved_review_file;

typedef struct {
    const char *row, *evidence, *review;
    jov_fact *fact;
    int count, concerns, visual, visual_concerns;
    saved_review_file files[JOV_BATCH_MAX_FILES];
} saved_review;

static int review_id_valid(const char *id) {
    return id && strlen(id)==64 && strspn(id,"0123456789abcdef")==64;
}

static int review_evidence_identity(const char *evidence, const char *id) {
    char digest[65];
    return !review_id_valid(id) || json_digest(evidence,digest) || strcmp(id,digest);
}

static int review_identity(const char *evidence, const char *id) {
    return !nj_is(nj_get(nj_get(evidence,"review"),"schema"),"jovovich.mixed-review/1") ||
        review_evidence_identity(evidence,id);
}

static int review_same_value(const char *left, const char *right) {
    if (!left || !right) return left==right;
    char *a=nj_string(left), *b=nj_string(right);
    int same;
    if (a || b) same=a && b && !strcmp(a,b);
    else {
        const char *ae=report_json_end(left,0), *be=report_json_end(right,0);
        same=ae && be && ae-left==be-right && !memcmp(left,right,(size_t)(ae-left));
    }
    free(a); free(b);
    return same;
}

static int review_same_member(const char *left, const char *right, const char *key) {
    return review_same_value(nj_get(left,key),nj_get(right,key));
}

static int review_integer(const char *object, const char *key, int expected) {
    long long value;
    return nj_int(nj_get(object,key),&value) || value!=expected;
}

static int review_string(const char *object, const char *key) {
    char *value=nj_string(nj_get(object,key));
    int bad=!value || !*value;
    free(value); return bad;
}

static int review_hash(const char *object, const char *key) {
    char *value=nj_string(nj_get(object,key));
    int bad=!review_id_valid(value);
    free(value); return bad;
}

static int review_commit(const char *object, const char *key) {
    char *value=nj_string(nj_get(object,key));
    size_t n=value?strlen(value):0;
    int bad=(n!=40 && n!=64) || strspn(value?value:"","0123456789abcdef")!=n;
    free(value); return bad;
}

static int review_fact_matches(const char *value, const jov_fact *fact) {
    jov_fact *other=NULL;
    int bad=jov_fact_decode(value,&other) || !jov_fact_same(other,fact);
    jov_fact_free(other); return bad;
}

static const char *review_image(const char *answer, const char *side) {
    return nj_get(nj_get(nj_get(nj_get(answer,"comparison"),side),"origin"),"observation");
}

static int review_summary(const char *summary, int count, int concerns, int verdict) {
    return review_integer(summary,"reviewed_files",count) || review_integer(summary,"concern_files",concerns) ||
        review_integer(summary,"clean_files",count-concerns) ||
        (verdict && !nj_is(nj_get(summary,"verdict"),concerns?"CONCERN":"CLEAN"));
}

static void saved_review_free(saved_review *review) {
    for (int i=0;i<review->count;i++) free(review->files[i].path);
    jov_fact_free(review->fact);
}

static int saved_review_read(saved_review *review, const char *row, const char *id, const jov_pr *pr) {
    const char *end=report_json_end(row,0), *e=nj_get(row,"evidence"), *r=nj_get(e,"review");
    int bad=0;
    if (!end || *nj_ws(end) || review_identity(e,id) || review_hash(e,"batch_id") ||
        review_commit(e,"base_commit") || review_commit(e,"head_commit") || jov_fact_decode(nj_get(e,"fact"),&review->fact) ||
        !review->fact || strcasecmp(review->fact->repository,pr->repository)) return 1;
    review->row=row; review->evidence=e; review->review=r;
    for (const char *f=nj_first(nj_get(r,"files"),&bad); f && !bad; f=nj_next(f,']',&bad)) {
        if (review->count==JOV_BATCH_MAX_FILES) return 1;
        saved_review_file *p=&review->files[review->count++];
        p->path=nj_string(nj_get(f,"file")); p->input=nj_get(f,"input"); p->answer=nj_get(f,"answer");
        if (!p->path || !*p->path || !nj_is(nj_get(p->input,"file"),p->path) || !p->answer) return 1;
        for (int i=0;i<review->count-1;i++) if (!strcmp(review->files[i].path,p->path)) return 1;
        const char *source=nj_get(p->input,"source");
        if (!review_same_member(source,e,"base_commit") || !review_same_member(source,e,"head_commit") ||
            review_string(p->input,"rule_excerpt") || review_string(p->answer,"question") ||
            review_fact_matches(nj_get(p->input,"fact"),review->fact)) return 1;
        p->visual=nj_get(p->input,"visual_request")!=NULL;
        const char *vote=nj_get(p->visual?p->answer:nj_get(p->answer,"choice"),"verdict");
        p->concern=nj_is(vote,"CONCERN");
        if (!p->concern && !nj_is(vote,"CLEAN")) return 1;
        const char *execution=p->visual?p->answer:nj_get(p->answer,"execution");
        if (review_hash(execution,"weights_sha256") || review_hash(execution,"tokenizer_sha256")) return 1;
        if (p->visual) {
            if (!nj_is(nj_get(p->answer,"schema"),"jovovich.visual-review/1") ||
                review_string(p->answer,"choice_a") || review_string(p->answer,"choice_b")) return 1;
            const char *sides[]={"before","after"};
            for (int i=0;i<2;i++) {
                const char *origin=nj_get(nj_get(nj_get(p->answer,"comparison"),sides[i]),"origin");
                const char *image=review_image(p->answer,sides[i]), *src=nj_get(origin,"source");
                char *scope=nj_string(nj_get(src,"repository"));
                int foreign=!scope || strcasecmp(scope,pr->repository) ||
                    review_integer(src,"pull_request",atoi(pr->number)) || !nj_is(nj_get(src,"path"),p->path);
                free(scope);
                if (foreign || review_hash(image,"weights_sha256") || review_hash(image,"tokenizer_sha256") ||
                    review_hash(image,"vision_weights_sha256") || review_string(image,"question") ||
                    review_string(image,"choice_a") || review_string(image,"choice_b")) return 1;
            }
            review->visual++; review->visual_concerns+=p->concern;
        } else if (review_integer(p->answer,"schema_version",1) || review_fact_matches(nj_get(p->answer,"fact"),review->fact) ||
                   !nj_is(nj_get(nj_get(p->answer,"scope"),"file"),p->path) ||
                   review_string(nj_get(p->answer,"model"),"id") || review_string(nj_get(p->answer,"model"),"revision")) return 1;
        review->concerns+=p->concern;
    }
    return bad || !review->count || !review->visual ||
        review_summary(nj_get(r,"summary"),review->count,review->concerns,1) ||
        review_summary(nj_get(r,"visual_summary"),review->visual,review->visual_concerns,0);
}

/* Compare identity fields, leaving input-dependent logits and prompt hashes in
 * the two complete original observations. Multiple changes remain visible. */
static int review_differences(const saved_review_file *a, const saved_review_file *b, int same_fact) {
    int differences=a->visual!=b->visual ? 1 : 0;
    const char *as=nj_get(a->input,"source"), *bs=nj_get(b->input,"source");
    if (!same_fact || !review_same_member(a->input,b->input,"rule_excerpt") ||
        !review_same_member(as,bs,"rules_path") || !review_same_member(as,bs,"rule_first_line") ||
        !review_same_member(as,bs,"rule_last_line")) differences|=2;
    if (a->visual!=b->visual) return differences;
    const char *ae=a->visual?a->answer:nj_get(a->answer,"execution");
    const char *be=b->visual?b->answer:nj_get(b->answer,"execution");
    if (!review_same_member(ae,be,"weights_sha256") || !review_same_member(ae,be,"tokenizer_sha256") ||
        (!a->visual && (!review_same_member(nj_get(a->answer,"model"),nj_get(b->answer,"model"),"id") ||
                       !review_same_member(nj_get(a->answer,"model"),nj_get(b->answer,"model"),"revision")))) differences|=4;
    if (!review_same_member(a->answer,b->answer,"question")) differences|=8;
    if (a->visual) {
        const char *ac=nj_get(a->answer,"comparison"), *bc=nj_get(b->answer,"comparison");
        const char *rule_fields[]={"path","first","last","quote"};
        for (int i=0;i<4;i++) if (!review_same_member(nj_get(ac,"rule"),nj_get(bc,"rule"),rule_fields[i])) differences|=2;
        if (!review_same_member(a->answer,b->answer,"choice_a") || !review_same_member(a->answer,b->answer,"choice_b") ||
            !review_same_member(ac,bc,"key")) differences|=8;
        const char *sides[]={"before","after"};
        for (int i=0;i<2;i++) {
            const char *ai=review_image(a->answer,sides[i]), *bi=review_image(b->answer,sides[i]);
            const char *models[]={"weights_sha256","tokenizer_sha256","vision_weights_sha256"};
            const char *policy[]={"question","choice_a","choice_b"};
            for (int j=0;j<3;j++) {
                if (!review_same_member(ai,bi,models[j])) differences|=4;
                if (!review_same_member(ai,bi,policy[j])) differences|=8;
            }
            if (!review_same_member(nj_get(ai,"image"),nj_get(bi,"image"),"max_pixels")) differences|=8;
        }
    } else {
        const char *policy[]={"engine","language","arithmetic","readout_sha256"};
        const char *views[]={"file_view","trace_witness","boundary_view"};
        for (int i=0;i<4;i++) if (!review_same_member(ae,be,policy[i])) differences|=8;
        for (int i=0;i<3;i++) if (!review_same_member(nj_get(ae,views[i]),nj_get(be,views[i]),"policy")) differences|=8;
    }
    return differences;
}

static int review_reference(FILE *out, const saved_review *r, const char *id, int ordinal, int complete) {
    fputc('{',out); json_field(out,"observation_id",id); fprintf(out,",\"ordinal\":%d",ordinal);
    if (complete) {
        if (write_member(out,"observation",r->row)) return 1;
    } else {
        const char *fields[]={"batch_id","base_commit","head_commit","fact"};
        for (int i=0;i<4;i++) if (write_member(out,fields[i],nj_get(r->evidence,fields[i]))) return 1;
        if (write_member(out,"checked_at",nj_get(r->row,"checked_at")) ||
            write_member(out,"summary",nj_get(r->review,"summary")) ||
            write_member(out,"visual_summary",nj_get(r->review,"visual_summary"))) return 1;
    }
    fputc('}',out); return ferror(out);
}

static void review_vote(FILE *out, const char *key, const saved_review *r, int index) {
    fprintf(out,",\"%s\":",key);
    if (index<0) fputs("null",out);
    else fprintf(out,"{\"file_index\":%d,\"verdict\":\"%s\"}",index,r->files[index].concern?"CONCERN":"CLEAN");
}

static int review_compare(FILE *out, const saved_review *before, const saved_review *after) {
    int left[2*JOV_BATCH_MAX_FILES], right[2*JOV_BATCH_MAX_FILES], differences[2*JOV_BATCH_MAX_FILES], count=0;
    float before_votes[2*JOV_BATCH_MAX_FILES], after_votes[2*JOV_BATCH_MAX_FILES], compatible[2*JOV_BATCH_MAX_FILES];
    for (int i=0;i<before->count;i++) {
        left[count]=i; right[count]=-1;
        for (int j=0;j<after->count;j++) if (!strcmp(before->files[i].path,after->files[j].path)) right[count]=j;
        count++;
    }
    for (int j=0;j<after->count;j++) {
        int found=0;
        for (int i=0;i<count;i++) if (right[i]==j) found=1;
        if (!found) { left[count]=-1; right[count++]=j; }
    }
    int same_fact=jov_fact_same(before->fact,after->fact);
    for (int i=0;i<count;i++) {
        before_votes[i]=left[i]<0?-1:before->files[left[i]].concern;
        after_votes[i]=right[i]<0?-1:after->files[right[i]].concern;
        differences[i]=left[i]<0 || right[i]<0 ? 0 : review_differences(&before->files[left[i]],&after->files[right[i]],same_fact);
        compatible[i]=differences[i]==0;
    }
    if (am_set_var_array("review_before_votes",before_votes,count) || am_set_var_array("review_after_votes",after_votes,count) ||
        am_set_var_array("review_compatible",compatible,count) || am_exec_file("aml/compare-reviews.aml")) return 1;
    const AM_List *states=am_get_var_list("review_transitions");
    int ncounts=0;
    const float *counts=am_get_var_array("review_transition_counts",&ncounts);
    if (!states || states->len!=count || !counts || ncounts!=7) return 1;
    const char *names[]={"concern_to_clean","clean_to_concern","unchanged_concern","unchanged_clean","first_review","not_reviewed_after","not_comparable"};
    const char *reasons[]={"review_kind_changed","rule_changed","model_changed","policy_changed"};
    int actual[7]={0};
    for (int i=0;i<count;i++) {
        int known=0;
        for (int j=0;j<7;j++) if (!strcmp(states->items[i]->data,names[j])) {actual[j]++;known=1;}
        if(!known)return 1;
    }
    for (int i=0;i<7;i++) if(!isfinite(counts[i]) || counts[i]!=actual[i])return 1;
    fputs(",\"summary\":{",out);
    for (int i=0;i<7;i++) { if(i)fputc(',',out); fprintf(out,"\"%s\":%.0f",names[i],counts[i]); }
    fputs("},\"files\":[",out);
    for (int i=0;i<count;i++) {
        const char *state=states->items[i]->data;
        if(i)fputc(',',out);
        fputc('{',out); json_field(out,"file",left[i]<0?after->files[right[i]].path:before->files[left[i]].path);
        fputc(',',out); json_field(out,"transition",state);
        review_vote(out,"before",before,left[i]); review_vote(out,"after",after,right[i]);
        fputs(",\"reasons\":[",out); int emitted=0;
        for (int j=0;j<4;j++) if (differences[i]&(1<<j)) { if(emitted++)fputc(',',out);json_string(out,reasons[j]); }
        fputs("]}",out);
    }
    fputc(']',out); return ferror(out);
}

int jov_pr_reviews(const char *directory, const char *scope, const char *number, const char *before_id, const char *after_id) {
    jov_pr pr={0}; int failed=1, writer=-1, comparing=before_id!=NULL;
    char *data=NULL; size_t size=0; FILE *out=NULL;
    saved_review before={0}, after={0}; AM_String *before_row=NULL, *after_row=NULL;
    if (repository_name(scope,pr.repository) || !valid_number(number,strlen(number)) ||
        (!!before_id!=!!after_id) || (comparing && (!review_id_valid(before_id) || !review_id_valid(after_id)))) return 1;
    strcpy(pr.number,number); am_init(); am_persistent_mode(1);
    if (journal(directory,&pr,0,&writer)) goto done;
    const AM_List *rows=am_get_var_list("observations"), *keys=am_get_var_list("keys");
    if (!rows || !keys || rows->len!=keys->len || rows->len>256) goto done;
    out=open_memstream(&data,&size); if(!out)goto done;
    fputs("{\"schema\":",out);json_string(out,comparing?"jovovich.mixed-review-comparison/1":"jovovich.mixed-review-index/1");
    fputc(',',out);json_field(out,"repository",pr.repository);fprintf(out,",\"number\":%s",pr.number);
    if (comparing) {
        int bi=-1,ai=-1;
        for(int i=0;i<keys->len;i++) {
            if(!strcmp(keys->items[i]->data,before_id)) {if(bi>=0)goto done;bi=i;}
            if(!strcmp(keys->items[i]->data,after_id)) {if(ai>=0)goto done;ai=i;}
        }
        if (bi<0 || ai<=bi || !(before_row=am_list_get(rows,bi)) || !(after_row=am_list_get(rows,ai)) ||
            saved_review_read(&before,before_row->data,before_id,&pr) || saved_review_read(&after,after_row->data,after_id,&pr)) goto done;
        fputs(",\"before\":",out);if(review_reference(out,&before,before_id,bi+1,1))goto done;
        fputs(",\"after\":",out);if(review_reference(out,&after,after_id,ai+1,1) || review_compare(out,&before,&after))goto done;
    } else {
        int count=0;fputs(",\"reviews\":[",out);
        for(int i=0;i<rows->len;i++) {
            const char *row=rows->items[i]->data, *end=report_json_end(row,0), *evidence=nj_get(row,"evidence");
            if (!end || *nj_ws(end) || review_evidence_identity(evidence,keys->items[i]->data)) goto done;
            for(int j=0;j<i;j++) if(!strcmp(keys->items[j]->data,keys->items[i]->data))goto done;
            if (!nj_get(evidence,"review")) continue;
            saved_review item={0};
            int bad=saved_review_read(&item,row,keys->items[i]->data,&pr);
            if(!bad) { if(count++)fputc(',',out);bad=review_reference(out,&item,keys->items[i]->data,i+1,0); }
            saved_review_free(&item); if(bad)goto done;
        }
        fputc(']',out);
    }
    fputs("}\n",out);
    failed=ferror(out); if(fclose(out))failed=1;out=NULL;
    if(!failed)failed=fwrite(data,1,size,stdout)!=size || fflush(stdout);
done:
    if(out)fclose(out);
    saved_review_free(&before);saved_review_free(&after);am_string_free(before_row);am_string_free(after_row);free(data);
    if(failed)fputs("Cannot compare or index mixed reviews: invalid selection or receipt\n",stderr);
    am_persistent_mode(0);return failed;
}
#endif
