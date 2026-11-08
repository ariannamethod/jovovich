#define _POSIX_C_SOURCE 200809L
#include "model_bytes.h"

#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"model snapshot: %s (line %d)\n",#x,__LINE__); return 1; } } while (0)

static int fixture(const char *path,const char *token,float weight,char sha[65]) {
    gguf_writer *w=gguf_write_open(path);
    if (!w || gguf_write_kv_str_array(w,"tokenizer.ggml.tokens",&token,1) ||
        gguf_write_tensor_decl(w,"probe",1,(uint64_t[]){1},GGUF_TYPE_F32) ||
        gguf_write_tensor_f32(w,"probe",&weight,1) || gguf_write_close(w)) return 1;
    unsigned char data[2048];
    FILE *f=fopen(path,"rb");
    if (!f) return 1;
    size_t n=fread(data,1,sizeof(data),f);
    int bad=ferror(f) || !feof(f) || !n || hash_bytes(data,n,sha);
    return fclose(f) || bad;
}

static int weight_is(gguf_file *g,float want) {
    int i=gguf_find_tensor(g,"probe");
    float *p=i<0?NULL:gguf_dequant(g,i);
    int ok=p && *p==want;
    free(p);
    return ok;
}

static int check_snapshot(int try_fd_paths) {
    char dir[]="/tmp/jov-model-test-XXXXXX",good[65],other[65],wh[65],th[65];
    int cwd=open(".",O_RDONLY|O_DIRECTORY);
    REQUIRE(cwd>=0 && mkdtemp(dir) && !chdir(dir) && !setenv("TMPDIR",dir,1));
    REQUIRE(!fixture("original","good",1,good) && !fixture("other","swap",9,other) && strcmp(good,other));
    REQUIRE(!symlink("original","source") && !symlink("other","next"));
    int writer=open("original",O_WRONLY);
    REQUIRE(writer>=0);
    jov_model_files s={0};
    REQUIRE(!jov_model_files_begin(&s,try_fd_paths));
    REQUIRE(!jov_model_capture(&s,JOV_WEIGHTS,"source",good,wh));
    REQUIRE(!jov_model_capture(&s,JOV_TOKENIZER,"source",good,th));
    REQUIRE(!strcmp(wh,good) && !strcmp(th,good));
    REQUIRE(!rename("next","source"));
    gguf_file *reopened=gguf_open("source");
    bpe_tokenizer *reopened_tok=bpe_load("source");
    REQUIRE(reopened && weight_is(reopened,9) && reopened_tok && bpe_token_id(reopened_tok,"swap")==0);
    gguf_close(reopened); bpe_free(reopened_tok);
    /* Keeping only the original inode alive would still allow this destructive write. */
    REQUIRE(!ftruncate(writer,0) && write(writer,"not a gguf",10)==10 && !close(writer));
    gguf_file *gg=NULL;
    bpe_tokenizer *tok=NULL;
    REQUIRE(!jov_model_load(&s,&gg,&tok));
    jov_model_files_end(&s);
    /* The native tensor mapping remains correct after the private names are gone. */
    REQUIRE(weight_is(gg,1) && bpe_token_id(tok,"good")==0 && bpe_token_id(tok,"swap")<0);
    gguf_close(gg);bpe_free(tok); gg=NULL;tok=NULL;
    REQUIRE(jov_model_verified_pair("source","source",good,other,wh,th,&gg,&tok) && !gg && !tok);
    REQUIRE(jov_model_verified_pair("source","source",other,good,wh,th,&gg,&tok) && !gg && !tok);
    /* The weights parse successfully; the matching non-tokenizer input does not. */
    char invalid[65];
    REQUIRE(!hash_bytes("not a gguf",10,invalid));
    REQUIRE(jov_model_verified_pair("source","original",other,invalid,wh,th,&gg,&tok) && !gg && !tok);
    REQUIRE(!mkfifo("pipe",0600));
    REQUIRE(jov_model_verified_pair("pipe","source",other,other,wh,th,&gg,&tok) && !gg && !tok);
    REQUIRE(!unlink("pipe"));
    REQUIRE(!jov_model_verified_pair("source","source",other,other,wh,th,&gg,&tok));
    REQUIRE(weight_is(gg,9) && bpe_token_id(tok,"swap")==0);
    gguf_close(gg); bpe_free(tok);
    REQUIRE(!unlink("original") && !unlink("source") && !unlink("other"));
    REQUIRE(!fchdir(cwd) && !close(cwd) && !rmdir(dir));
    return 0;
}

int main(void) {
    REQUIRE(!check_snapshot(1) && !check_snapshot(0));
    puts("model snapshots: native weights and tokenizer survive path replacement and source truncation");
    return 0;
}
