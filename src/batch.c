#include "batch.h"
#include "hash.h"
#include "json.h"
#include <stdlib.h>
#include <string.h>
int jov_batch_digest(const jov_batch_item *items,int count,char out[65]) {
    if(!items || !out || count<1 || count>JOV_BATCH_MAX_FILES)return 1;
    FILE*f=tmpfile();if(!f)return 1;int rc=1;
    fputs("{\"schema\":\"jovovich.git-batch/1\",\"scope\":\"all_changed_paths\",\"items\":[",f);
    for(int i=0;i<count;i++) {
        const jov_batch_item*p=items+i;
        if(!p->file || !*p->file || !p->id || strlen(p->id)!=64 || strspn(p->id,"0123456789abcdef")!=64 || jov_source_validate(&p->source))goto done;
        if(i)fputc(',',f);
        fputc('{',f);json_field(f,"file",p->file);fputc(',',f);json_field(f,"id",p->id);
        fputs(",\"source\":",f);if(jov_source_json(f,&p->source))goto done;fputc('}',f);
    }
    fputs("]}",f);long n=ftell(f);
    if(ferror(f) || n<1 || (unsigned long)n>JOV_BATCH_MAX_BYTES || fseek(f,0,SEEK_SET))goto done;
    char*p=malloc((size_t)n);if(!p)goto done;
    if(fread(p,1,(size_t)n,f)==(size_t)n)rc=hash_bytes(p,(size_t)n,out);
    free(p);
done:
    if(fclose(f))rc=1;
    return rc;
}
