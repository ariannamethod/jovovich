#include "review.h"
#include "json.h"

#include <math.h>
#include <string.h>

static int present(const char *s) { return s && *s; }

static int hash_string(const char *s) {
    if (!s || strlen(s) != 64) return 0;
    return strspn(s, "0123456789abcdef") == 64;
}

static int git_oid(const char *s) {
    if(!s || (strlen(s)!=40 && strlen(s)!=64))return 0;
    return strspn(s,"0123456789abcdef")==strlen(s);
}

int jov_source_validate(const jov_source *s) {
    return s && git_oid(s->base) && git_oid(s->head) && git_oid(s->rules_blob) &&
        strlen(s->base)==strlen(s->head) && strlen(s->base)==strlen(s->rules_blob) &&
        present(s->rules_path) && hash_string(s->rules_sha256) && hash_string(s->diff_sha256) &&
        s->first_line>=1 && s->last_line>=s->first_line ? JOV_OK : JOV_INVALID;
}

int jov_source_json(FILE *f,const jov_source *s) {
    if(!f || jov_source_validate(s))return JOV_INVALID;
    fputc('{',f);json_field(f,"kind","git");fputc(',',f);json_field(f,"base_commit",s->base);
    fputc(',',f);json_field(f,"head_commit",s->head);fputc(',',f);json_field(f,"rules_path",s->rules_path);
    fputc(',',f);json_field(f,"rules_blob",s->rules_blob);fputc(',',f);json_field(f,"rules_sha256",s->rules_sha256);
    fputc(',',f);json_field(f,"diff_sha256",s->diff_sha256);
    fprintf(f,",\"rule_first_line\":%d,\"rule_last_line\":%d}",s->first_line,s->last_line);
    return ferror(f)?JOV_IO_ERROR:JOV_OK;
}

int jov_review_validate(const jov_review *r) {
    if (!r || !present(r->id) || !present(r->model) || !present(r->revision) ||
        !present(r->question) || !present(r->file) || !present(r->context) ||
        !present(r->rule_excerpt) || !present(r->change_excerpt)) return JOV_INVALID;
    if (!isfinite(r->concern) || !isfinite(r->clean) ||
        r->concern < 0 || r->concern > 1 || r->clean < 0 || r->clean > 1 ||
        fabs(r->concern + r->clean - 1.0) > 1e-6) return JOV_INVALID;
    if (!strstr(r->context, r->file) || !strstr(r->context, r->rule_excerpt) ||
        !strstr(r->context, r->change_excerpt)) return JOV_INVALID;
    if(r->source && jov_source_validate(r->source))return JOV_INVALID;
    if (r->execution) {
        const jov_execution *e = r->execution;
        if (!hash_string(e->input_sha256) || !hash_string(e->weights_sha256) ||
            !hash_string(e->tokenizer_sha256) || (e->readout_sha256 && !hash_string(e->readout_sha256)) || e->second < 0 || e->second >= 86400 ||
            e->millisecond < 0 || e->millisecond >= 1000) return JOV_INVALID;
    }
    return JOV_OK;
}

const char *jov_review_verdict(const jov_review *r) {
    if (jov_review_validate(r) != JOV_OK) return NULL;
    return r->concern >= r->clean ? "CONCERN" : "CLEAN";
}

int jov_review_json(FILE *out, const jov_review *r) {
    if (!out || jov_review_validate(r) != JOV_OK) return JOV_INVALID;
    fputs("{\"schema_version\":1,", out);
    json_field(out, "id", r->id);
    fputs(",\"model\":{", out);
    json_field(out, "id", r->model);
    fputc(',', out);
    json_field(out, "revision", r->revision);
    fputs("},", out);
    json_field(out, "question", r->question);
    fputs(",\"scope\":{", out);
    json_field(out, "file", r->file);
    fputs("},\"input\":{", out);
    json_field(out, "context", r->context);
    fputc(',', out);
    json_field(out, "rule_excerpt", r->rule_excerpt);
    fputc(',', out);
    json_field(out, "change_excerpt", r->change_excerpt);
    fputs("},\"choice\":{", out);
    json_field(out, "verdict", jov_review_verdict(r));
    fprintf(out, ",\"probabilities\":{\"CONCERN\":%.17g,\"CLEAN\":%.17g}}",
            r->concern, r->clean);
    if(r->source){fputs(",\"source\":",out);jov_source_json(out,r->source);}
    if (r->execution) {
        const jov_execution *e = r->execution;
        fputs(",\"execution\":{\"engine\":\"NoTorch\",\"language\":\"AML\",\"arithmetic\":\"float32\",", out);
        json_field(out, "input_sha256", e->input_sha256); fputc(',', out);
        json_field(out, "weights_sha256", e->weights_sha256); fputc(',', out);
        json_field(out, "tokenizer_sha256", e->tokenizer_sha256);
        if(e->readout_sha256){fputc(',',out);json_field(out,"readout_sha256",e->readout_sha256);}
        fprintf(out, ",\"reviewed_at\":{\"schema\":\"janus.instant/1\",\"time_scale\":\"posix\",\"unix_day\":%d,\"second\":%d,\"millisecond\":%d}}",
                e->unix_day, e->second, e->millisecond);
    }
    fputs("}\n", out);
    return ferror(out) ? JOV_IO_ERROR : JOV_OK;
}

/* Keep supplied text literal in Markdown, including HTML and Markdown syntax. */
static void markdown_char(FILE *out, unsigned char c) {
    if (c == '&') fputs("&amp;", out);
    else if (c == '<') fputs("&lt;", out);
    else if (c == '>') fputs("&gt;", out);
    else {
        if (strchr("\\`*_{}[]()#+-.!|~", c)) fputc('\\', out);
        fputc(c, out);
    }
}

static void markdown_text(FILE *out, const char *s, int quote) {
    if (quote) fputs("> ", out);
    for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
        if (*p == '\n') {
            fputs(quote ? "\n>" : " ", out);
            if (quote && p[1] && p[1] != '\n' && p[1] != '\r') fputc(' ', out);
        }
        else if (*p != '\r') markdown_char(out, *p);
    }
}

static void fence(FILE *out, size_t length) {
    for (size_t i = 0; i < length; ++i) fputc('`', out);
}

static void code_block(FILE *out, const char *s) {
    size_t longest = 0, run = 0;
    for (const char *p = s; *p; ++p) {
        run = *p == '`' ? run + 1 : 0;
        if (run > longest) longest = run;
    }
    size_t length = longest >= 3 ? longest + 1 : 3;
    fence(out, length);
    fputs("text\n", out);
    fputs(s, out);
    if (s[strlen(s) - 1] != '\n') fputc('\n', out);
    fence(out, length);
    fputc('\n', out);
}

int jov_review_markdown(FILE *out, const jov_review *r) {
    if (!out || jov_review_validate(r) != JOV_OK) return JOV_INVALID;
    fprintf(out, "**JOVOVICH · %s**\n\n**Reviewed file:** ", jov_review_verdict(r));
    markdown_text(out, r->file, 0);
    if(r->source) {
        const jov_source *s=r->source;
        fprintf(out,"\n\n**Git scope:** `%s` → `%s`\n\n**Rules source:** ",s->base,s->head);
        markdown_text(out,s->rules_path,0);
        fprintf(out," (lines %d–%d)",s->first_line,s->last_line);
    }
    fputs("\n\n**Rule supplied for review**\n\n", out);
    markdown_text(out, r->rule_excerpt, 1);
    fputs("\n\n**Change under review**\n\n", out);
    code_block(out, r->change_excerpt);
    fprintf(out, "\n**Choice probabilities:** CONCERN %.1f%% · CLEAN %.1f%%\n",
            100 * r->concern, 100 * r->clean);
    return ferror(out) ? JOV_IO_ERROR : JOV_OK;
}
