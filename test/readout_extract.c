#define READOUT_MAIN readout_extractor_main
#include "../training/extract_readout.c"
#undef READOUT_MAIN
#include <assert.h>
#include <sys/wait.h>

static void write_text(FILE *f,const char *s) { readout_u32(f,(uint32_t)strlen(s));assert(fwrite(s,1,strlen(s),f)==strlen(s)); }
static void invalid_input(const char *path) {
    pid_t pid=fork();assert(pid>=0);
    if(!pid){int n;assert(freopen("/dev/null","w",stderr));readout_row *r=readout_data(path,&n);readout_free(r,n);_exit(0);}
    int status;assert(waitpid(pid,&status,0)==pid);assert(WIFEXITED(status)&&WEXITSTATUS(status)==1);
}
int main(void) {
    char path[]="/tmp/jovovich-readout-unit-XXXXXX";int fd=mkstemp(path);assert(fd>=0);
    FILE *f=fdopen(fd,"wb");assert(f);assert(fwrite("JVRO1\0\0\0",1,8,f)==8);readout_u32(f,1);
    write_text(f,"system");write_text(f,"user prompt");assert(!fclose(f));
    int n;readout_row *rows=readout_data(path,&n);assert(n==1&&!strcmp(rows[0].system,"system")&&!strcmp(rows[0].user,"user prompt"));readout_free(rows,n);
    f=fopen(path,"ab");assert(f);fputc(0,f);fclose(f);invalid_input(path);
    f=fopen(path,"wb");assert(f);fwrite("JVDS\1\0\0\0",1,8,f);fclose(f);invalid_input(path);
    f=fopen(path,"wb");assert(f);fwrite("JVRO1\0\0\0",1,8,f);readout_u32(f,1);readout_u32(f,4);fwrite("x\0yz",1,4,f);fclose(f);invalid_input(path);
    f=fopen(path,"wb");assert(f);fwrite("JVRO1\0\0\0",1,8,f);readout_u32(f,1);write_text(f,"");write_text(f,"user");fclose(f);invalid_input(path);unlink(path);
    float residual[]={10,11,20,21,30,31},out[]={-1,-1};readout_capture c={4,9,0,out,2};
    assert(readout_hook(&c,3,8,3,2,residual)==NT_OK&&c.seen==0);
    assert(readout_hook(&c,4,11,3,2,residual)==NT_OK&&c.seen==0);
    assert(readout_hook(&c,4,8,3,3,residual)==NT_E_ARG&&c.seen==0);
    assert(readout_hook(&c,4,8,3,2,residual)==NT_OK&&c.seen==1&&out[0]==20&&out[1]==21);
    assert(readout_hook(&c,4,8,3,2,residual)==NT_E_ARG);
    puts("readout extraction: prompt-only parsing, malformed/gold input rejection, unique causal hook position passed");return 0;
}
