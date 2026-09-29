#define main mlp_trainer_main
#include "../training/train_mlp.c"
#undef main
#include <assert.h>

enum { PARAMS = 6, ELEMENTS = 54, STEPS = 40 };

static void fill_fixture(nt_tensor *t, float scale, int shift) {
    for (int i = 0; i < t->len; i++)
        t->data[i] = scale * (float)(((i * 7 + shift) % 17) - 8);
}

static void init_fixture(mlp_bank *b, mlp_example *ex) {
    *b = (mlp_bank){.E=4, .F=5, .V=7, .layer=1};
    b->wg=tensor(b->F,b->E); b->wu=tensor(b->F,b->E);
    b->wd=tensor(b->E,b->F); b->head=tensor(b->V,b->E);
    b->norm=tensor(1,b->E); b->ffn_norm=tensor(1,b->E); b->bias=tensor(1,b->E);
    fill_fixture(b->wg,.07f,2); fill_fixture(b->wu,.06f,3);
    fill_fixture(b->wd,.08f,4); fill_fixture(b->head,.11f,5);
    for (int i = 0; i < b->E; i++) {
        b->norm->data[i]=.8f+.1f*i;
        b->ffn_norm->data[i]=1.1f-.05f*i;
        b->bias->data[i]=.01f*(i-2);
    }
    for (int j = 0; j < 3; j++) {
        int rc = nt_lora_init(&b->adapters[j], j==2?b->F:b->E, j==2?b->E:b->F, 2, 4);
        assert(rc == 0);
        fill_fixture(b->adapters[j].A,.035f,1+j);
        nt_tensor_fill(b->adapters[j].B,0);
    }
    *ex = (mlp_example){0};
    ex->cache.n=3; ex->cache.z=tensor(3,b->E); ex->cache.targets=tensor(3,1);
    fill_fixture(ex->cache.z,.12f,1);
    for (int i = 0; i < 3; i++) ex->cache.targets->data[i]=(float)(i*2+1);
    prepare_cache(b,&ex->cache);
}

static void free_fixture(mlp_bank *b, mlp_example *ex) {
    /* Restore the parameter count so destroy releases the persistent moments. */
    nt_tape_start();
    for (int j = 0; j < 3; j++) {
        nt_tape_param(b->adapters[j].A);
        nt_tape_param(b->adapters[j].B);
    }
    nt_tape_destroy();
    for (int j = 0; j < 3; j++) nt_lora_free(&b->adapters[j]);
    nt_tensor_free(b->wg); nt_tensor_free(b->wu); nt_tensor_free(b->wd);
    nt_tensor_free(b->head); nt_tensor_free(b->norm);
    nt_tensor_free(b->ffn_norm); nt_tensor_free(b->bias);
    batch_free(&ex->cache);
}

int main(void) {
    float final[2][ELEMENTS], max_update_error=0, max_norm_error=0;
    int updates=0, clipped_steps=0;
    const float lr=.003f, clip=.01f, beta1=.9f, beta2=.999f;
    for (int interleave = 0; interleave < 2; interleave++) {
        mlp_bank b;
        mlp_example ex;
        init_fixture(&b,&ex);
        float ref_m[ELEMENTS]={0}, ref_v[ELEMENTS]={0};
        nt_tensor *params[PARAMS];
        for (int j = 0; j < PARAMS; j++)
            params[j] = j%2 ? b.adapters[j/2].B : b.adapters[j/2].A;

        for (int step = 0; step < STEPS; step++) {
            int n=1+step%3, slots[PARAMS];
            token_row order[3];
            for (int i = 0; i < n; i++) order[i]=(token_row){0,(i+step)%3};
            mlp_batch s = gather(&b,&ex,order,n);
            nt_tape_start();
            int ce = mlp_forward(&b,&s,1,NULL,NULL,slots);
            nt_tape *t = nt_tape_get();
            assert(t->n_params == PARAMS);
            assert(isfinite(t->entries[ce].output->data[0]));
            nt_tape_backward(ce);

            double sumsq=0;
            float raw[ELEMENTS];
            int p=0;
            for (int j = 0; j < PARAMS; j++) {
                nt_tape_entry *e = &t->entries[slots[j]];
                assert(e->slot == j && e->output == params[j]);
                assert(e->grad && e->grad->len == params[j]->len);
                assert(t->adam[j].t == step);
                for (int k = 0; k < e->grad->len; k++) {
                    assert(p < ELEMENTS && isfinite(e->grad->data[k]));
                    raw[p++] = e->grad->data[k];
                    sumsq += (double)e->grad->data[k]*e->grad->data[k];
                }
            }
            assert(p == ELEMENTS);
            for (int i = 0; i < t->count; i++)
                if (t->entries[i].frozen) assert(!t->entries[i].grad);
            float norm = nt_tape_clip_grads(clip);
            float norm_error = fabsf(norm-(float)sqrt(sumsq));
            assert(isfinite(norm) && norm_error < 2e-6f*(1+(float)sqrt(sumsq)));
            max_norm_error = fmaxf(max_norm_error,norm_error);
            float scale = norm > clip ? clip/(norm+1e-6f) : 1;
            clipped_steps += norm > clip;

            /* Compute Adam independently of its persistent tape state. */
            float expected[ELEMENTS];
            p=0;
            for (int j = 0; j < PARAMS; j++) for (int k = 0; k < params[j]->len; k++) {
                float g = t->entries[slots[j]].grad->data[k];
                assert(isfinite(g) && fabsf(g-raw[p]*scale) < 1e-7f);
                ref_m[p] = beta1*ref_m[p]+(1-beta1)*g;
                ref_v[p] = beta2*ref_v[p]+(1-beta2)*g*g;
                float m_hat = ref_m[p]/(1-powf(beta1,(float)(step+1)));
                float v_hat = ref_v[p]/(1-powf(beta2,(float)(step+1)));
                expected[p] = params[j]->data[k]-lr*m_hat/(sqrtf(v_hat)+1e-8f);
                p++;
            }
            nt_tape_adam_step(lr);
            nt_tensor *saved_m[PARAMS], *saved_v[PARAMS];
            float moments_m[ELEMENTS], moments_v[ELEMENTS];
            p=0;
            for (int j = 0; j < PARAMS; j++) {
                assert(t->adam[j].t == step+1);
                saved_m[j]=t->adam[j].m; saved_v[j]=t->adam[j].v;
                for (int k = 0; k < params[j]->len; k++) {
                    float error = fabsf(params[j]->data[k]-expected[p]);
                    assert(isfinite(error) && error < 1e-7f);
                    assert(fabsf(saved_m[j]->data[k]-ref_m[p]) < 1e-8f);
                    assert(fabsf(saved_v[j]->data[k]-ref_v[p]) < 1e-8f);
                    max_update_error = fmaxf(max_update_error,error);
                    moments_m[p]=saved_m[j]->data[k]; moments_v[p]=saved_v[j]->data[k];
                    p++; updates++;
                }
            }
            nt_tape_clear();
            batch_free(&s);

            /* Evaluation must neither allocate slots nor reset/advance Adam. */
            if (interleave) for (int en = 1; en <= 3; en++) {
                token_row eo[]={{0,0},{0,1},{0,2}};
                mlp_batch es = gather(&b,&ex,eo,en);
                nt_tape_start();
                int eval = mlp_forward(&b,&es,0,NULL,NULL,NULL);
                assert(isfinite(t->entries[eval].output->data[0]));
                assert(t->n_params == 0);
                nt_tape_clear();
                batch_free(&es);
            }
            p=0;
            for (int j = 0; j < PARAMS; j++) {
                assert(t->adam[j].m == saved_m[j] && t->adam[j].v == saved_v[j]);
                assert(t->adam[j].t == step+1);
                for (int k = 0; k < params[j]->len; k++) {
                    assert(t->adam[j].m->data[k] == moments_m[p]);
                    assert(t->adam[j].v->data[k] == moments_v[p]);
                    p++;
                }
            }
        }
        int p=0;
        for (int j = 0; j < PARAMS; j++) for (int k = 0; k < params[j]->len; k++)
            final[interleave][p++] = params[j]->data[k];
        free_fixture(&b,&ex);
    }
    assert(clipped_steps > 0 && updates == 2*STEPS*ELEMENTS);
    assert(!memcmp(final[0],final[1],sizeof(final[0])));
    printf("MLP optimizer: %d Adam updates checked; 120 frozen evaluations leave trajectory identical; "
           "max update error=%g, norm error=%g\n",updates,max_update_error,max_norm_error);
    return 0;
}
