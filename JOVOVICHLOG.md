# JOVOVICHLOG

A fresh engineering log. Newest entries first. Earlier work remains in Git history.

## 2026-11-06 — Pin the NoTorch head-offset fix

NoTorch PR #188 widens two Qwen3.5 tensor offsets before multiplication,
resolving the CodeQL findings on the original native integration. Pin the
corrected engine commit. The rebuilt engine passes 1,214 frozen-reference
checks; the live AML consumer passes all 1,340 checks over 14 review cases.
Every emitted probability pair is exactly unchanged from the preceding run.

## 2026-11-06 — Original OneJev, NoTorch arithmetic, AML language

The live reviewer now executes original OmniJev/OneJev-0.8B with native
Qwen3.5 arithmetic in NoTorch. AML constructs the exact qev-labels-v2 question
and prompt, selects the verdict and creates its JANUS timestamp. The C host
validates supplied evidence, checks pinned model/tokenizer hashes and emits
English Markdown or JSON. The repository's former Python check is replaced by
C + AML checks. Both source dependencies are pinned.

A/B logits determine CONCERN/CLEAN without generated tokens. All 14 live
choices match the independent F32 reference within the recorded probability
gate. The original BF16 demo is preserved as a separate record. Task accuracy
is 12/14, including the index-boundary and disabled-writer misses. Full-layer
NoTorch parity, consumer checks, test counts and commands are recorded in
[docs/native-validation.md](docs/native-validation.md).

The first connection exposed two host-integration mistakes: an AML template
line exceeded the interpreter's 256-byte limit, and the host injected globals
before explicit initialization. Splitting the template and initializing AML
before injection fixed them; the exact-prompt and end-to-end checks now cover
this connection. No AML core changes were required.

LALO and Amos 2 informed the provenance boundary: retain the input, model
revision, hashes and a dated execution result. No event date or origin is
invented from the time of review. The first text path accepts ASCII English
and uses F32 CPU matrices. Vision, personality training and speed optimization
are the next implementation stages. The Hugging Face repository ataeff/jovovich
was verified private; no weights were uploaded and RunPod was not used.
