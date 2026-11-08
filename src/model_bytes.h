#ifndef JOV_MODEL_BYTES_H
#define JOV_MODEL_BYTES_H
#include "hash.h"
#include <fcntl.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static inline int jov_model_file_hash(const char *path, char out[65]) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 1;
    struct stat st;
    int rc = 1;
    if (fstat(fd, &st) == 0 && st.st_size > 0 && (uintmax_t)st.st_size <= SIZE_MAX) {
        size_t length = (size_t)st.st_size;
        void *data = mmap(NULL, length, PROT_READ, MAP_PRIVATE, fd, 0);
        if (data != MAP_FAILED) {
            rc = hash_bytes(data, length, out);
            munmap(data, length);
        }
    }
    close(fd);
    return rc;
}
#endif
