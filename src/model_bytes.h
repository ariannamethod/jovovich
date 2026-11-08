#ifndef JOV_MODEL_BYTES_H
#define JOV_MODEL_BYTES_H
#include "hash.h"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static inline int jov_model_file_hash(const char *path, char out[65]) {
    int fd=open(path,O_RDONLY);struct stat st;int rc=1;
    if(fd>=0 && !fstat(fd,&st) && st.st_size>0) {
        void *p=mmap(NULL,(size_t)st.st_size,PROT_READ,MAP_PRIVATE,fd,0);
        if(p!=MAP_FAILED){rc=hash_bytes(p,(size_t)st.st_size,out);munmap(p,(size_t)st.st_size);}
    }
    if(fd>=0)close(fd);
    return rc;
}
#endif
