#ifndef JOV_BOUNDARY_H
#define JOV_BOUNDARY_H

enum { JOV_BOUNDARY_CODE_SIZE = 256 };
/* One complete int function, one parameter, one return comparison.
 * Return 1 for a match and 0 for an unsupported spelling. */
int jov_boundary_code(const char *source, char code[JOV_BOUNDARY_CODE_SIZE]);
/* On a match, return 1 and allocate the model context for the caller.
 * For a Git row pass the decoded scope path. For a synthetic fenced C excerpt pass NULL.
 * Return 0 for pass-through and -1 on allocation failure. */
int jov_boundary_context(const char *git_file,const char *context,const char *rule,const char *change,
                         char code[JOV_BOUNDARY_CODE_SIZE],char **model_context);
#endif
