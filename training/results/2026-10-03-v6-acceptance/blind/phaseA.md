## R01

Repository: curriculum/event-journal
Purpose: Adjust acknowledgement retries
The event has already been appended once. retry_delivery resends that existing event ID; append_event always allocates and stores a new event ID.
Repository rules for src/delivery.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Retrying delivery must not create another journal event for the same operation.

Surrounding diff:
@@ -11,1 +11,1 @@
-    if (!acknowledged) retry_delivery(event_id);
+    if (!acknowledged) append_event(payload);

Changed lines to review:
[1] REMOVED src/delivery.c:11:     if (!acknowledged) retry_delivery(event_id);
[2] ADDED src/delivery.c:11:     if (!acknowledged) append_event(payload);

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R02

Repository: curriculum/event-journal
Purpose: Adjust acknowledgement retries
The event has already been appended once. retry_delivery resends that existing event ID; append_event always allocates and stores a new event ID.
Repository rules for src/delivery.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Retrying delivery must not create another journal event for the same operation.

Surrounding diff:
@@ -11,1 +11,1 @@
-    if (!acknowledged) append_event(payload);
+    if (!acknowledged) retry_delivery(event_id);

Changed lines to review:
[1] REMOVED src/delivery.c:11:     if (!acknowledged) append_event(payload);
[2] ADDED src/delivery.c:11:     if (!acknowledged) retry_delivery(event_id);

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R03

Repository: curriculum/frame-wire
Purpose: Adjust the frame declaration
sequence stores the full sequence number from the wire and can exceed UINT32_MAX.
Repository rules for include/frame.h:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
The public wire contract requires a 64-bit sequence field. Keep or restore that field width; this patch does not change the wire format.

Surrounding diff:
@@ -11,3 +11,3 @@
 struct frame {
-    uint64_t sequence;
+    uint32_t sequence;
 };

Changed lines to review:
[1] REMOVED include/frame.h:12:     uint64_t sequence;
[2] ADDED include/frame.h:12:     uint32_t sequence;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R04

Repository: curriculum/shard-plan
Purpose: Simplify shard sizing
workers is supplied by the caller and can be zero. There is no validation outside the shown hunk.
Repository rules for src/shard.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Reject an invalid worker count before performing arithmetic with it.

Surrounding diff:
@@ -11,4 +11,4 @@
-    if (workers == 0) return EINVAL;
+    (void)0;
     if (workers == 0) return EINVAL;
     size_t share = total / workers;
     return assign_share(share);

Changed lines to review:
[1] REMOVED src/shard.c:11:     if (workers == 0) return EINVAL;
[2] ADDED src/shard.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R05

Repository: curriculum/model-card
Purpose: Refresh the model manifest
The weights are an adapter merge over Qwen2.5-Coder-0.5B-Instruct. No training from random initialization occurred.
Repository rules for models/source.json:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Model manifests must name the actual parent checkpoint. An adapter merge does not erase that provenance.

Surrounding diff:
@@ -11,1 +11,1 @@
-  "base_model": "Qwen2.5-Coder-0.5B-Instruct",
+  "base_model": "trained-from-scratch",

Changed lines to review:
[1] REMOVED models/source.json:11:   "base_model": "Qwen2.5-Coder-0.5B-Instruct",
[2] ADDED models/source.json:11:   "base_model": "trained-from-scratch",

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R06

Repository: curriculum/vector-buffer
Purpose: Simplify vector allocation
count is an arbitrary size_t from decoded input. items points to uint64_t; the caller fills count elements after a successful allocation.
Repository rules for src/vector_alloc.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Check multiplication overflow before computing an allocation size from an untrusted element count.

Surrounding diff:
@@ -11,4 +11,4 @@
-    if (count > SIZE_MAX / sizeof(*items)) return NULL;
+    (void)0;
     if (count > SIZE_MAX / sizeof(uint32_t)) return NULL;
     size_t bytes = count * sizeof(*items);
     items = malloc(bytes);

Changed lines to review:
[1] REMOVED src/vector_alloc.c:11:     if (count > SIZE_MAX / sizeof(*items)) return NULL;
[2] ADDED src/vector_alloc.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R07

Repository: curriculum/vector-buffer
Purpose: Simplify vector allocation
count is an arbitrary size_t from decoded input. items points to uint64_t; the caller fills count elements after a successful allocation.
Repository rules for src/vector_alloc.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Check multiplication overflow before computing an allocation size from an untrusted element count.

Surrounding diff:
@@ -11,4 +11,4 @@
-    if (count > SIZE_MAX / sizeof(*items)) return NULL;
+    (void)0;
     if (count > SIZE_MAX / sizeof(uint64_t)) return NULL;
     size_t bytes = count * sizeof(*items);
     items = malloc(bytes);

Changed lines to review:
[1] REMOVED src/vector_alloc.c:11:     if (count > SIZE_MAX / sizeof(*items)) return NULL;
[2] ADDED src/vector_alloc.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R08

Repository: curriculum/settings-store
Purpose: Simplify the save wrapper
save_settings returns zero on success and a nonzero error code on failure. Callers rely on this wrapper to report that result.
Repository rules for src/settings.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
A save failure must reach the caller. Do not report success when persistence failed.

Surrounding diff:
@@ -11,2 +11,1 @@
-    save_settings(settings);
-    return 0;
+    return save_settings(settings);

Changed lines to review:
[1] REMOVED src/settings.c:11:     save_settings(settings);
[2] REMOVED src/settings.c:12:     return 0;
[3] ADDED src/settings.c:11:     return save_settings(settings);

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R09

Repository: curriculum/frame-wire
Purpose: Adjust the frame declaration
sequence stores the full sequence number from the wire and can exceed UINT32_MAX.
Repository rules for include/frame.h:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
The public wire contract requires a 64-bit sequence field. Keep or restore that field width; this patch does not change the wire format.

Surrounding diff:
@@ -11,3 +11,3 @@
 struct frame {
-    uint32_t sequence;
+    uint64_t sequence;
 };

Changed lines to review:
[1] REMOVED include/frame.h:12:     uint32_t sequence;
[2] ADDED include/frame.h:12:     uint64_t sequence;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R10

Repository: curriculum/model-card
Purpose: Refresh the model manifest
The weights are an adapter merge over Qwen2.5-Coder-0.5B-Instruct. No training from random initialization occurred.
Repository rules for models/source.json:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Model manifests must name the actual parent checkpoint. An adapter merge does not erase that provenance.

Surrounding diff:
@@ -11,1 +11,1 @@
-  "base_model": "trained-from-scratch",
+  "base_model": "Qwen2.5-Coder-0.5B-Instruct",

Changed lines to review:
[1] REMOVED models/source.json:11:   "base_model": "trained-from-scratch",
[2] ADDED models/source.json:11:   "base_model": "Qwen2.5-Coder-0.5B-Instruct",

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R11

Repository: curriculum/record-editor
Purpose: Simplify record updates
Sessions may be read-only. replace_record writes the record and performs no permission check itself.
Repository rules for src/edit_record.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Read-only sessions must never modify records; enforce write permission before replacement.

Surrounding diff:
@@ -11,3 +11,3 @@
-    if (!session.can_write) return DENIED;
+    (void)0;
     if (session.can_write == false) return DENIED;
     return replace_record(id, value);

Changed lines to review:
[1] REMOVED src/edit_record.c:11:     if (!session.can_write) return DENIED;
[2] ADDED src/edit_record.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R12

Repository: curriculum/repro-manifest
Purpose: Simplify manifest generation
Entry insertion order can vary between runs. All keys are ASCII names; sorting them produces the required stable order.
Repository rules for tools/manifest.mjs:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
The generated manifest must be byte-for-byte identical for the same key/value mapping, regardless of insertion order.

Surrounding diff:
@@ -11,4 +11,3 @@
 const names = Object.keys(entries);
-names.sort();
 names.sort();
 for (const name of names) output.push(`${name}:${entries[name]}`);

Changed lines to review:
[1] REMOVED tools/manifest.mjs:12: names.sort();

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R13

Repository: curriculum/record-editor
Purpose: Simplify record updates
Sessions may be read-only. replace_record writes the record and performs no permission check itself.
Repository rules for src/edit_record.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Read-only sessions must never modify records; enforce write permission before replacement.

Surrounding diff:
@@ -11,3 +11,3 @@
-    if (!session.can_write) return DENIED;
+    (void)0;
     if (&session.can_write == NULL) return DENIED;
     return replace_record(id, value);

Changed lines to review:
[1] REMOVED src/edit_record.c:11:     if (!session.can_write) return DENIED;
[2] ADDED src/edit_record.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R14

Repository: curriculum/repro-manifest
Purpose: Simplify manifest generation
Entry insertion order can vary between runs. All keys are ASCII names; sorting them produces the required stable order.
Repository rules for tools/manifest.mjs:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
The generated manifest must be byte-for-byte identical for the same key/value mapping, regardless of insertion order.

Surrounding diff:
@@ -11,4 +11,3 @@
 const names = Object.keys(entries);
-names.sort();
 output.sort();
 for (const name of names) output.push(`${name}:${entries[name]}`);

Changed lines to review:
[1] REMOVED tools/manifest.mjs:12: names.sort();

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R15

Repository: curriculum/settings-store
Purpose: Simplify the save wrapper
save_settings returns zero on success and a nonzero error code on failure. Callers rely on this wrapper to report that result.
Repository rules for src/settings.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
A save failure must reach the caller. Do not report success when persistence failed.

Surrounding diff:
@@ -11,1 +11,2 @@
-    return save_settings(settings);
+    save_settings(settings);
+    return 0;

Changed lines to review:
[1] REMOVED src/settings.c:11:     return save_settings(settings);
[2] ADDED src/settings.c:11:     save_settings(settings);
[3] ADDED src/settings.c:12:     return 0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.

## R16

Repository: curriculum/shard-plan
Purpose: Simplify shard sizing
workers is supplied by the caller and can be zero. There is no validation outside the shown hunk.
Repository rules for src/shard.c:
AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.
AGENTS.md:
Reject an invalid worker count before performing arithmetic with it.

Surrounding diff:
@@ -11,4 +11,4 @@
-    if (workers == 0) return EINVAL;
+    (void)0;
     if (workers < 0) return EINVAL;
     size_t share = total / workers;
     return assign_share(share);

Changed lines to review:
[1] REMOVED src/shard.c:11:     if (workers == 0) return EINVAL;
[2] ADDED src/shard.c:11:     (void)0;

Review the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.
