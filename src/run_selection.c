#include "run_selection.h"
#include "ariannamethod.h"
#include "report_json.h"

int jov_prepare_selection(const char *row,int *mode_a) {
    const char *end=report_json_end(row,0);
    if(!end || *nj_ws(end))return 1;
    char *first=nj_string(nj_get(row,"first_body")),*second=nj_string(nj_get(row,"second_body"));
    const char *kind=nj_get(row,"metric"),*raw_target=nj_get(row,"target");
    char *target=nj_string(raw_target);
    int count=nj_is(kind,"count");
    long long mode;
    int bad=!first || !*first || !second || !*second || (!count && !nj_is(kind,"sequence")) ||
        (count ? !target || !*target : raw_target!=NULL) ||
        nj_int(nj_get(row,"mode_a"),&mode) || (mode!=0 && mode!=1);
    if(!bad) {
        *mode_a=(int)mode;
        bad=am_set_var_text("first_body",first) || am_set_var_text("second_body",second) ||
            am_set_var_text("count_target",count?target:"") || am_set_var_array("select_count",(float[]){(float)count},1) ||
            am_set_var_text("option_a",mode?"1":"0") || am_set_var_text("option_b",mode?"0":"1") ||
            am_exec_file("aml/select-run.aml");
    }
    free(first);free(second);free(target);return bad;
}
