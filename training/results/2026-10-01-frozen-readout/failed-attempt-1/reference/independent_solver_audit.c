/* Independent numerical gate; compile with -I PATH_TO_REPO/training -lm. */
#define READOUT_FIT_NO_MAIN
#include "readout_fit.c"
#include <assert.h>

static void near(double a,double b,double tol) {
    if (!isfinite(a)||!isfinite(b)||fabs(a-b)>tol) {
        fprintf(stderr,"independent audit mismatch %.17g %.17g tol %.17g\n",a,b,tol);
        abort();
    }
}

int main(void) {
    int labels[]={0,1,0,1},groups[]={0,0,1,1},pairs[]={0,0,1,1},subset[]={0,0,0,0};
    double x[]={-1,0,1,0,-1,50,1,-50};
    Dataset d={.rows=4,.width=2,.groups=2,.pairs=2,.x=x,.label=labels,.group=groups,.pair=pairs,.subset=subset};
    Prepared p=prepare(&d,1,0);
    near(p.mean[0],0,0);near(p.mean[1],0,0);near(p.global_scale,1,0);
    int y[]={0,1};FitOptions options={.lambda=.01,.tolerance=1e-8,.max_iterations=100};
    Fit f=fit(&p,y,options);assert(f.converged&&f.correct==2);near(f.bias,0,1e-12);near(f.w[1],0,0);
    /* For balanced symmetric x=-1,+1, optimum satisfies lambda*w=1/(1+exp(w)). */
    double lo=0,hi=20;
    for(int it=0;it<100;it++) {double w=.5*(lo+hi);if(.01*w>1/(1+exp(w)))hi=w;else lo=w;}
    near(f.w[0],.5*(lo+hi),2e-6);
    /* Held-out-only coordinate variation must not contribute despite global scaling. */
    near(dot(p.all+2*2,f.w,2)+f.bias,-f.w[0],1e-12);
    near(dot(p.all+3*2,f.w,2)+f.bias,f.w[0],1e-12);
    double old_kernel[4];memcpy(old_kernel,p.kernel,sizeof old_kernel);
    x[4]=-1e9;x[5]=1e15;x[6]=1e12;x[7]=-1e20;
    Prepared q=prepare(&d,1,0);
    assert(!memcmp(old_kernel,q.kernel,sizeof old_kernel));
    assert(!memcmp(p.mean,q.mean,2*sizeof(double))&&!memcmp(p.scale,q.scale,2*sizeof(double)));
    Prepared n=prepare(&d,1,1);
    for(int i=0;i<4;i++)near(n.all[i*2+1],0,0);
    assert(n.active==1);
    /* An independent closed-form value plus centered finite-difference gradients. */
    double w[]={.42,-.13},b=.27,gradient[2],gb,ce;
    double objective=objective_gradient(&p,y,w,b,.07,gradient,&gb,&ce,NULL,NULL);
    double oracle=(log1p(exp(-.42+.27))+log1p(exp(-.42-.27)))/2+.035*(.42*.42+.13*.13);
    near(objective,oracle,1e-14);
    for(int j=0;j<2;j++) {
        double initial=w[j],step=1e-5;w[j]=initial+step;
        double plus=objective_gradient(&p,y,w,b,.07,NULL,NULL,NULL,NULL,NULL);
        w[j]=initial-step;double minus=objective_gradient(&p,y,w,b,.07,NULL,NULL,NULL,NULL,NULL);w[j]=initial;
        near(gradient[j],(plus-minus)/(2*step),1e-9);
    }
    double plus=objective_gradient(&p,y,w,b+1e-5,.07,NULL,NULL,NULL,NULL,NULL);
    double minus=objective_gradient(&p,y,w,b-1e-5,.07,NULL,NULL,NULL,NULL,NULL);
    near(gb,(plus-minus)/2e-5,1e-9);
    free(f.w);free_prepared(&p);free_prepared(&q);free_prepared(&n);
    double zeros[8]={0};d.x=zeros;p=prepare(&d,-1,0);
    f=fit(&p,labels,options);assert(f.converged&&f.iterations==0&&f.correct==2);near(f.ce,log(2),1e-15);near(f.bias,0,0);
    for(int j=0;j<2;j++)near(f.w[j],0,0);
    free(f.w);free_prepared(&p);
    puts("{\"status\":\"pass\",\"checks\":[\"closed_form_symmetric_logistic_optimum\",\"closed_form_logistic_objective\",\"weight_and_intercept_gradient_finite_differences\",\"training_only_normalization_and_kernel\",\"global_constant_coordinate_zero_weight\",\"nuisance_constant_coordinate_zero_heldout\",\"constant_features_zero_tie_clean\"]}");
    return 0;
}
