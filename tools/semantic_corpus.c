#define _POSIX_C_SOURCE 200809L
#include "ariannamethod.h"
#include "hash.h"
#include "boundary.h"
#include "json.h"
#include "report_json.h"
#include <limits.h>

#define MAX_CASES 224
typedef struct {int kind,policy,limit,form,split;char code[768],hash[65];} sample;
typedef struct {int checked,failures,x,y,expected,actual;} proof;
static sample samples[MAX_CASES];
static int used;
static void die(const char*s){fprintf(stderr,"Corpus: %s\n",s);exit(1);}
static void add(int kind,int policy,int limit,int form,int split,int broken) {
    if(used==MAX_CASES)die("too many cases");
    sample*s=samples+used++;s->kind=kind;s->policy=policy;s->limit=limit;s->form=form;s->split=split;
    char body[512],expr[96];
    if(!kind) {
        const char*ops[]={"<","<=",">",">="},*opposites[]={">=",">","<=","<"};
        int op=policy^broken;
        if(form==0)snprintf(body,sizeof(body),"return value %s %d;",ops[op],limit);
        else if(form==1)snprintf(body,sizeof(body),"if (value %s %d) return 1; return 0;",ops[op],limit);
        else if(form==2)snprintf(body,sizeof(body),"return !(value %s %d);",opposites[op],limit);
        else {
            const int reversed[]={2,3,0,1};
            const char *symbol=form==3?ops[reversed[op]]:opposites[reversed[op]];
            snprintf(body,sizeof(body),form==3?"return %d %s value;":"return !(%d %s value);",limit,symbol);
        }
        snprintf(s->code,sizeof(s->code),"int accepts(int value) { %s }",body);
    }else {
        const char*conditions[]={"enabled","!enabled","enabled && ready","enabled || ready"};
        snprintf(expr,sizeof(expr),broken?"!(%s)":"(%s)",conditions[policy]);
        const char*formats[]={"if (%s) emit();","if (%s) { emit(); } else { return; }",
            "if (!(%s)) return; emit();","if (%s) { emit(); return; }",
            "int allowed = %s; if (allowed) emit();","int blocked = !(%s); if (!blocked) emit();",
            "if (%s) { for (int n = 0; n < 1; n++) emit(); }",
            "int calls = (%s) ? 1 : 0; while (calls-- > 0) emit();"};
        snprintf(body,sizeof(body),formats[form],expr);
        snprintf(s->code,sizeof(s->code),"void apply(int enabled, int ready) { (void)enabled; (void)ready; %s }",body);
    }
    if(hash_bytes(s->code,strlen(s->code),s->hash))die("code hash failed");
}
static void enumerate(int direct_boundary,int equivalent) {
    const int train[]={-5,-3,-1,1,3,5},holdout[]={-6,-2,2,6},fresh[]={-7,0,7};
    const int equivalent_forms[]={0,2,3,4};
    for(int split=0;split<2;split++) {
        const int *limits=!split?train:equivalent?fresh:holdout;
        int nlimits=!split?6:equivalent?3:4;
        int nforms=!split?2:equivalent?4:1;
        for(int op=0;op<4;op++)for(int l=0;l<nlimits;l++)
            for(int f=0;f<nforms;f++)for(int bad=0;bad<2;bad++) {
                int form=equivalent?equivalent_forms[f]:split?(direct_boundary?0:2):f;
                add(0,op,limits[l],form,split,bad);
            }
        if(!split || !equivalent)
            for(int policy=0;policy<4;policy++)for(int f=split?4:0;f<(split?8:4);f++)
                for(int bad=0;bad<2;bad++)add(1,policy,0,f,split,bad);
    }
    if(used!=(equivalent?224:192))die("case count changed");
    for(int i=0;i<used;i++)for(int j=0;j<i;j++)
        if(samples[i].split!=samples[j].split && !strcmp(samples[i].hash,samples[j].hash))die("code crosses split");
}
static void source_line(FILE *out,const char *s) {
    fputs(s,out);
    fputc('\n',out);
}
static void source(FILE *out,int equivalent) {
    source_line(out,"/* Generated trusted snippets, compiled exactly as shown; macros rename symbols only. */\n#include <stdio.h>\nstatic int calls;\nstatic void emit(void){calls++;}");
    for(int i=0;i<used;i++) {
        const char*name=samples[i].kind?"apply":"accepts";
        fprintf(out,"#define %s case_%d\n%s\n#undef %s\n",name,i,samples[i].code,name);
    }
    source_line(out,"typedef struct {int checked,failures,x,y,expected,actual;} proof;\n"
         "static int bound(int policy,int value,int limit){switch(policy){case 0:return value<limit;case 1:return value<=limit;case 2:return value>limit;default:return value>=limit;}}\n"
         "static int guard(int policy,int enabled,int ready){const unsigned masks[]={12,3,8,14};return (masks[policy]>>(2*enabled+ready))&1;}\n"
         "static void observe(proof*p,int x,int y,int expected,int actual){p->checked++;if(expected!=actual){if(!p->failures){p->x=x;p->y=y;p->expected=expected;p->actual=actual;}p->failures++;}}\n"
         "static void write_proof(int id,const char*hash,const proof*p){printf(\"{\\\"case\\\":%d,\\\"code_sha256\\\":\\\"%s\\\",\\\"checked\\\":%d,\\\"failures\\\":%d,\\\"x\\\":%d,\\\"y\\\":%d,\\\"expected\\\":%d,\\\"actual\\\":%d}\\n\",id,hash,p->checked,p->failures,p->x,p->y,p->expected,p->actual);}\n"
         "int main(void){");
    for(int i=0;i<used;i++) {
        sample*s=samples+i;source_line(out,"{ proof p={0,0,-99,-99,-1,-1};");
        if(!s->kind)fprintf(out,"for(int x=-8;x<=8;x++)observe(&p,x,0,bound(%d,x,%d),case_%d(x));\n",s->policy,s->limit,i);
        else fprintf(out,"for(int x=0;x<=1;x++)for(int y=0;y<=1;y++){calls=0;case_%d(x,y);observe(&p,x,y,guard(%d,x,y),calls);}\n",i,s->policy);
        fprintf(out,"write_proof(%d,\"%s\",&p);}\n",i,s->hash);
    }
    if(equivalent) {
        for(int first=0;first<used;) {
            sample *s=samples+first;
            if(s->kind){first++;continue;}
            int group=s->split?8:4;
            source_line(out,"for(int x=-8;x<=8;x++){");
            for(int j=0;j<group;j+=2) {
                int clean=first+j;
                fprintf(out,"if((case_%d(x)!=case_%d(x))!=(x==%d))return 1;\n",clean,clean+1,s->limit);
                if(j)for(int b=0;b<2;b++)
                    fprintf(out,"if(case_%d(x)!=case_%d(x))return 1;\n",clean+b,first+b);
            }
            source_line(out,"}");first+=group;
        }
    }
    source_line(out,"return ferror(stdout) || fflush(stdout);}");
}
static int number(const char*j,const char*k) {
    long long n;if(nj_int(nj_get(j,k),&n) || n<INT_MIN || n>INT_MAX)die("invalid proof integer");return (int)n;
}
static void read_proofs(const char*path,proof proofs[MAX_CASES],char digest[65]) {
    size_t size;
    char *data=nj_load(path,&size);
    if(!data || size>2048*MAX_CASES || hash_bytes(data,size,digest))die("invalid native proofs");
    char *cursor=data;
    for(int i=0;i<used;i++) {
        char *line=cursor,*nl=strchr(line,'\n');
        size_t n=nl?(size_t)(nl-line):strlen(line);
        if(!n || n>2048)die("incomplete proof stream");
        cursor=line+n;
        if(nl)*cursor++=0;
        const char*end=report_json_end(line,0);if(!end || *nj_ws(end))die("invalid proof JSON");
        char*h=nj_string(nj_get(line,"code_sha256"));
        if(number(line,"case")!=i || !h || strcmp(h,samples[i].hash))die("proof does not match source");
        free(h);
        proof*p=proofs+i;*p=(proof){number(line,"checked"),number(line,"failures"),number(line,"x"),number(line,"y"),number(line,"expected"),number(line,"actual")};
        sample*s=samples+i;
        if(p->checked!=(s->kind?4:17) || p->failures<0 || p->failures>p->checked)die("incomplete domain coverage");
        /* Adjacent rows come from the explicitly generated compliant/mutated
         * bodies. The off-by-one mutation changes only equality; negating a
         * Boolean guard changes all four outcomes, starting at (0,0). */
        int failures=(i%2)*(s->kind?4:1);
        if(p->failures!=failures ||
           (failures && (p->x!=(s->kind?0:s->limit) || p->y!=0)))
            die("receipt disagrees with the generated mutation or its first witness");
        if(p->failures) {
            int expected;
            if(!s->kind) {
                if(p->x< -8 || p->x>8 || p->y)die("invalid bound witness");
                expected=s->policy==0?p->x<s->limit:s->policy==1?p->x<=s->limit:s->policy==2?p->x>s->limit:p->x>=s->limit;
            }else {
                if(p->x<0 || p->x>1 || p->y<0 || p->y>1)die("invalid guard witness");
                const int masks[]={12,3,8,14};expected=(masks[s->policy]>>(2*p->x+p->y))&1;
            }
            if(p->expected!=expected || p->actual==expected || p->actual<0 || p->actual>1)die("invalid counterexample");
        }else if(p->x!= -99 || p->y!= -99 || p->expected!= -1 || p->actual!= -1)die("clean case has a witness");
    }
    if(*cursor)die("extra proof records");
    free(data);
}
static FILE *open_output(const char*dir,const char*name) {
    char path[4096];if(snprintf(path,sizeof(path),"%s/%s",dir,name)>=(int)sizeof(path))die("output path too long");
    FILE*f=fopen(path,"wb");if(!f)die("cannot create output");return f;
}
static void close_output(FILE*f){if(ferror(f) || fclose(f))die("output write failed");}
static void file_hash(const char*dir,const char*name,char out[65]) {
    char path[4096];if(snprintf(path,sizeof(path),"%s/%s",dir,name)>=(int)sizeof(path))die("hash path too long");
    size_t n;char*s=nj_load(path,&n);if(!s || hash_bytes(s,n,out))die("file hash failed");free(s);
}
static void pack(const char*proof_path,const char*dir,int equivalent) {
    proof proofs[MAX_CASES];
    char proofs_hash[65],source_hash[65],staged[65];
    read_proofs(proof_path,proofs,proofs_hash);
    file_hash(dir,"proofs.jsonl",staged);
    if(strcmp(staged,proofs_hash))die("staged proofs differ from the validated input");
    char *generated=NULL;
    size_t size=0;
    FILE *oracle=open_memstream(&generated,&size);
    if(!oracle)die("cannot render the oracle source");
    source(oracle,equivalent);
    close_output(oracle);
    if(hash_bytes(generated,size,source_hash))die("cannot hash the oracle source");
    free(generated);
    file_hash(dir,"oracle.c",staged);
    if(strcmp(staged,source_hash))die("staged oracle differs from the generated source");
    FILE*train=open_output(dir,"train.jsonl"),*eval=open_output(dir,"eval-inputs.jsonl"),*gold=open_output(dir,"eval-expected.jsonl"),*audit=open_output(dir,"audit.jsonl");
    char contexts[MAX_CASES][65];int counts[2][2]={{0}},checked=0;
    am_init();am_persistent_mode(1);
    for(int i=0;i<used;i++) {
        sample*s=samples+i;proof*p=proofs+i;char threshold[24],id[32],pair[32];
        snprintf(threshold,sizeof(threshold),"%d",s->limit);snprintf(id,sizeof(id),equivalent && (s->split || (!s->kind && s->form==2))?"equiv-%03d":"semantic-%03d",i);snprintf(pair,sizeof(pair),"pair-%03d",i/2);
        float config[3]={(float)s->kind,(float)s->policy,(float)p->failures};
        if(am_set_var_array("case_config",config,3) || am_set_var_text("limit_text",threshold) || am_set_var_text("source_code",s->code) ||
           am_exec_file("aml/corpus.aml") || am_exec_file("aml/prepare.aml"))die(am_get_error());
        const char*context=am_get_var_text("review_context"),*prompt=am_get_var_text("prompt"),*rule=am_get_var_text("rule"),*file=am_get_var_text("file");
        const char*label=am_get_var_text("expected"),*completion=am_get_var_text("completion");
        if(!context || !prompt || !rule || !file || !label || !completion || strcmp(label,p->failures?"CONCERN":"CLEAN") || strcmp(completion,p->failures?"A":"B"))die("AML target mismatch");
        if(!strstr(prompt,context) || !strstr(context,rule) || !strstr(context,s->code) || hash_bytes(context,strlen(context),contexts[i]))die("context mismatch");
        for(int j=0;j<i;j++)if(!strcmp(contexts[i],contexts[j]))die("duplicate context");
        FILE*out=s->split?eval:train;
        fputc('{',out);json_field(out,"id",id);fputc(',',out);json_field(out,"file",file);fputc(',',out);json_field(out,"context",context);
        fputc(',',out);json_field(out,"rule_excerpt",rule);fputc(',',out);json_field(out,"change_excerpt",s->code);
        if(!s->split) {
            fputc(',',out);json_field(out,"pair_id",pair);fputc(',',out);json_field(out,"prompt",prompt);fputc(',',out);json_field(out,"completion",completion);
            fprintf(out,",\"completion_token_id\":%d",p->failures?32:33);
        }
        fputs("}\n",out);
        if(s->split) {
            fputc('{',gold);json_field(gold,"id",id);fputs(",\"split\":\"transfer\",",gold);json_field(gold,"family",s->kind?"guard":"boundary");
            fputc(',',gold);json_field(gold,"expected",label);fputs("}\n",gold);
        }
        fputc('{',audit);json_field(audit,"id",id);fputc(',',audit);json_field(audit,"pair_id",pair);fputc(',',audit);json_field(audit,"split",s->split?"eval":"train");
        fputc(',',audit);json_field(audit,"family",s->kind?"guard":"boundary");fprintf(audit,",\"template\":%d,",s->form);json_field(audit,"expected",label);
        fputc(',',audit);json_field(audit,"code_sha256",s->hash);fputc(',',audit);json_field(audit,"context_sha256",contexts[i]);
        fprintf(audit,",\"checked\":%d,\"failures\":%d,\"witness\":",p->checked,p->failures);
        if(p->failures)fprintf(audit,"{\"x\":%d,\"y\":%d,\"expected\":%d,\"actual\":%d}",p->x,p->y,p->expected,p->actual);else fputs("null",audit);
        fputs("}\n",audit);counts[s->split][!!p->failures]++;checked+=p->checked;
    }
    close_output(train);close_output(eval);close_output(gold);close_output(audit);
    if(counts[0][0]!=64 || counts[0][1]!=64 || counts[1][0]!=(equivalent?48:32) || counts[1][1]!=(equivalent?48:32))die("split balance changed");
    FILE*m=open_output(dir,"manifest.json");
    fprintf(m,"{\"schema\":\"%s\",\"train\":128,\"eval\":%d,\"native_checks\":%d,\"train_clean\":64,\"train_concern\":64,\"eval_clean\":%d,\"eval_concern\":%d,\"sha256\":{",equivalent?"jovovich.equivalent-corpus/1":"jovovich.semantic-corpus/1",used-128,checked,counts[1][0],counts[1][1]);
    const char*names[]={"train.jsonl","eval-inputs.jsonl","eval-expected.jsonl","audit.jsonl","oracle.c","proofs.jsonl"};
    for(int i=0;i<6;i++){
        char h[65];
        if(i==4)strcpy(h,source_hash);
        else if(i==5)strcpy(h,proofs_hash);
        else file_hash(dir,names[i],h);
        if(i)fputc(',',m);
        json_field(m,names[i],h);
    }
    fputs("}}\n",m);close_output(m);am_persistent_mode(0);
}
/* Compile beside the pinned equivalent corpus's oracle.c. The driver calls
 * the reviewed function and the independent rule oracle on both inputs. */
static void observation_driver(void) {
    puts("#define main full_domain_oracle\n#include \"oracle.c\"\n#undef main");
    for(int i=0;i<used;i++)if(samples[i].split) {
        char code[JOV_BOUNDARY_CODE_SIZE];
        if(!jov_boundary_code(samples[i].code,code))die("unsupported equivalent case");
        printf("#define accepts canonical_%d\n%s\n#undef accepts\n",i,code);
    }
    puts("int main(void){");
    for(int i=0;i<used;i++) {
        const sample *s=samples+i;
        if(!s->split)continue;
        printf("for(int v=-8;v<=8;v++)if(case_%d(v)!=canonical_%d(v))return 1;\n",i,i);
        printf("{int x=%d;printf(\"{\\\"id\\\":\\\"equiv-%03d\\\",\\\"code_sha256\\\":\\\"%s\\\","
               "\\\"x\\\":%%d,\\\"required\\\":%%d,\\\"returned\\\":%%d,"
               "\\\"adjacent_required\\\":%%d,\\\"adjacent_returned\\\":%%d}\\n\","
               "x,bound(%d,x,x),case_%d(x),bound(%d,x-1,x),case_%d(x-1));}\n",
               s->limit,i,s->hash,s->policy,i,s->policy,i);
    }
    puts("return ferror(stdout)||fflush(stdout);}");
}

static void observed_inputs(const char *receipts,int adjacent) {
    FILE *f=fopen(receipts,"rb");
    if(!f)die("cannot open observation receipts");
    char *line=NULL;size_t cap=0;
    am_init();am_persistent_mode(1);
    for(int i=0;i<used;i++) {
        const sample *s=samples+i;
        if(!s->split)continue;
        ssize_t n=getline(&line,&cap,f);
        const char *end=n>0 && n<1024 && !memchr(line,0,(size_t)n)?report_json_end(line,0):NULL;
        char id[32];snprintf(id,sizeof(id),"equiv-%03d",i);
        if(!end || *nj_ws(end) || !nj_is(nj_get(line,"id"),id) ||
           !nj_is(nj_get(line,"code_sha256"),s->hash) || number(line,"x")!=s->limit)
            die("observation receipt differs from the compiled case");
        int x=s->limit-adjacent;
        int expected=number(line,adjacent?"adjacent_required":"required");
        int actual=number(line,adjacent?"adjacent_returned":"returned");
        int reference=s->policy==0?x<s->limit:s->policy==1?x<=s->limit:s->policy==2?x>s->limit:x>=s->limit;
        if(expected!=reference || (actual!=0 && actual!=1) || ((expected!=actual)!=(!adjacent && i%2)))
            die("observation is inconsistent with the verified mutation");
        char limit[24],at[24];snprintf(limit,sizeof(limit),"%d",s->limit);snprintf(at,sizeof(at),"%d",x);
        float config[]={0,(float)s->policy,0};
        if(am_set_var_array("case_config",config,3) || am_set_var_text("limit_text",limit) ||
           am_set_var_text("source_code",s->code) || am_exec_file("aml/corpus.aml") ||
           am_set_var_text("observation_x",at) || am_set_var_text("observation_expected",expected?"1":"0") ||
           am_set_var_text("observation_actual",actual?"1":"0") || am_exec_file("aml/boundary-observation.aml"))
            die(am_get_error());
        const char *file=am_get_var_text("file"), *context=am_get_var_text("review_context"), *rule=am_get_var_text("rule");
        if(!file || !context || !rule)die("missing observation context");
        fputc('{',stdout);json_field(stdout,"id",id);fputc(',',stdout);json_field(stdout,"file",file);
        fputc(',',stdout);json_field(stdout,"context",context);fputc(',',stdout);json_field(stdout,"rule_excerpt",rule);
        fputc(',',stdout);json_field(stdout,"change_excerpt",s->code);puts("}");
    }
    if(getline(&line,&cap,f)>=0 || ferror(f))die("extra observation receipts");
    free(line);fclose(f);am_persistent_mode(0);
}

int main(int argc,char**argv) {
    const char *program=argv[0];
    int direct=argc>1 && !strcmp(argv[1],"--direct-boundary");
    int equivalent=argc>1 && !strcmp(argv[1],"--equivalent-forms");
    if(direct || equivalent){argc--;argv++;}
    enumerate(direct,equivalent);
    if(equivalent && argc==2 && !strcmp(argv[1],"observation-driver")) {
        observation_driver();return ferror(stdout) || fflush(stdout);
    }
    if(equivalent && argc==4 && !strcmp(argv[1],"observe") &&
       (!strcmp(argv[3],"boundary") || !strcmp(argv[3],"adjacent"))) {
        observed_inputs(argv[2],!strcmp(argv[3],"adjacent"));return ferror(stdout) || fflush(stdout);
    }
    if(argc==2 && !strcmp(argv[1],"source")){source(stdout,equivalent);return ferror(stdout) || fflush(stdout);}
    if(argc==4 && !strcmp(argv[1],"pack")){pack(argv[2],argv[3],equivalent);return 0;}
    fprintf(stderr,"Usage: %s [--direct-boundary|--equivalent-forms] source | pack PROOFS.jsonl OUTPUT_DIRECTORY\n",program);return 2;
}
