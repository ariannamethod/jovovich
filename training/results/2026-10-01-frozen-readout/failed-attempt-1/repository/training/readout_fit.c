/* Frozen-state diagnostic only. No model weights or production decisions change.
 * Objective: mean binary logistic loss + lambda/2 * ||w||^2, free intercept.
 * All arithmetic is native float64. Input features alone are float32.
 * Compile: cc -O2 -Wall -Wextra -std=gnu11 training/readout_fit.c -lm -o readout-fit
 */
#include <errno.h>
#include <float.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    int rows, width, groups, pairs;
    double *x;
    int *label, *group, *pair, *subset;
} Dataset;

typedef struct {
    int n, rows, d, active;
    int *train;
    double *x, *all, *mean, *scale, *kernel;
    double global_scale;
} Prepared;

typedef struct {
    double lambda, tolerance;
    int max_iterations;
} FitOptions;

typedef struct {
    double *w, bias, objective, ce, grad_inf, weight_norm;
    int iterations, converged, correct, floors, backtracks;
    const char *status;
} Fit;

static void die(const char *message) {
    fprintf(stderr, "readout-fit: %s\n", message);
    exit(1);
}

static void *allocate(size_t count, size_t width) {
    if (width && count > SIZE_MAX / width) die("allocation size overflow");
    void *p = calloc(count ? count : 1, width);
    if (!p) die("allocation failed");
    return p;
}

static double sigmoid(double x) {
    if (x >= 0) return 1.0 / (1.0 + exp(-x));
    double t = exp(x);
    return t / (1.0 + t);
}

static double softplus(double x) {
    return fmax(x, 0.0) + log1p(exp(-fabs(x)));
}

static double dot(const double *a, const double *b, int n) {
    double sum = 0;
    for (int i = 0; i < n; i++) sum += a[i] * b[i];
    return sum;
}

/* Population statistics use training rows only. Per-feature scaling zeros a
 * training-constant column on all rows. Global scaling preserves its held-out
 * variation, but the fitted weight remains zero in that training-zero column. */
static Prepared prepare(const Dataset *data, int heldout, int per_feature) {
    Prepared p = {0};
    p.rows = data->rows;
    p.d = data->width;
    p.train = allocate(data->rows, sizeof(int));
    for (int i = 0; i < data->rows; i++)
        if (heldout < 0 || data->group[i] != heldout) p.train[p.n++] = i;
    if (p.n < 2) die("a training fold needs at least two examples");
    p.mean = allocate(p.d, sizeof(double));
    p.scale = allocate(p.d, sizeof(double));
    p.x = allocate((size_t)p.n * p.d, sizeof(double));
    p.all = allocate((size_t)p.rows * p.d, sizeof(double));
    p.kernel = allocate((size_t)p.n * p.n, sizeof(double));
    for (int j = 0; j < p.d; j++) {
        for (int i = 0; i < p.n; i++) p.mean[j] += data->x[(size_t)p.train[i]*p.d+j];
        p.mean[j] /= p.n;
        for (int i = 0; i < p.n; i++) {
            double a = data->x[(size_t)p.train[i]*p.d+j] - p.mean[j];
            p.scale[j] += a*a;
        }
        p.scale[j] /= p.n;
        if (p.scale[j] > 0) p.active++;
        p.global_scale += p.scale[j];
        p.scale[j] = sqrt(p.scale[j]);
    }
    p.global_scale = sqrt(p.global_scale);
    double active_root = sqrt((double)p.active);
    for (int i = 0; i < p.rows; i++) for (int j = 0; j < p.d; j++) {
        double scale = per_feature ? p.scale[j] * active_root : p.global_scale;
        if (scale > 0)
            p.all[(size_t)i*p.d+j] = (data->x[(size_t)i*p.d+j] - p.mean[j]) / scale;
    }
    for (int i = 0; i < p.n; i++)
        memcpy(p.x+(size_t)i*p.d, p.all+(size_t)p.train[i]*p.d, (size_t)p.d*sizeof(double));
    for (int i = 0; i < p.n; i++) for (int j = 0; j <= i; j++) {
        double value = dot(p.x+(size_t)i*p.d, p.x+(size_t)j*p.d, p.d);
        p.kernel[(size_t)i*p.n+j] = p.kernel[(size_t)j*p.n+i] = value;
    }
    return p;
}

static void free_prepared(Prepared *p) {
    free(p->train); free(p->x); free(p->all); free(p->mean); free(p->scale); free(p->kernel);
    memset(p, 0, sizeof(*p));
}

static double objective_gradient(const Prepared *p, const int *y,
                                 const double *w, double bias, double lambda,
                                 double *gradient, double *gb, double *ce,
                                 double *logits, int *correct) {
    double loss = 0, intercept_gradient = 0;
    if (correct) *correct = 0;
    if (gradient) for (int j = 0; j < p->d; j++) gradient[j] = lambda*w[j];
    for (int i = 0; i < p->n; i++) {
        const double *x = p->x+(size_t)i*p->d;
        double a = dot(x, w, p->d) + bias;
        double r = (y[i] ? -sigmoid(-a) : sigmoid(a)) / p->n;
        loss += softplus(y[i] ? -a : a) / p->n;
        intercept_gradient += r;
        if (gradient) for (int j = 0; j < p->d; j++) gradient[j] += r*x[j];
        if (logits) logits[i] = a;
        if (correct) *correct += ((a > 0) == y[i]);
    }
    if (gb) *gb = intercept_gradient;
    if (ce) *ce = loss;
    return loss + 0.5*lambda*dot(w, w, p->d);
}

/* In-place Cholesky, lower triangle. No unchecked inverse is formed. */
static int cholesky(double *a, int n) {
    for (int i = 0; i < n; i++) for (int j = 0; j <= i; j++) {
        double v = a[(size_t)i*n+j];
        for (int k = 0; k < j; k++) v -= a[(size_t)i*n+k]*a[(size_t)j*n+k];
        if (i == j) {
            if (!(v > 0) || !isfinite(v)) return 0;
            a[(size_t)i*n+j] = sqrt(v);
        } else a[(size_t)i*n+j] = v / a[(size_t)j*n+j];
    }
    return 1;
}

static void chol_solve(const double *l, double *b, int n) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < i; j++) b[i] -= l[(size_t)i*n+j]*b[j];
        b[i] /= l[(size_t)i*n+i];
    }
    for (int i = n-1; i >= 0; i--) {
        for (int j = i+1; j < n; j++) b[i] -= l[(size_t)j*n+i]*b[j];
        b[i] /= l[(size_t)i*n+i];
    }
}

/* IRLS Newton target in sample space. The n-by-n positive-definite system
 * is (XX' + n*lambda*diag(1/v)) alpha + b*1 = t, 1'alpha = 0.
 * This is the exact primal Newton step when curvature is above the floor.
 * The floor affects only the search direction; loss and stopping gradient
 * always use the exact logistic objective. Lambda is strictly positive. */
static int newton_target(const Prepared *p, const int *y, const double *logits,
                         double lambda, double *next_w, double *next_b,
                         double *matrix, double *a, double *c, int *floors) {
    memcpy(matrix, p->kernel, (size_t)p->n*p->n*sizeof(double));
    for (int i = 0; i < p->n; i++) {
        double v = sigmoid(logits[i])*sigmoid(-logits[i]);
        if (v < 1e-12) { v = 1e-12; (*floors)++; }
        double negative_residual = y[i] ? sigmoid(-logits[i]) : -sigmoid(logits[i]);
        matrix[(size_t)i*p->n+i] += p->n*lambda/v;
        a[i] = logits[i] + negative_residual/v;
        c[i] = 1;
    }
    if (!cholesky(matrix, p->n)) return 0;
    chol_solve(matrix, a, p->n);
    chol_solve(matrix, c, p->n);
    double sum_a = 0, sum_c = 0;
    for (int i = 0; i < p->n; i++) { sum_a += a[i]; sum_c += c[i]; }
    if (!(sum_c > 0) || !isfinite(sum_a) || !isfinite(sum_c)) return 0;
    *next_b = sum_a/sum_c;
    memset(next_w, 0, (size_t)p->d*sizeof(double));
    for (int i = 0; i < p->n; i++) {
        double alpha = a[i] - *next_b*c[i];
        for (int j = 0; j < p->d; j++) next_w[j] += p->x[(size_t)i*p->d+j]*alpha;
    }
    return isfinite(*next_b);
}

static Fit fit(const Prepared *p, const int *y, FitOptions options) {
    Fit f = {.status="iteration_limit"};
    f.w = allocate(p->d, sizeof(double));
    double *gradient = allocate(p->d, sizeof(double));
    double *next = allocate(p->d, sizeof(double));
    double *trial = allocate(p->d, sizeof(double));
    double *logits = allocate(p->n, sizeof(double));
    double *matrix = allocate((size_t)p->n*p->n, sizeof(double));
    double *a = allocate(p->n, sizeof(double));
    double *c = allocate(p->n, sizeof(double));
    for (int iteration = 0; iteration <= options.max_iterations; iteration++) {
        double gb = 0;
        f.objective = objective_gradient(p, y, f.w, f.bias, options.lambda,
                                        gradient, &gb, &f.ce, logits, &f.correct);
        f.grad_inf = fabs(gb);
        int finite = isfinite(gb) && isfinite(f.bias);
        for (int j = 0; j < p->d; j++) {
            finite &= isfinite(gradient[j]) && isfinite(f.w[j]);
            f.grad_inf = fmax(f.grad_inf, fabs(gradient[j]));
        }
        for (int i = 0; i < p->n; i++) finite &= isfinite(logits[i]);
        if (!finite || !isfinite(f.objective) || !isfinite(f.grad_inf)) { f.status="nonfinite_objective"; break; }
        if (f.grad_inf <= options.tolerance) { f.converged=1; f.status="gradient_tolerance"; break; }
        if (iteration == options.max_iterations) break;
        double next_b = 0;
        if (!newton_target(p, y, logits, options.lambda, next, &next_b, matrix, a, c, &f.floors)) {
            f.status="cholesky_failed"; break;
        }
        double gb_delta = next_b-f.bias;
        double directional = gb*gb_delta;
        for (int j = 0; j < p->d; j++) directional += gradient[j]*(next[j]-f.w[j]);
        if (!(directional < 0) || !isfinite(directional)) { f.status="non_descent_direction"; break; }
        int accepted = 0;
        double step = 1.0;
        for (int backtrack = 0; backtrack <= 60; backtrack++) {
            for (int j = 0; j < p->d; j++) trial[j] = f.w[j]+step*(next[j]-f.w[j]);
            double trial_bias = f.bias+step*gb_delta;
            double trial_objective = objective_gradient(p,y,trial,trial_bias,options.lambda,NULL,NULL,NULL,NULL,NULL);
            if (isfinite(trial_objective) && trial_objective <= f.objective+1e-4*step*directional) {
                memcpy(f.w,trial,(size_t)p->d*sizeof(double)); f.bias=trial_bias;
                f.iterations++; accepted=1; break;
            }
            if (backtrack < 60) { step *= 0.5; f.backtracks++; }
        }
        if (!accepted) { f.status="line_search_failed"; break; }
    }
    f.weight_norm = sqrt(dot(f.w,f.w,p->d));
    free(gradient); free(next); free(trial); free(logits); free(matrix); free(a); free(c);
    return f;
}

#ifndef READOUT_FIT_NO_MAIN
static uint32_t read_u32(FILE *file) {
    unsigned char b[4];
    if (fread(b,1,4,file)!=4) die("truncated matrix header");
    return (uint32_t)b[0] | (uint32_t)b[1]<<8 | (uint32_t)b[2]<<16 | (uint32_t)b[3]<<24;
}

static void ensure_eof(FILE *file, int binary) {
    int c;
    while ((c=fgetc(file))!=EOF)
        if (binary || (c!=' ' && c!='\n' && c!='\r' && c!='\t')) die("unexpected trailing input");
    if (ferror(file)) die("input read error");
}

static Dataset read_dataset(const char *matrix_path, const char *metadata_path) {
    Dataset d = {0};
    FILE *meta=fopen(metadata_path,"r");
    if (!meta) die("cannot open metadata");
    char magic[64];
    if (fscanf(meta,"%63s",magic)!=1 || strcmp(magic,"JOVOVICH_READOUT_V1")) die("wrong metadata magic");
    if (fscanf(meta,"%d %d %d %d",&d.rows,&d.width,&d.groups,&d.pairs)!=4 ||
        d.rows<4 || d.rows>10000 || d.width<1 || d.width>100000 ||
        d.groups<2 || d.groups>d.rows/2 || d.pairs!=d.rows/2 || d.rows%2)
        die("invalid metadata dimensions");
    d.label=allocate(d.rows,sizeof(int)); d.group=allocate(d.rows,sizeof(int));
    d.pair=allocate(d.rows,sizeof(int)); d.subset=allocate(d.rows,sizeof(int));
    int *group_counts=allocate(d.groups,sizeof(int));
    int *pair_counts=allocate(d.pairs,sizeof(int));
    int *pair_first=allocate(d.pairs,sizeof(int));
    for (int i=0;i<d.rows;i++) {
        if (fscanf(meta,"%d %d %d %d",&d.label[i],&d.group[i],&d.pair[i],&d.subset[i])!=4 ||
            d.label[i]<0 || d.label[i]>1 || d.group[i]<0 || d.group[i]>=d.groups ||
            d.pair[i]<0 || d.pair[i]>=d.pairs || d.subset[i]<0 || d.subset[i]>1)
            die("invalid metadata row");
        group_counts[d.group[i]]++;
        int pair=d.pair[i];
        if (++pair_counts[pair]==1) pair_first[pair]=i;
        else if (pair_counts[pair]==2) {
            int first=pair_first[pair];
            if (d.label[first]==d.label[i] || d.group[first]!=d.group[i] || d.subset[first]!=d.subset[i])
                die("pair must contain opposite labels in one family and subset");
        } else die("a pair has more than two examples");
    }
    ensure_eof(meta,0); fclose(meta);
    for (int i=0;i<d.groups;i++) if (group_counts[i]<2 || group_counts[i]%2) die("missing or unbalanced family");
    for (int i=0;i<d.pairs;i++) if (pair_counts[i]!=2) die("missing or incomplete pair");
    free(group_counts); free(pair_counts); free(pair_first);
    FILE *file=fopen(matrix_path,"rb");
    if (!file) die("cannot open feature matrix");
    unsigned char header[8];
    const unsigned char expected[8]={'J','V','R','F','1',0,0,0};
    if (fread(header,1,8,file)!=8 || memcmp(header,expected,8)) die("wrong feature matrix magic");
    uint32_t rows=read_u32(file), width=read_u32(file);
    if (rows!=(uint32_t)d.rows || width!=(uint32_t)d.width) die("matrix and metadata dimensions disagree");
    if (sizeof(float)!=4 || FLT_RADIX!=2 || FLT_MANT_DIG!=24) die("IEEE-754 float32 required");
    d.x=allocate((size_t)d.rows*d.width,sizeof(double));
    for (size_t i=0;i<(size_t)d.rows*d.width;i++) {
        uint32_t bits=read_u32(file); float value;
        memcpy(&value,&bits,4);
        if (!isfinite(value)) die("nonfinite feature");
        d.x[i]=value;
    }
    ensure_eof(file,1); fclose(file);
    return d;
}

static unsigned char *read_masks(const char *path,int groups,int *count) {
    FILE *file=fopen(path,"r");
    if (!file) die("cannot open permutation masks");
    char magic[64]; int columns;
    if (fscanf(file,"%63s",magic)!=1 || strcmp(magic,"JOVOVICH_MASKS_V1") ||
        fscanf(file,"%d %d",count,&columns)!=2 || *count<1 || *count>10000 || columns!=groups)
        die("invalid permutation mask header");
    unsigned char *masks=allocate((size_t)*count*groups,sizeof(unsigned char));
    for (int i=0;i<*count;i++) {
        int nonzero=0;
        for (int j=0;j<groups;j++) {
            int value=fgetc(file);
            if (j==0) while(value==' ' || value=='\n' || value=='\r' || value=='\t') value=fgetc(file);
            if (value!='0' && value!='1') die("mask must be a full contiguous bitstring");
            masks[(size_t)i*groups+j]=(unsigned char)(value-'0'); nonzero|=value=='1';
        }
        int end=fgetc(file);
        if (end!=EOF && end!=' ' && end!='\n' && end!='\r' && end!='\t') die("mask is too long");
        if (!nonzero) die("identity mask is reserved for observed labels");
        for (int k=0;k<i;k++) if (!memcmp(masks+(size_t)i*groups,masks+(size_t)k*groups,groups))
            die("duplicate permutation mask");
    }
    ensure_eof(file,0); fclose(file);
    return masks;
}

static double parse_positive(const char *text) {
    char *end=NULL; errno=0; double x=strtod(text,&end);
    if (errno || !end || *end || !(x>0) || !isfinite(x)) die("expected a finite positive numeric option");
    return x;
}

static void output_fit(FILE *out,const Dataset *d,const Prepared *p,const int *y,
                       const unsigned char *mask,int permutation,int heldout,
                       int interpolation,FitOptions options,const Fit *f) {
    fprintf(out,"{\"type\":\"fit\",\"mode\":\"%s\",\"permutation\":%d,\"heldout_family\":%d,"
        "\"train_rows\":%d,\"lambda\":%.17g,\"converged\":%s,\"status\":\"%s\","
        "\"iterations\":%d,\"objective\":%.17g,\"train_ce\":%.17g,\"gradient_inf\":%.17g,"
        "\"train_correct\":%d,\"penalty\":%.17g,\"weight_norm\":%.17g,\"active_columns\":%d,"
        "\"global_rms\":%.17g,\"curvature_floors\":%d,\"backtracks\":%d,\"predictions\":[",
        interpolation?"interpolation":"heldout",permutation,heldout,p->n,options.lambda,
        f->converged?"true":"false",f->status,f->iterations,f->objective,f->ce,f->grad_inf,
        f->correct,0.5*options.lambda*f->weight_norm*f->weight_norm,f->weight_norm,p->active,p->global_scale,f->floors,f->backtracks);
    int first=1;
    for (int i=0;i<d->rows;i++) if (interpolation || d->group[i]==heldout) {
        double score=dot(p->all+(size_t)i*p->d,f->w,p->d)+f->bias;
        int label=d->label[i]^(mask?mask[d->group[i]]:0);
        fprintf(out,"%s{\"row\":%d,\"family\":%d,\"pair\":%d,\"subset\":%d,"
            "\"label\":%d,\"score\":%.17g,\"probability\":%.17g,\"prediction\":%d}",
            first?"":",",i,d->group[i],d->pair[i],d->subset[i],label,score,sigmoid(score),score>0);
        first=0;
    }
    (void)y;
    fprintf(out,"]}\n");
    if (ferror(out)) die("output write failed");
}

static void output_normalization(FILE *out,const Prepared *p,int heldout) {
    fprintf(out,"{\"type\":\"normalization\",\"heldout_family\":%d,\"active_columns\":%d,"
        "\"global_rms\":%.17g,\"training_rows\":[",heldout,p->active,p->global_scale);
    for(int i=0;i<p->n;i++) fprintf(out,"%s%d",i?",":"",p->train[i]);
    fprintf(out,"],\"mean\":[");
    for(int j=0;j<p->d;j++) fprintf(out,"%s%.17g",j?",":"",p->mean[j]);
    fprintf(out,"],\"feature_population_std\":[");
    for(int j=0;j<p->d;j++) fprintf(out,"%s%.17g",j?",":"",p->scale[j]);
    fprintf(out,"]}\n");
    if (ferror(out)) die("output write failed");
}

int main(int argc,char **argv) {
    const char *matrix=NULL,*metadata=NULL,*masks_path=NULL,*output=NULL,*normalization=NULL;
    FitOptions options={.lambda=.01,.tolerance=1e-8,.max_iterations=100};
    double interpolation_lambda=1e-8;
    for (int i=1;i<argc;i++) {
        if (!strcmp(argv[i],"--help")) {
            puts("readout-fit --matrix F --metadata F --masks F --output F\n"
                 "  --normalization centered-rms|per-feature-rms [--lambda .01]\n"
                 "  [--interpolation-lambda 1e-8] [--gradient-tolerance 1e-8] [--max-iterations 100]\n"
                 "Runs all leave-family-out masks plus observed/first-mask interpolation; output must not exist.");
            return 0;
        }
        if (i+1>=argc) die("missing option value");
        const char *key=argv[i],*value=argv[++i];
        if (!strcmp(key,"--matrix")) matrix=value;
        else if (!strcmp(key,"--metadata")) metadata=value;
        else if (!strcmp(key,"--masks")) masks_path=value;
        else if (!strcmp(key,"--output")) output=value;
        else if (!strcmp(key,"--normalization")) normalization=value;
        else if (!strcmp(key,"--lambda")) options.lambda=parse_positive(value);
        else if (!strcmp(key,"--interpolation-lambda")) interpolation_lambda=parse_positive(value);
        else if (!strcmp(key,"--gradient-tolerance")) options.tolerance=parse_positive(value);
        else if (!strcmp(key,"--max-iterations")) {
            double count=parse_positive(value);
            if (count>100000 || floor(count)!=count) die("invalid iteration limit");
            options.max_iterations=(int)count;
        } else die("unknown option");
    }
    if (!matrix || !metadata || !masks_path || !output || !normalization) die("missing required option; see --help");
    int per_feature=!strcmp(normalization,"per-feature-rms");
    if (!per_feature && strcmp(normalization,"centered-rms")) die("unknown normalization mode");
    Dataset d=read_dataset(matrix,metadata);
    int mask_count=0;
    unsigned char *masks=read_masks(masks_path,d.groups,&mask_count);
    FILE *out=fopen(output,"wx");
    if (!out) die("cannot exclusively create output (does it already exist?)");
    fprintf(out,"{\"type\":\"configuration\",\"schema_version\":1,\"rows\":%d,\"width\":%d,"
        "\"families\":%d,\"pairs\":%d,\"permutations\":%d,\"normalization\":\"%s\","
        "\"lambda\":%.17g,\"interpolation_lambda\":%.17g,\"gradient_tolerance\":%.17g,"
        "\"max_iterations\":%d,\"intercept_penalized\":false,\"positive_class\":\"concern\","
        "\"tie_class\":\"clean\",\"armijo_c1\":0.0001,\"maximum_halvings\":60,"
        "\"direction_curvature_floor\":1e-12,\"interpolation_mask_indices\":[-1,0]}\n",
        d.rows,d.width,d.groups,d.pairs,mask_count,normalization,options.lambda,
        interpolation_lambda,options.tolerance,options.max_iterations);
    int total=0,failed=0;
    for (int heldout=0;heldout<d.groups;heldout++) {
        Prepared p=prepare(&d,heldout,per_feature);
        output_normalization(out,&p,heldout);
        int *y=allocate(p.n,sizeof(int));
        for (int permutation=-1;permutation<mask_count;permutation++) {
            const unsigned char *mask=permutation<0?NULL:masks+(size_t)permutation*d.groups;
            for (int i=0;i<p.n;i++) {
                int row=p.train[i]; y[i]=d.label[row]^(mask?mask[d.group[row]]:0);
            }
            Fit f=fit(&p,y,options); total++; failed+=!f.converged;
            output_fit(out,&d,&p,y,mask,permutation,heldout,0,options,&f); free(f.w);
        }
        free(y); free_prepared(&p);
    }
    Prepared p=prepare(&d,-1,per_feature);
    output_normalization(out,&p,-1);
    int *y=allocate(p.n,sizeof(int));
    FitOptions capacity_options=options; capacity_options.lambda=interpolation_lambda;
    for (int permutation=-1;permutation<=0;permutation++) {
        const unsigned char *mask=permutation<0?NULL:masks;
        for (int i=0;i<p.n;i++) y[i]=d.label[i]^(mask?mask[d.group[i]]:0);
        Fit f=fit(&p,y,capacity_options); total++; failed+=!f.converged;
        output_fit(out,&d,&p,y,mask,permutation,-1,1,capacity_options,&f); free(f.w);
    }
    fprintf(out,"{\"type\":\"completion\",\"fits\":%d,\"failed_fits\":%d,\"all_converged\":%s}\n",
        total,failed,failed?"false":"true");
    if (fclose(out)) die("output close failed");
    free(y); free_prepared(&p); free(masks);
    free(d.x); free(d.label); free(d.group); free(d.pair); free(d.subset);
    return failed?2:0;
}
#endif
