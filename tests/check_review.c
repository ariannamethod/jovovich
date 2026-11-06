#include "review.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static jov_review sample(void) {
    return (jov_review){
        .id = "escaping", .model = "fixture", .revision = "test",
        .question = "Does the change meet the rule?",
        .file = "a*[x]<b>.c",
        .context = "a*[x]<b>.c\nRule: keep \"quoted\" \\ paths\tand controls\x01.\n"
                   "Change: ```\n<script>\n`\n````\n",
        .rule_excerpt = "keep \"quoted\" \\ paths\tand controls\x01.",
        .change_excerpt = "```\n<script>\n`\n````\n",
        .concern = .75, .clean = .25
    };
}

static void invalid(jov_review r) {
    FILE *f = tmpfile();
    assert(f);
    assert(jov_review_verdict(&r) == NULL);
    assert(jov_review_json(f, &r) == JOV_INVALID);
    assert(jov_review_markdown(f, &r) == JOV_INVALID);
    assert(ftell(f) == 0);
    assert(fclose(f) == 0);
}

int main(void) {
    jov_review r = sample();
    assert(jov_review_validate(NULL) == JOV_INVALID);
    assert(jov_review_validate(&r) == JOV_OK);
    assert(jov_review_json(NULL, &r) == JOV_INVALID);
    assert(!strcmp(jov_review_verdict(&r), "CONCERN"));
    r.concern = .49; r.clean = .51;
    assert(!strcmp(jov_review_verdict(&r), "CLEAN"));
    r.concern = r.clean = .5;
    assert(!strcmp(jov_review_verdict(&r), "CONCERN"));
    r = sample(); r.concern = NAN; invalid(r);
    r = sample(); r.clean = INFINITY; invalid(r);
    r = sample(); r.concern = -.1; r.clean = 1.1; invalid(r);
    r = sample(); r.clean = .9; invalid(r);
    r = sample(); r.change_excerpt = "invented code"; invalid(r);
    r = sample(); r.rule_excerpt = "invented rule"; invalid(r);
    r = sample(); r.file = "elsewhere.c"; invalid(r);
    r = sample(); r.context = NULL; invalid(r);
    r = sample(); r.model = ""; invalid(r);

    r = sample();
    FILE *f = fopen("build/escaping.json", "w");
    assert(f && jov_review_json(f, &r) == JOV_OK && fclose(f) == 0);
    f = fopen("build/escaping.md", "w");
    assert(f && jov_review_markdown(f, &r) == JOV_OK && fclose(f) == 0);
    puts("Invalid choices rejected; near ties, exact ties and escaping exercised.");
    return 0;
}
