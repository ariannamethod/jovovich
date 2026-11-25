/* Protocol fixtures only: store caller-supplied observations with real AML
 * encoding and evidence digests. No model inference occurs here. */
#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "report_json.h"
#include "hash.h"
#include <assert.h>

static void text_field(AM_Record *record,const char *name,const char *text) {
    AM_String *key=am_string_new(name), *string=am_string_new(text);
    AML_Var value={.type=AML_TYPE_STRING,.string=string};
    assert(key && string && !am_record_set(record,key,&value));
    am_string_free(key);am_string_free(string);
}

int main(int argc,char **argv) {
    assert(argc==4);am_init();
    AM_Record *record=am_record_new();AM_List *rows=am_list_new(), *keys=am_list_new();
    assert(record && rows && keys);
    text_field(record,"schema","jovovich.pr-history/1");text_field(record,"repository",argv[2]);
    text_field(record,"number",argv[3]);text_field(record,"opened","2026-10-01T09:00:00Z");
    size_t total=0;int bad=0;
    for (;;) {
        char *row=report_json_row(stdin,&total,&bad,AM_MAX_STRING_BYTES,AM_MAX_CHECKPOINT_BYTES);
        if(!row)break;
        const char *e=nj_get(row,"evidence"), *end=e?report_json_end(e,0):NULL;char hash[65];
        assert(end && !hash_bytes(e,(size_t)(end-e),hash));
        AM_String *value=am_string_new(row), *key=am_string_new(hash);
        assert(value && key && am_list_push(rows,value)>0 && am_list_push(keys,key)>0);
        am_string_free(value);am_string_free(key);free(row);
    }
    assert(!bad);
    AM_String *key=am_string_new("observations");AML_Var value={.type=AML_TYPE_LIST,.list=rows};
    assert(key && !am_record_set(record,key,&value));am_string_free(key);
    key=am_string_new("keys");value.list=keys;
    assert(key && !am_record_set(record,key,&value));am_string_free(key);
    char error[256];assert(am_checkpoint_save(record,argv[1],error,sizeof(error))>0);
    for(int i=0;i<keys->len;i++)puts(keys->items[i]->data);
    am_record_free(record);am_list_free(rows);am_list_free(keys);return 0;
}
