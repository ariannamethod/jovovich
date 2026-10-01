#include "examples/bpe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void hex(const char *s,int n) { for(int i=0;i<n;i++)printf("%02x",(unsigned char)s[i]); }
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 bpe_tokenizer *tok=bpe_load(argv[1]);if(!tok)return 1;
 int expected[]={4913,3903,819,66582,788};char text[4096];
 for(int i=0;i<5;i++){int n=bpe_decode_token(tok,expected[i],text,sizeof(text));printf("{\"operation\":\"decode\",\"token_id\":%d,\"bytes\":%d,\"hex\":\"",expected[i],n);hex(text,n);puts("\"}");}
 const char *spans[]={"{\"findings\":","{\"findings","{\"findings\":[]}","{\"findings\":[{\"path\":\"test.c\"}]}"};
 for(int i=0;i<4;i++){int ids[128],n=bpe_encode_raw(tok,spans[i],ids,128);printf("{\"operation\":\"encode\",\"input_hex\":\"");hex(spans[i],strlen(spans[i]));printf("\",\"ids\":[");for(int j=0;j<n;j++)printf("%s%d",j?",":"",ids[j]);puts("]}");}
 bpe_free(tok);return 0;
}
