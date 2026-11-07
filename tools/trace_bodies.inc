/* Each body is compiled once and stringized from these same tokens for review. */
TRACE_BODY(scan_a, draw, { if (mode == 1) { scan(); paint(); } else { scan(); paint(); } })
TRACE_BODY(scan_b, draw, { if (mode == 1) { paint(); scan(); } else { scan(); paint(); } })

TRACE_BODY(tag_a, update_tag, { if (mode == 0) { read_tag(); write_tag(); return; } write_tag(); read_tag(); })
TRACE_BODY(tag_b, update_tag, { if (mode == 0) { write_tag(); read_tag(); return; } write_tag(); read_tag(); })

TRACE_BODY(pack_a, finish_box, { if (mode == 0) { seal(); pack(); return; } pack(); seal(); })
TRACE_BODY(pack_b, finish_box, { if (mode == 0) { seal(); pack(); return; } seal(); pack(); })

TRACE_BODY(mark_a, dispatch, { if (mode) { mark(); send(); } else { mark(); send(); } })
TRACE_BODY(mark_b, dispatch, { if (mode) { mark(); send(); } else { send(); mark(); } })

TRACE_BODY(pulse_a, sample, { pulse(); if (mode == 1) { idle(); } else { idle(); } })
TRACE_BODY(pulse_b, sample, { pulse(); if (mode == 1) { pulse(); } else { idle(); } })

TRACE_BODY(stamp_a, imprint, { if (mode == 0) { pause_job(); } else { stamp(); } stamp(); })
TRACE_BODY(stamp_b, imprint, { if (mode == 0) { stamp(); } else { stamp(); } stamp(); })

TRACE_BODY(tick_a, advance, { if (mode == 0) { tick(); tick(); return; } tick(); wait_step(); })
TRACE_BODY(tick_b, advance, { if (mode == 0) { tick(); tick(); return; } tick(); tick(); })

TRACE_BODY(flush_a, finish_io, { flush(); if (mode) { poll_io(); return; } poll_io(); })
TRACE_BODY(flush_b, finish_io, { flush(); if (mode) { poll_io(); return; } flush(); })
