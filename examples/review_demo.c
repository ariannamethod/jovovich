#include "review.h"
#include "review_fixtures.h"

#include <locale.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    int json = argc > 1 && strcmp(argv[1], "--json") == 0;
    int first = json ? 2 : 1;
    const char *id = argc > first ? argv[first] : reviews[0].id;
    if (argc > first + 1) {
        fputs("Usage: review-demo [--json] [case-id|all]\n", stderr);
        return 2;
    }
    /* JSON uses a dot decimal separator regardless of the environment. */
    setlocale(LC_NUMERIC, "C");
    int found = 0;
    for (size_t i = 0; i < sizeof(reviews) / sizeof(reviews[0]); ++i) {
        if (strcmp(id, "all") && strcmp(id, reviews[i].id)) continue;
        if (found && !json) fputs("\n---\n\n", stdout);
        int status = json ? jov_review_json(stdout, &reviews[i]) :
                            jov_review_markdown(stdout, &reviews[i]);
        if (status != JOV_OK) {
            fprintf(stderr, "Review output failed: %s (error %d)\n", reviews[i].id, status);
            return status;
        }
        found = 1;
    }
    if (!found) {
        fprintf(stderr, "Unknown review case: %s\n", id);
        return 2;
    }
    return fflush(stdout) == 0 ? 0 : JOV_IO_ERROR;
}
