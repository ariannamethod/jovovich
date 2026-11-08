/* Validate the original bytes before jq decodes a receipt. Use the same
 * JSON grammar, key uniqueness and UTF-8 checks as the native reviewer. */
#include "report_json.h"

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    for (int i = 1; i < argc; ++i) {
        char *bytes = nj_load(argv[i], NULL);
        if (!bytes) return 1;
        const char *p = nj_ws(bytes);
        int valid = *p != 0;
        while (valid && *p) {
            const char *end = *p == '{' ? report_json_end(p, 0) : NULL;
            if (!end) { valid = 0; break; }
            p = nj_ws(end);
            if (*p && p == end) valid = 0;
        }
        free(bytes);
        if (!valid) {
            fprintf(stderr, "%s: invalid JSON receipt or duplicate key\n", argv[i]);
            return 1;
        }
    }
    return 0;
}
