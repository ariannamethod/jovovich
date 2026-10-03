#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>
#include <sys/wait.h>

/* The fixture has a real byte BPE vocabulary, not a tokenizer stub. Its merge
 * table makes ":[{ and ":[] distinct targets. A second table deliberately
 * merges s + the closing quote across the requested findings boundary. */
enum { ROWS=4, ELEMENTS=42, TOKEN_EOS=257, TOKEN_CLEAN=260, TOKEN_CONCERN=261 };
static const char *answers[ROWS]={
    "{\"analysis\":\"Élan: \\\"findings\\\" in prose.\",\"context\":{\"findings\":[]},\"findings\":[{\"rule\":\"scope\"}]}",
    "{\"analysis\":\"Clean.\",\"findings\":[]}",
    "{ \"meta\":[{\"findings\":[]}], \"analysis\":\"Nested before decision; ✓\", \"findings\":[{}] }",
    "{\"analysis\":\"Short.\",\"findings\":[]}"
};
static const char *prefixes[ROWS]={
    "{\"analysis\":\"Élan: \\\"findings\\\" in prose.\",\"context\":{\"findings\":[]},\"findings",
    "{\"analysis\":\"Clean.\",\"findings",
    "{ \"meta\":[{\"findings\":[]}], \"analysis\":\"Nested before decision; ✓\", \"findings",
    "{\"analysis\":\"Short.\",\"findings"
};
static void put32(FILE *f,uint32_t n) {
    unsigned char b[4];for(int i=0;i<4;i++)b[i]=(unsigned char)(n>>(8*i));
    assert(fwrite(b,1,4,f)==4);
}
static void put64(FILE *f,uint64_t n) {put32(f,(uint32_t)n);put32(f,(uint32_t)(n>>32));}
static void putstr(FILE *f,const char *s) {size_t n=strlen(s);put64(f,n);assert(fwrite(s,1,n,f)==n);}
static void mapstr(FILE *f,const char *s) {size_t n=strlen(s);put32(f,(uint32_t)n);assert(fwrite(s,1,n,f)==n);}
static FILE *new_file(char *path) {int fd=mkstemp(path);assert(fd>=0);FILE *f=fdopen(fd,"wb");assert(f);return f;}
static void byte_symbol(unsigned b,char *s) {
    int missing=0;
    for(unsigned i=0;i<b;i++)missing+=!((i>=33&&i<=126)||(i>=161&&i<=172)||(i>=174));
    unsigned cp=((b>=33&&b<=126)||(b>=161&&b<=172)||(b>=174))?b:256+(unsigned)missing;
    if(cp<128){s[0]=(char)cp;s[1]=0;}
    else {s[0]=(char)(0xc0|(cp>>6));s[1]=(char)(0x80|(cp&63));s[2]=0;}
}
static bpe_tokenizer *fixture_tokenizer(int mode) {
    int crossing=mode==1,asymmetric=mode==2,vocab=asymmetric?264:crossing?263:262;
    char path[]="/tmp/jovovich-verdict-tokenizer-XXXXXX";FILE *f=new_file(path);
    assert(fwrite("GGUF",1,4,f)==4);put32(f,3);put64(f,0);put64(f,3);
    putstr(f,"tokenizer.ggml.tokens");put32(f,9);put32(f,8);put64(f,(uint64_t)vocab);
    for(unsigned b=0;b<256;b++){char s[4];byte_symbol(b,s);putstr(f,s);}
    const char *extra[]={"<|im_start|>","<|im_end|>","\":","\":[","\":[]","\":[{","s\""};
    for(int i=0;i<(crossing?7:6);i++)putstr(f,extra[i]);
    if(asymmetric){putstr(f,"[{");putstr(f,":[{");}
    putstr(f,"tokenizer.ggml.merges");put32(f,9);put32(f,8);put64(f,crossing?5:4);
    /* Crossing has rank zero, before the closing quote can merge with colon. */
    if(crossing)putstr(f,"s \"");
    const char *merges[]={"\" :","\": [","\":[ ]","\":[ {"};
    const char *asymmetric_merges[]={"[ {",": [{","\" :[{","\" :"};
    for(int i=0;i<4;i++)putstr(f,asymmetric?asymmetric_merges[i]:merges[i]);
    putstr(f,"tokenizer.ggml.pre");put32(f,8);putstr(f,"qwen2");
    assert(fclose(f)==0);bpe_tokenizer *tok=bpe_load(path);assert(tok);assert(unlink(path)==0);
    assert(bpe_n_vocab(tok)==vocab);return tok;
}
static void map_file(char *path,int version,uint32_t count,uint32_t pairs,const uint32_t *indices,const char *const *fields) {
    FILE *f=strstr(path,"XXXXXX")?new_file(path):fopen(path,"wb");assert(f);
    assert(fwrite("JVPR",1,4,f)==4);put32(f,(uint32_t)version);put32(f,count);put32(f,pairs);
    for(uint32_t i=0;i<pairs;i++) {
        put32(f,indices[2*i]);put32(f,indices[2*i+1]);
        if(version==2){mapstr(f,fields[2*i]);mapstr(f,fields[2*i+1]);}
    }
    assert(fclose(f)==0);
}
static void tokenize_rows(mlp_example *rows,bpe_tokenizer *tok) {
    memset(rows,0,ROWS*sizeof(*rows));
    for(int i=0;i<ROWS;i++) {
        rows[i].system="JOVOVICH reviews.";rows[i].prompt="Review this diff.";rows[i].answer=(char*)answers[i];
        tokenize(&rows[i],tok);
    }
}
static void clear_rows(mlp_example *rows) {
    for(int i=0;i<ROWS;i++){free(rows[i].ids);batch_free(&rows[i].cache);}
}
static void fixture_fill(nt_tensor *t,float scale,int shift) {
    for(int i=0;i<t->len;i++)t->data[i]=scale*(float)(((i*7+shift)%17)-8);
}
static nt_tensor *parameter(mlp_bank *b,int j) {return j%2?b->adapters[j/2].B:b->adapters[j/2].A;}
static void bank_fixture(mlp_bank *b,mlp_example *rows,int vocab) {
    b->E=3;b->F=4;b->V=vocab;b->layer=1;
    b->wg=tensor(b->F,b->E);b->wu=tensor(b->F,b->E);b->wd=tensor(b->E,b->F);
    b->head=tensor(b->V,b->E);b->norm=tensor(1,b->E);b->ffn_norm=tensor(1,b->E);
    fixture_fill(b->wg,.07f,2);fixture_fill(b->wu,.06f,3);fixture_fill(b->wd,.08f,4);fixture_fill(b->head,.11f,5);
    for(int k=0;k<b->E;k++){b->norm->data[k]=.8f+.1f*k;b->ffn_norm->data[k]=1.1f-.05f*k;}
    for(int j=0;j<3;j++) {
        assert(nt_lora_init(&b->adapters[j],j==2?b->F:b->E,j==2?b->E:b->F,2,4)==0);
        fixture_fill(b->adapters[j].A,.035f,j+1);fixture_fill(b->adapters[j].B,.025f,j+4);
    }
    for(int i=0;i<ROWS;i++) {
        rows[i].cache.z=tensor(rows[i].cache.n,b->E);fixture_fill(rows[i].cache.z,.12f,i+1);prepare_cache(b,&rows[i].cache);
    }
}
static void bank_clear(mlp_bank *b) {
    nt_tape_start();for(int j=0;j<6;j++)nt_tape_param(parameter(b,j));nt_tape_destroy();
    for(int j=0;j<3;j++)nt_lora_free(&b->adapters[j]);
    nt_tensor_free(b->wg);nt_tensor_free(b->wu);nt_tensor_free(b->wd);nt_tensor_free(b->head);
    nt_tensor_free(b->norm);nt_tensor_free(b->ffn_norm);
}
static void gradient(mlp_bank *b,float *out) {
    int offsets[6],n=0;unsigned seen=0;
    for(int j=0;j<6;j++){offsets[j]=n;n+=parameter(b,j)->len;}assert(n==ELEMENTS);
    nt_tape *t=nt_tape_get();assert(t->n_params==6);
    for(int i=0;i<t->count;i++)if(t->entries[i].is_param&&!t->entries[i].frozen) {
        nt_tape_entry *e=&t->entries[i];int slot=e->slot;
        assert(slot>=0&&slot<6&&!(seen&(1u<<slot))&&e->output==parameter(b,slot)&&e->grad);seen|=1u<<slot;
        memcpy(out+offsets[slot],e->grad->data,(size_t)e->grad->len*sizeof(float));
    }
    assert(seen==63);
}
static void objective_test(mlp_bank *b,mlp_example *rows,const int *positions) {
    int decisions,residual;token_row *order=joint_order(rows,ROWS,&decisions,&residual),*selected=decision_order(rows,ROWS,ROWS);
    int total=0;for(int i=0;i<ROWS;i++)total+=rows[i].cache.n;
    assert(decisions==ROWS&&residual==total-ROWS);
    double oracle=0,oracle_g[ELEMENTS]={0},decision_mass=0,residual_mass=0;int at=0;
    for(int i=0;i<ROWS;i++) {
        assert(selected[i].example==i&&selected[i].token==positions[i]);
        for(int p=0;p<rows[i].cache.n;p++,at++) {
            assert(order[at].example==i&&order[at].token==p);
            /* Oracle membership is the fixture's independently encoded prefix,
             * including rationale and EOS in residual, not first divergence. */
            int decision=p==positions[i];double c=decision?1.0/ROWS:1.0/(total-ROWS);
            assert(fabs(joint_coefficient(&rows[i],p,decisions,residual)-c)<1e-8);
            if(decision)decision_mass+=c;else residual_mass+=c;
            token_row one={i,p};mlp_batch batch=gather(b,rows,&one,1);assert(!batch.weights);
            nt_tape_start();int ce=mlp_forward(b,&batch,1,NULL,NULL,NULL);oracle+=c*nt_tape_get()->entries[ce].output->data[0];
            nt_tape_backward(ce);float g[ELEMENTS];gradient(b,g);
            for(int k=0;k<ELEMENTS;k++)oracle_g[k]+=c*g[k];
            nt_tape_clear();batch_free(&batch);
        }
    }
    assert(at==total&&fabs(decision_mass-1)<1e-12&&fabs(residual_mass-1)<1e-12);
    float max_gradient_error=0;double max_loss_error=0;
    const int batches[]={7,19,total};
    for(unsigned i=0;i<sizeof(batches)/sizeof(*batches);i++) {
        double loss;joint_accumulate(b,rows,order,total,batches[i],decisions,residual,&loss);
        float g[ELEMENTS];gradient(b,g);max_loss_error=fmax(max_loss_error,fabs(loss-oracle));assert(fabs(loss-oracle)<3e-6);
        for(int k=0;k<ELEMENTS;k++) {
            float error=(float)fabs(g[k]-oracle_g[k]);max_gradient_error=fmaxf(max_gradient_error,error);assert(error<3e-6);
        }
        nt_tape_clear();
    }
    free(order);free(selected);
    printf("JVPR2 joint objective: %d decisions at unequal positions + %d residual targets; rationale and EOS included; 3 microbatch sizes match 42 independent adapter derivatives (loss=%g gradient=%g)\n",ROWS,residual,max_loss_error,max_gradient_error);
}
static void truncate_file(const char *path,size_t bytes) {assert(truncate(path,(off_t)bytes)==0);}
static void patch32(const char *path,long offset,uint32_t n) {FILE *f=fopen(path,"r+b");assert(f&&fseek(f,offset,SEEK_SET)==0);put32(f,n);assert(fclose(f)==0);}
static void replace_answer(mlp_example *rows,int row,bpe_tokenizer *tok,char *answer) {
    free(rows[row].ids);batch_free(&rows[row].cache);rows[row]=(mlp_example){.system="s",.prompt="p",.answer=answer};tokenize(&rows[row],tok);
}
static void rejection_tests(bpe_tokenizer *tok,bpe_tokenizer *crossing) {
    const char *labels[]={"missing tokenizer","stale prefix","nested findings decoy","quoted findings decoy","duplicate findings key","escaped top-level findings key","escaped other top-level key","wrong pair index","same pair index","duplicate mapped row","truncated prefix","trailing bytes","unsupported version","dataset row mismatch","equal verdict IDs","terminal EOS position","EOS target ID","BPE merge crosses boundary","tokenizer capacity","findings is not an array","malformed JSON","missing findings","whitespace formatting decoy","wrong declared concern role","counterfactual alternative mismatch","counterfactual token capacity"};
    const uint32_t indices[]={0,1,2,3};
    for(unsigned test=0;test<sizeof(labels)/sizeof(*labels);test++) {
        char path[]="/tmp/jovovich-verdict-reject-XXXXXX";map_file(path,2,ROWS,2,indices,prefixes);
        FILE *errors=tmpfile();assert(errors);fflush(NULL);pid_t pid=fork();assert(pid>=0);
        if(!pid) {
            if(dup2(fileno(errors),STDERR_FILENO)<0)_exit(2);
            mlp_example rows[ROWS];bpe_tokenizer *active=test==17?crossing:tok;tokenize_rows(rows,active);
            mlp_bank b={.average_tokens=60};const char *fields[ROWS];memcpy(fields,prefixes,sizeof(fields));int rewrite=0;
            switch(test) {
            case 0:active=NULL;break;
            case 1:fields[0]="{\"analysis\":\"stale\",\"findings";rewrite=1;break;
            case 2:fields[0]="{\"analysis\":\"Élan: \\\"findings\\\" in prose.\",\"context\":{\"findings";rewrite=1;break;
            case 3:fields[0]="{\"analysis\":\"Élan: \\\"findings";rewrite=1;break;
            case 4:replace_answer(rows,0,tok,"{\"findings\":[{}],\"findings\":[]}");fields[0]="{\"findings";rewrite=1;break;
            case 5:replace_answer(rows,0,tok,"{\"find\\u0069ngs\":[{}]}");fields[0]="{\"find\\u0069ngs";rewrite=1;break;
            case 6:replace_answer(rows,0,tok,"{\"anal\\u0079sis\":\"x\",\"findings\":[{}]}");fields[0]="{\"anal\\u0079sis\":\"x\",\"findings";rewrite=1;break;
            case 7:patch32(path,16,ROWS);break;
            case 8:patch32(path,20,0);break;
            case 9: {
                long offset=24+4+(long)strlen(prefixes[0])+4+(long)strlen(prefixes[1]);patch32(path,offset,0);break;
            }
            case 10:truncate_file(path,28+strlen(prefixes[0])-1);break;
            case 11:{FILE *f=fopen(path,"ab");assert(f&&fputc('x',f)!=EOF&&fclose(f)==0);break;}
            case 12:patch32(path,4,3);break;
            case 13:patch32(path,8,ROWS+1);break;
            case 14: {int ids[MLP_MAX_TOKENS];int n=bpe_encode_raw(tok,prefixes[0],ids,MLP_MAX_TOKENS);rows[0].cache.targets->data[n]=TOKEN_CLEAN;break;}
            case 15: {int ids[MLP_MAX_TOKENS];rows[0].cache.n=bpe_encode_raw(tok,prefixes[0],ids,MLP_MAX_TOKENS)+1;break;}
            case 16: {int ids[MLP_MAX_TOKENS];int n=bpe_encode_raw(tok,prefixes[0],ids,MLP_MAX_TOKENS);rows[0].cache.targets->data[n]=TOKEN_EOS;break;}
            case 17:break;
            case 18: {
                const char *begin="{\"analysis\":\"",*tail="\",\"findings";size_t n=MLP_MAX_TOKENS+100;
                char *prefix=calloc(n+100,1),*answer=calloc(n+120,1);assert(prefix&&answer);
                strcpy(prefix,begin);memset(prefix+strlen(begin),'x',n);strcat(prefix,tail);
                strcpy(answer,prefix);strcat(answer,"\":[{}]}");rows[0].answer=answer;rows[0].cache.n=(int)n+100;
                (void)verdict_position(&rows[0],tok,prefix,1);_exit(0);
            }
            case 19:replace_answer(rows,0,tok,"{\"findings\":{}}");fields[0]="{\"findings";rewrite=1;break;
            case 20:replace_answer(rows,0,tok,"{\"analysis\":wrong,\"findings\":[{}]}");fields[0]="{\"analysis\":wrong,\"findings";rewrite=1;break;
            case 21:replace_answer(rows,0,tok,"{\"nested\":{\"findings\":[{}]}}");fields[0]="{\"nested\":{\"findings";rewrite=1;break;
            case 22:replace_answer(rows,0,tok,"{\"findings\" : [{\"rule\":\"scope\"}]}");fields[0]="{\"findings";rewrite=1;break;
            case 23:replace_answer(rows,0,tok,"{\"findings\":[]}");fields[0]="{\"findings";rewrite=1;break;
            case 24: {int ids[MLP_MAX_TOKENS];int n=bpe_encode_raw(tok,prefixes[0],ids,MLP_MAX_TOKENS);rows[0].cache.targets->data[n]='?';break;}
            case 25: {
                size_t n=2100;char *prefix=calloc(n+100,1),*left=calloc(n+120,1),*right=calloc(n+120,1);assert(prefix&&left&&right);
                strcpy(prefix,"{\"analysis\":\"");memset(prefix+strlen(prefix),'x',n);strcat(prefix,"\",\"findings");
                strcpy(left,prefix);strcat(left,"\":[{}]}");
                strcpy(right,"{\"findings\":[],\"after\":\"");memset(right+strlen(right),'y',n);strcat(right,"\"}");
                replace_answer(rows,0,tok,left);replace_answer(rows,1,tok,right);
                fields[0]=prefix;fields[1]="{\"findings";rewrite=1;break;
            }
            }
            if(rewrite)map_file(path,2,ROWS,2,indices,fields);
            load_pairs_tokenized(&b,rows,ROWS,path,active);_exit(0);
        }
        int status;assert(waitpid(pid,&status,0)==pid);
        if(!WIFEXITED(status)||WEXITSTATUS(status)!=1)fprintf(stderr,"JVPR2 rejection failed: %s\n",labels[test]);
        assert(WIFEXITED(status)&&WEXITSTATUS(status)==1);
        char message[512]={0};rewind(errors);assert(fread(message,1,sizeof(message)-1,errors)>0);assert(strstr(message,"train-mlp:"));
        if(test==17)assert(strstr(message,"BPE merge crosses"));
        if(test==18)assert(strstr(message,"token capacity"));
        if(test==22||test==23)assert(strstr(message,"compact concern/clean"));
        if(test==24)assert(strstr(message,"reciprocal alternative"));
        if(test==25)assert(strstr(message,"counterfactual exceeds token capacity"));
        fclose(errors);(void)unlink(path);
    }
    printf("JVPR2 rejects %zu malformed, stale, ambiguous, EOS, capacity and BPE-boundary inputs\n",sizeof(labels)/sizeof(*labels));
}
int main(void) {
    bpe_tokenizer *tok=fixture_tokenizer(0),*crossing=fixture_tokenizer(1);mlp_example rows[ROWS];tokenize_rows(rows,tok);
    int expected[ROWS];int total=0;
    for(int i=0;i<ROWS;i++) {
        int ids[MLP_MAX_TOKENS];expected[i]=bpe_encode_raw(tok,prefixes[i],ids,MLP_MAX_TOKENS);
        assert(expected[i]>0&&expected[i]<rows[i].cache.n-1);total+=rows[i].cache.n;
        assert((int)rows[i].cache.targets->data[expected[i]]==(i%2?TOKEN_CLEAN:TOKEN_CONCERN));
        char decoded[1024]={0};size_t bytes=0;
        for(int k=0;k<expected[i];k++)bytes+=(size_t)bpe_decode_token(tok,ids[k],decoded+bytes,(int)(sizeof(decoded)-bytes));
        assert(bytes==strlen(prefixes[i])&&!strcmp(decoded,prefixes[i]));
    }
    assert(expected[0]!=expected[1]&&expected[2]!=expected[3]);
    const uint32_t indices[]={0,1,2,3};char path[]="/tmp/jovovich-verdict-valid-XXXXXX";
    map_file(path,2,ROWS,2,indices,prefixes);mlp_bank b={.average_tokens=(double)total/ROWS};load_pairs_tokenized(&b,rows,ROWS,path,tok);assert(unlink(path)==0);
    assert(b.pair_count==2&&b.pair_map_version==2);
    for(int i=0;i<ROWS;i++) {
        assert(rows[i].decision_pair==i/2+1&&rows[i].decision_position==expected[i]);
        assert(rows[i].decision_prefix_bytes==(int)strlen(prefixes[i]));
        assert(rows[i].decision_alternative_id==(i%2?TOKEN_CONCERN:TOKEN_CLEAN));
    }
    printf("JVPR2 real BPE: positions %d/%d and %d/%d; literal Unicode bytes, escaped quotes and nested findings retain the top-level decision\n",expected[0],expected[1],expected[2],expected[3]);
    bank_fixture(&b,rows,bpe_n_vocab(tok));objective_test(&b,rows,expected);bank_clear(&b);clear_rows(rows);
    rejection_tests(tok,crossing);
    tokenize_rows(rows,tok);char legacy[]="/tmp/jovovich-verdict-v1-XXXXXX";map_file(legacy,1,ROWS,2,indices,NULL);
    load_pairs(&b,rows,ROWS,legacy);assert(unlink(legacy)==0&&b.pair_map_version==1);
    for(int i=0;i<ROWS;i+=2)assert(rows[i].decision_position==rows[i+1].decision_position&&rows[i].decision_position<expected[i]);
    for(int i=0;i<ROWS;i++)assert(rows[i].decision_prefix_bytes==0);
    puts("JVPR1 compatibility: rationale's first divergence remains historical selection; JVPR2 uses each verdict boundary");
    clear_rows(rows);
    bpe_tokenizer *asymmetric=fixture_tokenizer(2);tokenize_rows(rows,asymmetric);
    char asymmetric_map[]="/tmp/jovovich-verdict-asymmetric-XXXXXX";map_file(asymmetric_map,2,ROWS,2,indices,prefixes);
    load_pairs_tokenized(&b,rows,ROWS,asymmetric_map,asymmetric);assert(unlink(asymmetric_map)==0);
    for(int i=0;i<ROWS;i++) {
        assert((int)rows[i].cache.targets->data[rows[i].decision_position]==(i%2?258:TOKEN_CONCERN));
        assert(rows[i].decision_alternative_id==(i%2?TOKEN_CONCERN:258));
    }
    puts("JVPR2 asymmetric BPE: clean target is only quote/colon; counterfactual suffixes verify reciprocal alternatives without equal decoded widths");
    clear_rows(rows);bpe_free(asymmetric);bpe_free(tok);bpe_free(crossing);return 0;
}
