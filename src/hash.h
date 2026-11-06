#ifndef JOVOVICH_HASH_H
#define JOVOVICH_HASH_H
#include "sha256.h"
#include <stdio.h>
static inline int hash_bytes(const void*bytes,size_t n,char out[65]) {
    unsigned char h[32];if(nt_sha256(bytes,n,h))return 1;
    for(int i=0;i<32;i++)snprintf(out+2*i,3,"%02x",h[i]);
    return 0;
}
#endif
