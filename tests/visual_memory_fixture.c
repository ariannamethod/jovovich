#define _POSIX_C_SOURCE 200809L
#include "visual_memory.h"
#include "report_json.h"
#include "ariannamethod.h"
#include <stdio.h>

/* Offline journal tests supply a synthetic observation explicitly. The public
 * writer is the live vision CLI; it never accepts caller-supplied answers. */
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    size_t bytes=0;int bad=0,rc=1;
    char *input=report_json_row(stdin,&bytes,&bad,65536,131072);
    char *observation=report_json_row(stdin,&bytes,&bad,65536,131072),*receipt=NULL;
    am_init();am_persistent_mode(1);
    if(!bad && input && observation && !jov_visual_remember(argv[1],input,observation,&receipt))
        rc=puts(receipt)==EOF || fflush(stdout);
    free(input);free(observation);free(receipt);am_persistent_clear();am_persistent_mode(0);return rc;
}
