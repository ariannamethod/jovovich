#ifndef JOV_VISUAL_COMPARE_H
#define JOV_VISUAL_COMPARE_H

/* Read exact visual revisions and the rule from their Git base. On success,
 * AML owns visual_state/question/a/b; the caller owns the comparison receipt. */
int jov_visual_comparison(const char *directory, const char *input, char **receipt);
int jov_visual_compare_preview(int argc, char **argv);

#endif
