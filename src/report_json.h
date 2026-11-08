#ifndef JOVOVICH_REPORT_JSON_H
#define JOVOVICH_REPORT_JSON_H
#include "tools/narrow_json.h"

/* Reports retain answer JSON verbatim. Validate its syntax first and reject
 * duplicate keys, so every consumer reads the same decision. Protocol keys
 * use literal spellings, matching narrow_json's lookup contract. */
static const char *report_string_end(const char *p) {
    const char *end=nj_str_end(p);
    if(!end)return NULL;
    for(const char*q=p+1;q<end-1;q++)if((unsigned char)*q<0x20)return NULL;
    char*s=nj_string(p);if(!s)return NULL;free(s);return end;
}
static const char *report_json_end(const char *p,int depth) {
    if(depth>64)return NULL;
    p=nj_ws(p);
    if(*p=='"')return report_string_end(p);
    if(*p=='{' || *p=='[') {
        char close=*p=='{'?'}':']';
        const char*keys[64];size_t lengths[64],count=0;
        p=nj_ws(p+1);if(*p==close)return p+1;
        for(;;) {
            if(close=='}') {
                const char*end=report_string_end(p);
                if(!end || count==64)return NULL;
                size_t n=(size_t)(end-p);
                if(memchr(p,'\\',n))return NULL;
                for(size_t i=0;i<count;i++)if(lengths[i]==n && !memcmp(keys[i],p,n))return NULL;
                keys[count]=p;lengths[count++]=n;p=nj_ws(end);
                if(*p!=':')return NULL;
                p++;
            }
            p=report_json_end(p,depth+1);if(!p)return NULL;
            p=nj_ws(p);if(*p==close)return p+1;
            if(*p!=',')return NULL;
            p=nj_ws(p+1);
        }
    }
    if(!strncmp(p,"true",4))return p+4;
    if(!strncmp(p,"false",5))return p+5;
    if(!strncmp(p,"null",4))return p+4;
    if(*p=='-')p++;
    if(*p=='0')p++;
    else {
        if(*p<'1' || *p>'9')return NULL;
        do{p++;}while(*p>='0' && *p<='9');
    }
    if(*p=='.') {
        p++;if(*p<'0' || *p>'9')return NULL;
        do{p++;}while(*p>='0' && *p<='9');
    }
    if(*p=='e' || *p=='E') {
        p++;if(*p=='+' || *p=='-')p++;
        if(*p<'0' || *p>'9')return NULL;
        do{p++;}while(*p>='0' && *p<='9');
    }
    return p;
}

static inline char *report_json_row(FILE*f,size_t*total,int*bad,size_t limit,size_t total_limit) {
    char*p=malloc(limit+1);if(!p){*bad=1;return NULL;}size_t n=0;int c;
    while((c=fgetc(f))!=EOF) {
        if(!c || n==limit){*bad=1;free(p);return NULL;}p[n++]=(char)c;if(c=='\n')break;
    }
    if(ferror(f) || *total+n>total_limit){*bad=1;free(p);return NULL;}
    if(!n){free(p);return NULL;}p[n]=0;*total+=n;
    const char*end=report_json_end(p,0);if(!end || *nj_ws(end)){*bad=1;free(p);return NULL;}
    char*small=realloc(p,n+1);return small?small:p;
}

/* A batch or quality score carries one readout identity for every answer. */
static inline int report_readout(const char *answer, int index, char digest[65]) {
    const char *raw=nj_get(nj_get(answer,"execution"),"readout_sha256");
    char current[65]={0};
    if (raw) {
        char *s=nj_string(raw);
        if (!s || strlen(s)!=64 || strspn(s,"0123456789abcdef")!=64) {free(s);return 1;}
        memcpy(current,s,65);free(s);
    }
    if (index==0) memcpy(digest,current,sizeof(current));
    return strcmp(current,digest)!=0;
}
#endif
