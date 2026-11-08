#ifndef JOVOVICH_PROCESS_H
#define JOVOVICH_PROCESS_H
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

/* Capture bounded stdout. The child receives argv literally and cannot consume
 * the review stream on stdin. A normal nonzero exit is reported separately. */
static inline char *jov_command(const char *const argv[], size_t limit, size_t *length, int *code) {
    int output[2];
    if (pipe(output)) return NULL;
    pid_t pid = fork();
    if (pid == 0) {
        close(output[0]);
        int input = open("/dev/null", O_RDONLY);
        if (input < 0 || dup2(input, STDIN_FILENO) < 0 || dup2(output[1], STDOUT_FILENO) < 0) _exit(126);
        if (input != STDIN_FILENO) close(input);
        if (output[1] != STDOUT_FILENO) close(output[1]);
        execvp(argv[0], (char *const *)argv);
        _exit(127);
    }
    close(output[1]);
    if (pid < 0) { close(output[0]); return NULL; }
    char *data = malloc(limit + 1);
    size_t n = 0;
    while (data && n <= limit) {
        ssize_t got = read(output[0], data + n, limit + 1 - n);
        if (got < 0 && errno == EINTR) continue;
        if (got < 0) { free(data); data = NULL; break; }
        if (!got) break;
        n += (size_t)got;
    }
    close(output[0]);
    if (!data || n > limit) kill(pid, SIGKILL);
    int status;
    pid_t waited;
    do { waited = waitpid(pid, &status, 0); } while (waited < 0 && errno == EINTR);
    if (!data || n > limit || waited < 0 || !WIFEXITED(status)) { free(data); return NULL; }
    *code = WEXITSTATUS(status);
    *length = n;
    data[n] = 0;
    return data;
}
#endif
