#include "boundary.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void spaces(const char **p) {
    *p+=strspn(*p," \t\r\n\f\v");
}
static int take(const char **p,const char *token) {
    spaces(p);
    size_t len=strlen(token);
    if(strncmp(*p,token,len))return 0;
    *p+=len;return 1;
}
static int ident_char(char c) {
    return (c>='a' && c<='z') || (c>='A' && c<='Z') || c=='_' || (c>='0' && c<='9');
}
static int word(const char **p,const char *w) {
    const char *s=*p;
    if(!take(&s,w) || ident_char(*s))return 0;
    *p=s;return 1;
}
static int identifier(const char **p,char name[64]) {
    spaces(p);
    const char *s=*p;
    if(!ident_char(*s) || isdigit((unsigned char)*s))return 0;
    size_t n=0;while(ident_char(s[n]))n++;
    if(n>=64)return 0;
    memcpy(name,s,n);name[n]=0;*p=s+n;return 1;
}
static int decimal(const char **p,int *value) {
    spaces(p);
    int negative=take(p,"-");
    spaces(p);const char *s=*p;
    if(!isdigit((unsigned char)*s) || (*s=='0' && isdigit((unsigned char)s[1])))return 0;
    int v=0;
    do {
        int digit=*s++-'0';
        if(v>(2147483647-digit)/10)return 0;
        v=10*v+digit;
    } while(isdigit((unsigned char)*s));
    *value=negative?-v:v;*p=s;return 1;
}

int jov_boundary_code(const char *source,char code[JOV_BOUNDARY_CODE_SIZE]) {
    const char *p=source;
    char fn[64],var[64];
    if(!word(&p,"int") || !identifier(&p,fn) || !take(&p,"(") ||
       !word(&p,"int") || !identifier(&p,var) || !take(&p,")") || !take(&p,"{") ||
       !word(&p,"return"))return 0;
    int negated=take(&p,"!");
    if(negated && !take(&p,"("))return 0;
    int left_var=word(&p,var), n;
    if(!left_var && !decimal(&p,&n))return 0;
    spaces(&p);char direction=*p;
    if(direction!='<' && direction!='>')return 0;
    p++;
    int inclusive=*p=='=';
    if(inclusive)p++;
    if(left_var) {if(!decimal(&p,&n))return 0;}
    else if(!word(&p,var))return 0;
    if((negated && !take(&p,")")) || !take(&p,";") || !take(&p,"}"))return 0;
    spaces(&p);if(*p)return 0;
    if(!left_var)direction=direction=='<'?'>':'<';
    if(negated){direction=direction=='<'?'>':'<';inclusive=!inclusive;}
    int len=snprintf(code,JOV_BOUNDARY_CODE_SIZE,"int %s(int %s) { return %s %c%s %d; }",
                     fn,var,var,direction,inclusive?"=":"",n);
    return len>=0 && len<JOV_BOUNDARY_CODE_SIZE;
}

int jov_boundary_context(const char *context,const char *rule,const char *change,
                         char code[JOV_BOUNDARY_CODE_SIZE],char **model_context) {
    *model_context=NULL;
    const char *start=strstr(context,change);
    if(!start || !*change || strstr(start+1,change))return 0;
    const char *end=start+strlen(change);
    const char *index_line=NULL,*after_index=NULL;
    if(jov_boundary_code(change,code)) {
        const char fence[]="```c\n";
        size_t prefix=(size_t)(start-context);
        if(prefix<sizeof(fence)-1 || memcmp(start-(sizeof(fence)-1),fence,sizeof(fence)-1) ||
           (prefix>sizeof(fence)-1 && start[-(int)sizeof(fence)]!='\n') ||
           strncmp(end,"\n```",4) || (end[4] && end[4]!='\n'))return 0;
    } else {
        /* The new blob's ID changes with spelling. Omit that index line only
         * from the model view. The receipt keeps every original diff byte. */
        const char marker[]="\n@@ -0,0 +1 @@\n+";
        const char *hunk=strstr(change,marker);
        if(*end || strncmp(change,"diff --git ",11) || !hunk || !strstr(change,"\n--- /dev/null\n+++ ") ||
           strstr(change,"\ndiff --git ") || strstr(change,"\n@@ ")!=hunk)return 0;
        const char *index=strstr(change,"\nindex ");
        if(index) {
            const char *old=index+7,*dots=old+strspn(old,"0");
            if(dots==old || strncmp(dots,"..",2))return 0;
            const char *new_id=dots+2,*stop=new_id+strspn(new_id,"0123456789abcdef");
            if(stop==new_id || strncmp(stop,"\n--- /dev/null\n",15) || stop>hunk)return 0;
            index_line=start+(index+1-change);
            after_index=start+(stop+1-change);
        }
        const char *body=hunk+sizeof(marker)-1,*newline=strchr(body,'\n');
        if((newline && newline[1]) || !jov_boundary_code(body,code))return 0;
        start+=body-change;
        if(newline)end=start+(newline-body);
    }
    size_t prefix=(size_t)(start-context);
    const char *rule_start=strstr(context,rule);
    if(!rule_start || (rule_start<end && rule_start+strlen(rule)>start) ||
       (index_line && rule_start<after_index && rule_start+strlen(rule)>index_line))return 0;
    size_t code_len=strlen(code),tail=strlen(end);
    char *copy=malloc(prefix+code_len+tail+1);
    if(!copy)return -1;
    if(index_line) {
        size_t before=(size_t)(index_line-context),after=(size_t)(start-after_index);
        memcpy(copy,context,before);memcpy(copy+before,after_index,after);prefix=before+after;
    } else memcpy(copy,context,prefix);
    memcpy(copy+prefix,code,code_len);
    memcpy(copy+prefix+code_len,end,tail+1);*model_context=copy;
    return 1;
}
