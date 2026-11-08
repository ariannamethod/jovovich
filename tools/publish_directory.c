/* Publish a finished directory in one operation without replacing an existing entry. */
#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#ifdef __linux__
#include <linux/fs.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

int main(int argc, char **argv) {
    if (argc != 3) return 2;
#if defined(__APPLE__)
    int result = renamex_np(argv[1], argv[2], RENAME_EXCL);
#elif defined(__linux__) && defined(SYS_renameat2)
    int result = (int)syscall(SYS_renameat2, AT_FDCWD, argv[1],
                              AT_FDCWD, argv[2], RENAME_NOREPLACE);
#else
    errno = ENOTSUP;
    int result = -1;
#endif
    if (result < 0) {
        perror(argv[2]);
        return 1;
    }
    return 0;
}
