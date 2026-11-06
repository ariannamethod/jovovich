#ifndef JOVOVICH_JSON_H
#define JOVOVICH_JSON_H
#include <stdio.h>
static inline void json_string(FILE *out,const char *s) {
    fputc('"',out);
    for(const unsigned char*p=(const unsigned char*)s;*p;p++) {
        switch(*p) {
        case '"': fputs("\\\"",out);break;
        case '\\': fputs("\\\\",out);break;
        case '\b': fputs("\\b",out);break;
        case '\f': fputs("\\f",out);break;
        case '\n': fputs("\\n",out);break;
        case '\r': fputs("\\r",out);break;
        case '\t': fputs("\\t",out);break;
        default: if(*p<0x20)fprintf(out,"\\u%04x",(unsigned)*p);else fputc(*p,out);
        }
    }
    fputc('"',out);
}
static inline void json_field(FILE*out,const char*key,const char*value) {
    json_string(out,key);fputc(':',out);json_string(out,value);
}
#endif
