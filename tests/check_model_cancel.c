#define _POSIX_C_SOURCE 200809L
#include "hash.h"
#include <signal.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum { COPY, HASH, FILE_LIMIT };
static int phase=-1;
static volatile sig_atomic_t cancel_signal;

/* The copy has written its first real chunk. Cancel the worker's group while
 * bytes still remain, as a terminal or job controller would. */
static ssize_t interruptible_write(int fd,const void *p,size_t n) {
    ssize_t wrote=write(fd,p,n);
    if (phase==COPY && wrote>1) kill(0,cancel_signal);
    return wrote;
}

static void cancel_hash(int sig) {
    (void)sig;
    kill(0,cancel_signal);
}

static int interruptible_hash(const void *p,size_t n,char sha[65]) {
    if (phase!=HASH) return hash_bytes(p,n,sha);
    struct sigaction action={0};
    action.sa_handler=cancel_hash;
    sigemptyset(&action.sa_mask);
    /* This timer only advances while the worker executes in user space. Allow
     * several milliseconds of the actual SHA-256 computation before the signal. */
    struct itimerval timer={.it_value={.tv_usec=3000}};
    if (sigaction(SIGVTALRM,&action,NULL) || setitimer(ITIMER_VIRTUAL,&timer,NULL)) _exit(91);
    int rc=hash_bytes(p,n,sha);
    (void)rc;
    _exit(92);
}

#define write interruptible_write
#define hash_bytes interruptible_hash
#include "model_bytes.h"
#undef hash_bytes
#undef write

static int cancelled(int use_fds,int stage,int sig) {
    if (mkdir("scratch",0700)) return 1;
    pid_t worker=fork();
    if (worker<0) return 1;
    if (!worker) {
        struct sigaction normal={0};
        normal.sa_handler=SIG_DFL;
        sigemptyset(&normal.sa_mask);
        sigset_t unblock;
        sigemptyset(&unblock);
        sigaddset(&unblock,sig);sigaddset(&unblock,SIGVTALRM);
        if (setpgid(0,0) || (sig!=SIGKILL && sigaction(sig,&normal,NULL)) ||
            sigprocmask(SIG_UNBLOCK,&unblock,NULL) || setenv("TMPDIR","scratch",1)) _exit(93);
        if (stage==FILE_LIMIT) {
            const struct rlimit lim={65536,65536};
            if (setrlimit(RLIMIT_FSIZE,&lim)) _exit(94);
        }
        jov_model_files s;
        if (jov_model_files_begin(&s,use_fds)) _exit(95);
        phase=stage;cancel_signal=sig;
        char hash[65];
        jov_model_capture(&s,JOV_WEIGHTS,"source",
            "0000000000000000000000000000000000000000000000000000000000000000",hash);
        _exit(96);
    }
    int status;
    while (waitpid(worker,&status,0)<0) if (errno!=EINTR) return 1;
    if (!WIFSIGNALED(status) || WTERMSIG(status)!=sig) {
        fprintf(stderr,"worker stage %d, signal %d: wait status %d\n",stage,sig,status);
        return 1;
    }
    /* A named fallback's detached guard is scheduled separately from waitpid. */
    const struct timespec delay={.tv_nsec=10000000};
    for (int i=0;i<300;i++) {
        if (!rmdir("scratch")) return 0;
        if (errno!=ENOTEMPTY && errno!=EEXIST) break;
        nanosleep(&delay,NULL);
    }
    fprintf(stderr,"snapshot left after stage %d, signal %d, fd paths %d\n",stage,sig,use_fds);
    return 1;
}

int main(void) {
    char dir[]="/tmp/jov-cancel-test-XXXXXX";
    int cwd=open(".",O_RDONLY|O_DIRECTORY);
    if (cwd<0 || !mkdtemp(dir) || chdir(dir)) return 1;
    int src=open("source",O_CREAT|O_WRONLY|O_EXCL,0600);
    if (src<0 || ftruncate(src,16*1024*1024) || close(src)) return 1;
    const int signals[]={SIGINT,SIGTERM,SIGKILL};
    for (int fds=0;fds<=1;fds++) {
        for (int stage=COPY;stage<=HASH;stage++)
            for (size_t i=0;i<sizeof(signals)/sizeof(signals[0]);i++)
                if (cancelled(fds,stage,signals[i])) return 1;
        if (cancelled(fds,FILE_LIMIT,SIGXFSZ)) return 1;
    }
    if (unlink("source") || fchdir(cwd) || close(cwd) || rmdir(dir)) return 1;
    puts("snapshot cleanup: interrupted copy and hash, group INT/TERM/KILL, and 64 KiB file limit verified");
    return 0;
}
