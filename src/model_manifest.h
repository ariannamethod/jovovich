#ifndef JOVOVICH_MODEL_MANIFEST_H
#define JOVOVICH_MODEL_MANIFEST_H
#include <string.h>

/* The optional leading profile selects the manifest for both inference and
 * offline verification. Existing invocations use the released checkpoint. */
static inline const char *jov_manifest_option(int *argc, char **argv) {
    const char *original = "models/onejev-0.8b.json";
    if (*argc < 2 || strcmp(argv[1], "--model")) return original;
    if (*argc < 3) return NULL;
    const char *path = original;
    if (!strcmp(argv[2], "onejev1.6")) path = "models/onejev1.6-0.8b.json";
    else if (strcmp(argv[2], "onejev")) return NULL;
    memmove(argv + 1, argv + 3, (size_t)(*argc - 2) * sizeof(*argv));
    *argc -= 2;
    return path;
}
#endif
