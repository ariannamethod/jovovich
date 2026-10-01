#define READOUT_FIT_NO_MAIN
#include "../training/readout_fit.c"
#include <assert.h>

static Dataset small_data(void) {
    Dataset d={.rows=8,.width=3,.groups=4,.pairs=4};
    d.x=allocate((size_t)d.rows*d.width,sizeof(double));
    d.label=allocate(d.rows,sizeof(int)); d.group=allocate(d.rows,sizeof(int));
    d.pair=allocate(d.rows,sizeof(int)); d.subset=allocate(d.rows,sizeof(int));
    for(int i=0;i<d.rows;i++) {
        d.label[i]=i%2; d.group[i]=d.pair[i]=i/2;
        d.x[i*3]=i*.3-1;
        d.x[i*3+1]=sin(i*.8);
        d.x[i*3+2]=i%3-1;
    }
    return d;
}

static void free_data(Dataset *d) {
    free(d->x); free(d->label); free(d->group); free(d->pair); free(d->subset);
}

static void close_number(double a,double b,double tolerance) {
    if (!(isfinite(a) && isfinite(b) && fabs(a-b)<=tolerance)) {
        fprintf(stderr,"readout numeric mismatch %.17g vs %.17g (tol %.3g)\n",a,b,tolerance);
        abort();
    }
}

static void derivatives_and_dense_newton(void) {
    Dataset d=small_data(); Prepared p=prepare(&d,-1,0);
    double w[3]={.7,-.3,.2},b=-.4,gradient[3],gb,logits[8],ce;
    double lambda=.07;
    objective_gradient(&p,d.label,w,b,lambda,gradient,&gb,&ce,logits,NULL);
    double h=1e-5;
    for(int j=0;j<4;j++) {
        double *v=j<3?&w[j]:&b;
        *v+=h; double plus=objective_gradient(&p,d.label,w,b,lambda,NULL,NULL,NULL,NULL,NULL);
        *v-=2*h; double minus=objective_gradient(&p,d.label,w,b,lambda,NULL,NULL,NULL,NULL,NULL);
        *v+=h; close_number((plus-minus)/(2*h),j<3?gradient[j]:gb,2e-10);
    }
    /* Independent primal 4x4 Hessian oracle against the sample-space solver. */
    double hessian[16]={0},delta[4]={gradient[0],gradient[1],gradient[2],gb};
    for(int j=0;j<3;j++) hessian[j*4+j]=lambda;
    for(int i=0;i<p.n;i++) {
        double x[4]={p.x[i*3],p.x[i*3+1],p.x[i*3+2],1};
        double probability=1/(1+exp(-logits[i]));
        for(int j=0;j<4;j++) for(int k=0;k<4;k++)
            hessian[j*4+k]+=probability*(1-probability)*x[j]*x[k]/p.n;
    }
    assert(cholesky(hessian,4)); chol_solve(hessian,delta,4);
    double next[3],next_b,matrix[64],a[8],c[8];int floors=0;
    assert(newton_target(&p,d.label,logits,lambda,next,&next_b,matrix,a,c,&floors));
    for(int j=0;j<3;j++) close_number(next[j],w[j]-delta[j],2e-14);
    close_number(next_b,b-delta[3],2e-14); assert(!floors);
    /* Large logits must remain finite without computing exp(1000). */
    close_number(softplus(1000),1000,0); close_number(softplus(-1000),0,0);
    b=1000;
    double value=objective_gradient(&p,d.label,w,b,lambda,gradient,&gb,NULL,NULL,NULL);
    assert(isfinite(value) && isfinite(gb));
    for(int j=0;j<3;j++) assert(isfinite(gradient[j]));
    free_prepared(&p); free_data(&d);
}

static void heldout_isolation(void) {
    Dataset d=small_data();
    /* Column two is constant in the training rows, nonconstant only held-out. */
    for(int i=0;i<d.rows;i++) d.x[i*3+2]=d.group[i]==2?i:7;
    for(int normalization=0;normalization<2;normalization++) {
        Prepared before=prepare(&d,2,normalization);
        double *saved=allocate((size_t)d.rows*d.width,sizeof(double));
        memcpy(saved,d.x,(size_t)d.rows*d.width*sizeof(double));
        for(int i=0;i<d.rows;i++) if(d.group[i]==2) {
            for(int j=0;j<d.width;j++) d.x[i*3+j]=1e20*(j+1);
            d.label[i]^=1;
        }
        Prepared after=prepare(&d,2,normalization);
        assert(before.n==6 && after.n==6 && before.active==2 && after.active==2);
        assert(!memcmp(before.x,after.x,(size_t)before.n*before.d*sizeof(double)));
        assert(!memcmp(before.mean,after.mean,(size_t)before.d*sizeof(double)));
        assert(!memcmp(before.scale,after.scale,(size_t)before.d*sizeof(double)));
        close_number(before.global_scale,after.global_scale,0);
        int y[6]; for(int i=0;i<6;i++) y[i]=d.label[before.train[i]];
        FitOptions options={.lambda=.01,.tolerance=1e-8,.max_iterations=100};
        Fit first=fit(&before,y,options),second=fit(&after,y,options);
        assert(first.converged && second.converged);
        assert(!memcmp(first.w,second.w,3*sizeof(double)));
        close_number(first.bias,second.bias,0); close_number(first.w[2],0,0);
        if(normalization) for(int i=0;i<d.rows;i++) close_number(after.all[i*3+2],0,0);
        memcpy(d.x,saved,(size_t)d.rows*d.width*sizeof(double));
        for(int i=0;i<d.rows;i++) if(d.group[i]==2) d.label[i]^=1;
        free(saved);free(first.w);free(second.w);free_prepared(&before);free_prepared(&after);
    }
    free_data(&d);
}

static void constants_and_convergence_gates(void) {
    Dataset d=small_data();for(int i=0;i<24;i++) d.x[i]=3;
    for(int mode=0;mode<2;mode++) {
        Prepared p=prepare(&d,-1,mode);
        assert(p.global_scale==0 && p.active==0);
        for(int i=0;i<24;i++) assert(p.x[i]==0);
        FitOptions options={.lambda=.01,.tolerance=1e-8,.max_iterations=100};
        Fit balanced=fit(&p,d.label,options);
        assert(balanced.converged && balanced.iterations==0 && balanced.correct==4);
        close_number(balanced.bias,0,0); close_number(balanced.ce,log(2),1e-15);
        int unbalanced[]={1,1,1,1,1,1,0,0};
        Fit unequal=fit(&p,unbalanced,options);
        assert(unequal.converged);close_number(unequal.bias,log(3),1e-7);
        /* The final update counts: max_iterations=1 must not claim convergence. */
        options.max_iterations=1;
        Fit incomplete=fit(&p,unbalanced,options);
        assert(!incomplete.converged && incomplete.iterations==1 && incomplete.grad_inf>options.tolerance);
        close_number(incomplete.bias,1,1e-14);
        double expected_gradient=fabs(sigmoid(1)-.75);
        close_number(incomplete.grad_inf,expected_gradient,1e-15);
        free(balanced.w);free(unequal.w);free(incomplete.w);free_prepared(&p);
    }
    free_data(&d);
}

static void high_dimensional_weak_ridge(void) {
    Dataset d={.rows=52,.width=896,.groups=20,.pairs=26};
    d.x=allocate((size_t)d.rows*d.width,sizeof(double));
    d.label=allocate(d.rows,sizeof(int));d.group=allocate(d.rows,sizeof(int));
    d.pair=allocate(d.rows,sizeof(int));d.subset=allocate(d.rows,sizeof(int));
    for(int i=0;i<52;i++) {
        d.label[i]=i%2;d.pair[i]=i/2;d.group[i]=i<28?i/2:14+(i-28)/4;
        for(int j=0;j<896;j++) {
            /* Mostly duplicated/near-collinear columns plus per-row coordinates. */
            double common=.04*(d.label[i]*2-1)*((j%7)-3)+.003*sin(d.group[i]+j%7);
            d.x[(size_t)i*896+j]=common+(j==i?.2:0)+1e-10*cos(i+j);
        }
    }
    Prepared p=prepare(&d,-1,0);
    FitOptions weak={.lambda=1e-8,.tolerance=1e-8,.max_iterations=100};
    int shuffled[52];for(int i=0;i<52;i++) shuffled[i]=d.label[i]^(d.group[i]%2);
    Fit truth=fit(&p,d.label,weak),shuffle=fit(&p,shuffled,weak);
    assert(truth.converged && shuffle.converged);
    assert(truth.correct==52 && shuffle.correct==52 && truth.ce<.001 && shuffle.ce<.001);
    FitOptions main={.lambda=.01,.tolerance=1e-8,.max_iterations=100};
    Fit regular=fit(&p,d.label,main);assert(regular.converged && regular.correct==52);
    /* A fitted stationary point is better than the same point plus a perturbation. */
    double reference=regular.objective;regular.w[8]+=.05;
    double perturbed=objective_gradient(&p,d.label,regular.w,regular.bias,main.lambda,NULL,NULL,NULL,NULL,NULL);
    assert(perturbed>reference);
    free(truth.w);free(shuffle.w);free(regular.w);free_prepared(&p);
    /* The nuisance view has mixed scales and training-constant columns. */
    free(d.x);d.width=7;d.x=allocate(52*7,sizeof(double));
    for(int i=0;i<52;i++) for(int j=0;j<7;j++)
        d.x[i*7+j]=j==6?1000:((i+3*j)%11)*pow(10,j-3);
    Prepared nuisance=prepare(&d,19,1);
    assert(nuisance.active==6);
    int y[48];assert(nuisance.n==48);
    for(int i=0;i<48;i++) y[i]=d.label[nuisance.train[i]];
    Fit nuisance_fit=fit(&nuisance,y,main),nuisance_weak=fit(&nuisance,y,weak);
    assert(nuisance_fit.converged && nuisance_weak.converged);
    free(nuisance_fit.w);free(nuisance_weak.w);free_prepared(&nuisance);free_data(&d);
}

int main(void) {
    derivatives_and_dense_newton(); heldout_isolation();
    constants_and_convergence_gates(); high_dimensional_weak_ridge();
    puts("readout: derivatives, primal Newton, fold isolation, constants, convergence and weak ridge passed");
    return 0;
}
