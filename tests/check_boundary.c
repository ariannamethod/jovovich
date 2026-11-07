#include "boundary.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    const char *ops[]={"<","<=",">",">="};
    const char *spelling[]={"return x %s %d;","return !(x %s %d);","return %d %s x;","return !(%d %s x);"};
    const int map[][4]={{0,1,2,3},{3,2,1,0},{2,3,0,1},{1,0,3,2}};
    char code[JOV_BOUNDARY_CODE_SIZE],body[100],source[256],expected[256];
    for(int op=0;op<4;op++)for(int x=-8;x<=8;x++)for(int form=0;form<4;form++) {
        const char *symbol=ops[map[form][op]];
        if(form<2)snprintf(body,sizeof(body),spelling[form],symbol,x);
        else snprintf(body,sizeof(body),spelling[form],x,symbol);
        snprintf(source,sizeof(source),"int yes(int x) { %s }",body);
        snprintf(expected,sizeof(expected),"int yes(int x) { return x %s %d; }",ops[op],x);
        assert(jov_boundary_code(source,code)==1 && !strcmp(code,expected));
        assert(jov_boundary_code(expected,code)==1 && !strcmp(code,expected));
    }
    const char *unsupported[]={"int f(double x) { return !(x >= 0); }","int f(unsigned x) { return x < -1; }",
        "int f(int x) { return !(x++ >= 0); }","int f(int x) { return !(x >= fn()); }",
        "int f(int x) { return x < 010; }","int f(int x) { return y < 0; }",
        "int f(int x) { return x < 0u; }","int f(int x) { return x < 2147483648; }",
        "int f(int x) { return 0 < x && x < 3; }","int f(int x) { return !x < 1; }",
        "int f(int x) { return x < = 0; }","int f(int x) { return x < 0; } /* note */"};
    for(size_t i=0;i<sizeof(unsupported)/sizeof(*unsupported);i++)assert(!jov_boundary_code(unsupported[i],code));
    const char *raw="int f(int x) { return 0 > x; }",*normal="int f(int x) { return x < 0; }";
    char ctx[1024],*view=NULL;
    snprintf(ctx,sizeof(ctx),"rule\n```c\n%s\n```\nobservation",raw);
    assert(jov_boundary_context(ctx,"rule",raw,code,&view)==1 && strstr(view,normal) && strstr(view,"\n```\nobservation"));
    free(view);
    assert(!jov_boundary_context(ctx,raw,raw,code,&view) && !view);
    snprintf(ctx,sizeof(ctx),"rule mentions %s\n```c\n%s\n```",raw,raw);
    assert(!jov_boundary_context(ctx,"rule",raw,code,&view) && !view);
    char diff[512];snprintf(diff,sizeof(diff),"diff --git a/f.c b/f.c\nnew file mode 100644\n--- /dev/null\n+++ b/f.c\n@@ -0,0 +1 @@\n+%s\n",raw);
    snprintf(ctx,sizeof(ctx),"rule\n%s",diff);
    assert(jov_boundary_context(ctx,"rule",diff,code,&view)==1 && strstr(view,"@@ -0,0 +1 @@\n+int f(int x) { return x < 0; }\n"));
    free(view);
    const char *headers="diff --git a/f.c b/f.c\nnew file mode 100644\nindex 0000000..";
    char *other=NULL,alternate[512];
    snprintf(alternate,sizeof(alternate),"%sabcdef3\n--- /dev/null\n+++ b/f.c\n@@ -0,0 +1 @@\n+%s\n",headers,raw);
    snprintf(ctx,sizeof(ctx),"rule\n%s",alternate);
    assert(jov_boundary_context(ctx,"rule",alternate,code,&view)==1 && !strstr(view,"index "));
    snprintf(alternate,sizeof(alternate),"%sabad1d1\n--- /dev/null\n+++ b/f.c\n@@ -0,0 +1 @@\n+%s\n",headers,normal);
    snprintf(ctx,sizeof(ctx),"rule\n%s",alternate);
    assert(jov_boundary_context(ctx,"rule",alternate,code,&other)==1 && !strcmp(view,other));
    free(view);free(other);
    strcat(diff,"+int y;\n");snprintf(ctx,sizeof(ctx),"rule\n%s",diff);
    assert(!jov_boundary_context(ctx,"rule",diff,code,&view) && !view);
    puts("Verified 272 comparison rewrites, idempotence, unsupported syntax and exact evidence spans");
}
