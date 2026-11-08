#ifndef JOV_MODEL_BYTES_H
#define JOV_MODEL_BYTES_H
#include "hash.h"
#include "gguf.h"
#include "examples/bpe.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

/* BPE reopens the tokenizer for every GGUF key. Each open must see the same
 * snapshot, starting at byte zero. Both inputs are copied from regular files
 * into private storage on the trusted TMPDIR filesystem. */
enum { JOV_WEIGHTS, JOV_TOKENIZER, JOV_MODEL_PARTS };
static const char *const jov_model_names[JOV_MODEL_PARTS]={"weights","tokenizer"};
typedef struct { int writer,reader; char path[64]; } jov_model_part;
typedef struct {
    jov_model_part part[JOV_MODEL_PARTS];
    int dir,lease;
    pid_t guard;
    char *name;
} jov_model_files;

static inline int jov_model_unlink(const jov_model_files *s) {
    int bad=0;
    for (int i=0;i<JOV_MODEL_PARTS;i++)
        if (unlinkat(s->dir,jov_model_names[i],0) && errno!=ENOENT) bad=1;
    if (rmdir(s->name) && errno!=ENOENT) bad=1;
    return bad;
}

static inline void jov_model_close_parts(jov_model_files *s) {
    for (int i=0;i<JOV_MODEL_PARTS;i++) {
        if (s->part[i].reader>=0) close(s->part[i].reader);
        if (s->part[i].writer>=0) close(s->part[i].writer);
    }
}

/* Detect independent file positions, not merely the existence of /dev/fd.
 * On systems where opening the alias is dup(2), BPE needs ordinary named opens. */
static inline int jov_model_fd_path(jov_model_part *p) {
    const char *prefixes[]={"/proc/self/fd","/dev/fd"};
    for (size_t i=0;i<sizeof(prefixes)/sizeof(prefixes[0]);i++) {
        snprintf(p->path,sizeof(p->path),"%s/%d",prefixes[i],p->reader);
        int test=open(p->path,O_RDONLY|O_CLOEXEC);
        if (test<0) continue;
        struct stat a,b;
        int ok=!fstat(p->reader,&a) && !fstat(test,&b) &&
            a.st_dev==b.st_dev && a.st_ino==b.st_ino &&
            lseek(test,1,SEEK_SET)==1 && lseek(p->reader,0,SEEK_CUR)==0;
        close(test);
        if (lseek(p->reader,0,SEEK_SET)<0) return 0;
        if (ok) return 1;
    }
    return 0;
}

static inline ssize_t jov_model_read_byte(int fd,char *byte) {
    ssize_t got;
    do { got=read(fd,byte,1); } while (got<0 && errno==EINTR);
    return got;
}

/* A detached cleanup process owns the named fallback's lifetime. It waits for
 * EOF on its parent's socket, including when a terminal signal or SIGKILL ends
 * the entire foreground group. The parent waits for readiness before copying. */
static inline int jov_model_start_guard(jov_model_files *s) {
    int pair[2];
    if (socketpair(AF_UNIX,SOCK_STREAM,0,pair)) return 1;
    if (fcntl(pair[0],F_SETFD,FD_CLOEXEC) || fcntl(pair[1],F_SETFD,FD_CLOEXEC)) {
        close(pair[0]); close(pair[1]); return 1;
    }
    pid_t pid=fork();
    if (pid==0) {
        close(pair[0]);
        jov_model_close_parts(s);
        struct sigaction ignore={0};
        ignore.sa_handler=SIG_IGN;
        sigemptyset(&ignore.sa_mask);
        char ready='R';
        if (setsid()>=0 && !sigaction(SIGPIPE,&ignore,NULL) && write(pair[1],&ready,1)==1) {
            while (jov_model_read_byte(pair[1],&ready)>0) {}
        }
        _exit(jov_model_unlink(s));
    }
    close(pair[1]);
    if (pid<0) { close(pair[0]); return 1; }
    s->guard=pid; s->lease=pair[0];
    char ready;
    return jov_model_read_byte(s->lease,&ready)!=1 || ready!='R';
}

static inline int jov_model_files_begin(jov_model_files *s,int try_fd_paths) {
    *s=(jov_model_files){.dir=-1,.lease=-1};
    for (int i=0;i<JOV_MODEL_PARTS;i++) s->part[i].writer=s->part[i].reader=-1;
    const char *tmp=getenv("TMPDIR");
    if (!tmp || !*tmp) tmp="/tmp";
    size_t size=strlen(tmp)+sizeof("/jov-model-XXXXXX");
    char *name=malloc(size);
    if (!name) return 1;
    snprintf(name,size,"%s/jov-model-XXXXXX",tmp);
    if (!mkdtemp(name)) { free(name); return 1; }
    s->name=name;
    s->dir=open(name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if (s->dir<0) return 1;
    for (int i=0;i<JOV_MODEL_PARTS;i++) {
        jov_model_part *p=&s->part[i];
        p->writer=openat(s->dir,jov_model_names[i],O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC,0400);
        if (p->writer<0) return 1;
        p->reader=openat(s->dir,jov_model_names[i],O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
        if (p->reader<0) return 1;
        if (try_fd_paths && !jov_model_fd_path(p)) try_fd_paths=0;
    }
    if (!try_fd_paths) return jov_model_start_guard(s);
    /* Both files are still empty. Unlink now: a killed copy, hash or mapped
     * inference leaves no named file, and the kernel releases its storage. */
    if (jov_model_unlink(s)) return 1;
    free(s->name); s->name=NULL;
    close(s->dir); s->dir=-1;
    return 0;
}

static inline void jov_model_files_end(jov_model_files *s) {
    jov_model_close_parts(s);
    if (s->guard>0) {
        close(s->lease);
        while (waitpid(s->guard,NULL,0)<0 && errno==EINTR) {}
    }
    if (s->name) {
        if (s->dir>=0) jov_model_unlink(s); else rmdir(s->name);
        free(s->name);
    }
    if (s->dir>=0) close(s->dir);
}

/* Do not mmap the caller's mutable inode: truncation during hashing can SIGBUS. */
static inline int jov_model_capture(jov_model_files *s,int part,const char *path,
                                    const char *expected,char hash[65]) {
    if (!expected || strlen(expected)!=64) return 1;
    int src=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC), dst=s->part[part].writer,rc=1;
    struct stat st;
    if (src<0 || fstat(src,&st) || !S_ISREG(st.st_mode) || st.st_size<=0 ||
        (uintmax_t)st.st_size>SIZE_MAX) goto done;
    size_t length=(size_t)st.st_size, left=length;
    unsigned char buf[65536];
    while (left) {
        ssize_t got=read(src,buf,left<sizeof(buf)?left:sizeof(buf));
        if (got<0 && errno==EINTR) continue;
        if (got<=0) goto done;
        for (ssize_t offset=0;offset<got;) {
            ssize_t w=write(dst,buf+offset,(size_t)(got-offset));
            if (w<0 && errno==EINTR) continue;
            if (w<=0) goto done;
            offset+=w;
        }
        left-=(size_t)got;
    }
    char extra;
    if (jov_model_read_byte(src,&extra)!=0) goto done;
    void *bytes=mmap(NULL,length,PROT_READ,MAP_PRIVATE,s->part[part].reader,0);
    if (bytes==MAP_FAILED) goto done;
    rc=hash_bytes(bytes,length,hash) || strcmp(hash,expected)!=0;
    munmap(bytes,length);
done:
    if (close(dst)) rc=1;
    s->part[part].writer=-1;
    if (src>=0) close(src);
    return rc;
}

static inline int jov_model_load(jov_model_files *s,gguf_file **gg,bpe_tokenizer **tok) {
    if (!s->name) {
        *gg=gguf_open(s->part[JOV_WEIGHTS].path);
        if (*gg) *tok=bpe_load(s->part[JOV_TOKENIZER].path);
        return !*gg || !*tok;
    }
    /* These synchronous start-up calls precede inference. fchdir pins the
     * private directory for all of BPE's ordinary path opens. */
    int cwd=open(".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if (cwd<0) return 1;
    int rc=fchdir(s->dir);
    if (!rc) {
        *gg=gguf_open(jov_model_names[JOV_WEIGHTS]);
        if (*gg) *tok=bpe_load(jov_model_names[JOV_TOKENIZER]);
        rc=fchdir(cwd) || !*gg || !*tok;
    }
    close(cwd);
    return rc;
}

static inline int jov_model_verified_pair(const char *weights,const char *tokenizer,
                                          const char *want_weights,const char *want_tokenizer,
                                          char wh[65],char th[65],gguf_file **gg,bpe_tokenizer **tok) {
    jov_model_files s;
    *gg=NULL; *tok=NULL;
    int rc=jov_model_files_begin(&s,1) ||
        jov_model_capture(&s,JOV_WEIGHTS,weights,want_weights,wh) ||
        jov_model_capture(&s,JOV_TOKENIZER,tokenizer,want_tokenizer,th) ||
        jov_model_load(&s,gg,tok);
    jov_model_files_end(&s);
    if (rc) { gguf_close(*gg); bpe_free(*tok); *gg=NULL; *tok=NULL; }
    return rc;
}
#endif
