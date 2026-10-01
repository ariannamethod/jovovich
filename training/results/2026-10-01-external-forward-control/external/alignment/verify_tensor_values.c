/* Producer-independent every-element check using pinned notorch dequantization. */
#include "gguf.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
static void require(int condition,const char *message) {
    if(!condition) {fprintf(stderr,"alignment-verifier: %s\n",message);exit(1);}
}
int main(int argc,char **argv) {
    require(argc==3,"usage: verify-tensor-values ORIGINAL.gguf CONVERTED.gguf");
    uint32_t endian=1;
    require(*(unsigned char*)&endian==1&&sizeof(float)==4,"requires little-endian float32");
    gguf_file *base=gguf_open(argv[1]),*model=gguf_open(argv[2]);
    require(base&&model,"cannot open both GGUF files");
    require(!strcmp(base->arch,"qwen2")&&!strcmp(model->arch,"qwen2"),"expected qwen2");
    require(base->n_tensors==291&&model->n_tensors==base->n_tensors,"tensor count changed");
    for(uint64_t i=0;i<base->n_tensors;i++)for(uint64_t j=i+1;j<base->n_tensors;j++) {
        require(strcmp(base->tensors[i].name,base->tensors[j].name)!=0,"duplicate original tensor name");
        require(strcmp(model->tensors[i].name,model->tensors[j].name)!=0,"duplicate converted tensor name");
    }
    uint64_t total=0;
    for(uint64_t i=0;i<base->n_tensors;i++) {
        const gguf_tensor_info *a=&base->tensors[i];
        int destination=gguf_find_tensor(model,a->name);
        require(destination>=0,"converted tensor name missing");
        const gguf_tensor_info *b=&model->tensors[destination];
        require(a->ndim==b->ndim&&a->n_elements==b->n_elements,"tensor dimensions changed");
        for(uint32_t d=0;d<a->ndim;d++)require(a->shape[d]==b->shape[d],"tensor shape changed");
        require(a->dtype==GGUF_TYPE_Q8_0||a->dtype==GGUF_TYPE_F32||a->dtype==GGUF_TYPE_F16,"unsupported original dtype");
        require(b->dtype==GGUF_TYPE_F32,"converted tensor is not F32");
        require(b->n_elements<=UINT64_MAX/4&&b->offset<=model->data_size&&b->n_elements*4<=model->data_size-b->offset,"converted payload truncated");
        require(a->shape[0]>0&&a->shape[0]<=SIZE_MAX/4&&a->n_elements%a->shape[0]==0,"invalid row shape");
        float *row=malloc((size_t)a->shape[0]*4);
        require(row!=NULL,"cannot allocate one reference row");
        uint64_t rows=a->n_elements/a->shape[0];
        for(uint64_t r=0;r<rows;r++) {
            require(gguf_dequant_row(base,(int)i,r,row)==0,"independent native dequantization failed");
            const float *actual=(const float*)(model->data+b->offset+r*a->shape[0]*4);
            for(uint64_t j=0;j<a->shape[0];j++) {
                require(isfinite(row[j])&&isfinite(actual[j]),"nonfinite tensor value");
                if(memcmp(&row[j],&actual[j],4)) {
                    fprintf(stderr,"alignment-verifier: tensor %s row %llu column %llu differs\n",a->name,(unsigned long long)r,(unsigned long long)j);
                    return 1;
                }
            }
        }
        free(row);total+=a->n_elements;
        printf("{\"tensor_index\":%llu,\"name\":\"%s\",\"elements\":%llu,\"original_dtype\":%u,\"converted_tensor_index\":%d,\"converted_dtype\":0,\"all_finite\":true,\"exact_float32_bytes\":true}\n",(unsigned long long)i,a->name,(unsigned long long)a->n_elements,a->dtype,destination);
        require(!fflush(stdout),"cannot write complete verification result");
    }
    fprintf(stderr,"verified all291 tensors, %llu float32 elements, using notorch gguf_dequant_row\n",(unsigned long long)total);
    gguf_close(base);gguf_close(model);return 0;
}
