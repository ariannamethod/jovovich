#ifndef JOV_VISUAL_MEMORY_H
#define JOV_VISUAL_MEMORY_H

/* Called only after a live visual inference. The journal retains the model's
 * observation, its immutable Git image and the explicit correction lineage. */
int jov_visual_remember(const char *directory, const char *input,
                        const char *observation, char **receipt);
int jov_visual_remembered(const char *directory, const char *repository,
                          const char *key, int through, char **receipt);
int jov_visual_history(int argc, char **argv);

#endif
