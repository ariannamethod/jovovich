# JOVOVICHLOG

One log. SERGE may smoke here; he may not create `FINAL_FINAL_LOG_2.md`.

## 2026-09-29 — Read the rules upstairs, too

Codex review of PR #1 caught a real omission: local and GitHub collection only
loaded the root `AGENTS.md`. A change under `src/` could therefore arrive without
its governing `src/AGENTS.md` rules.

Both collectors now read each applicable ancestor's `AGENTS.md` from the base
revision, once per unique path. Each review chunk receives its own chain in
root-to-nearest order, with explicit nearest-scope precedence. Sibling rules
stay out of its prompt. The root README remains shared context. Existing
per-document excerpts and the native token budget still apply.

Regression cases cover inherited rules, deeper overrides, sibling isolation,
base-versus-head contents, and de-duplicated reads in local and GitHub paths.
Both scoped integration checks fail against the previous collector. The fixed
host passes all 11 runner/host tests; inference and training code are unchanged.

## 2026-09-28 — The freckles acquired an executable

Oleg and Sol brought the name, the provenance, and a deliberately small brief.
Astra built one native review path, one GitHub action, and a native training
experiment. JOVOVICH reviews. JOVOVICH does not rule.

### Body and action

- `deps/notorch` supplies GGUF loading, Qwen inference, and tokenization. The
  native executable consumes ChatML on stdin and emits only the completion on
  stdout. It rejects context overflow before inference.
- A dependency-free Node host gathers a diff and base-revision repository rules,
  bounds review chunks, and resolves model line IDs against actual changed lines.
  A model cannot invent a path or move its finding to another line.
- The WOLFE-shaped dispatcher has one action: `comment_review`. GitHub context
  collection and publication check the PR head and base. The reusable workflow
  checks out the trusted reviewer and reads PR code through the API as data.
- Missing patches and failed chunks remain visible. Empty findings are reported
  as the model returning no grounded concerns, never as an approval.

### What actually broke

The first local runner passed the spelling of ChatML CONTROL tokens through an
ordinary-text encoder. That encoder intentionally treats CONTROL spellings as
text. The runner now inserts the real `<|im_start|>` and `<|im_end|>` IDs; a tiny
synthetic GGUF regression checks this without downloading weights. Evaluations
made before this correction are excluded from behavioral conclusions below.

A second, upstream Qwen pretokenizer defect appeared in a Makefile prompt:
space followed by tab was split incorrectly. It changed two of 400 input IDs.
The narrow notorch correction makes all 400 agree with llama.cpp. The original
43-token control prompt also agrees and both engines answer `Yes.`.
The submodule pins the published fix at
`7e246e13f9dbbb7e61312b7341fb94ce492bff71`
([notorch PR #147](https://github.com/ariannamethod/notorch/pull/147)).

The host also needed incremental UTF-8 decoding: a Cyrillic character split
across process-output chunks must remain one character, not two replacements.

### Two native adaptation experiments

The checked-in seed curriculum has 30 SFT examples and 14 DPO pairs. The
decoder stays frozen. A rank-8, alpha-16 output-head LoRA trains 1,222,656
parameters using notorch C. SFT masks prompt tokens; DPO uses sequence log
probabilities against the frozen post-SFT policy, with beta 0.1. Learning rate
is 0.0002 for SFT and one quarter of that for DPO.

| Measurement on training examples | 6 SFT + 3 DPO | 24 SFT + 3 DPO |
| --- | ---: | ---: |
| Initial mean example SFT cross entropy | 3.97596505 | 3.97596505 |
| Final mean example SFT cross entropy | 2.58710332 | 1.85003589 |
| Final DPO loss | 0.37918435 | 0.30532132 |
| Positive DPO margins | 14/14 | 14/14 |

Those are optimization measurements, not a claim that the juror is ready.
Both adapted models returned empty findings for the explicit forbidden-Python
inference example, and repeated themselves on the held-out perspective question.
The first checkpoint's perspective loop reproduces for 128 generated tokens in
llama.cpp. Its full runtime review also returns empty findings in both engines.
More output-head epochs did not repair this behavior.

The runtime therefore retains the checksum-pinned Instruct base. That base also
missed the explicit violation in the full host prompt. The body and integration
are runnable; review quality and identity tuning remain unfinished. The next
training decision must use held-out generation, not just a descending loss.

The private `ataeff/jovovich` experiment archive holds the first merged GGUF,
both adapters, datasets, metrics, and exact evaluation responses. Its first
GGUF has SHA-256
`621bd3b4948acd5e8ce6dbed34362f588102b9809624a256fb02b072efbfe0fb`.
The longer run's local merged GGUF has SHA-256
`6a708834387dfa4aaae935e18a117452768718283d3a922f3a06dbe9fac78c83`.
The archive commit is `e1b253a9d7c06401a06cdec1910bfcb3a8b91b59`; all 11 uploaded
files were checked and the repository remained private.

### Reference and numerical checks

llama.cpp commit `680a036285273a3ff56032ec5d7f3352609eba4f` is a scratch reference
for diagnosis only. It is not linked into the product or training path.

The independent Unsloth Q8_0 conversion, revision
`daf1702b41e8e676d2cce36798a61b8f81983eb4`, has SHA-256
`edb8291fee6621801d9546e4eac1aef2e67e802d86d89ee3885f612498cc7657`.
Its full host prompt also matches all 400 reference input IDs and both engines
return the same empty JSON array. Merely switching these GGUF builds does not
repair that missed violation. The official file's metadata name includes AWQ;
Unsloth's does not. The official file carries an extra output tensor identical
to its embedding, accounting for most of the size difference. Sampled decoder
tensors differ, so these files are not interchangeable byte-for-byte.
Three shorter prompt variants were also tested against one violating and one
clean change on Unsloth (six generations, capped at 96 tokens each). YES/NO
missed the violation, concise JSON returned two empty arrays, and an explicit
allowed-function comparison incorrectly labelled the clean case a violation.
None passed both controls. These prompt-development probes did not change the
production prompt or justify another training run on the same seed curriculum.

The original base's shorter perspective prompt matches all 63 input IDs but
diverges late in its greedy continuation (a period versus ` to their queries.`).
No logit comparison was completed for that boundary; general numerical parity
is therefore not claimed. The trained model's 128-token repetition agrees exactly.

Independent finite differences pass all 16 sampled DPO derivatives (maximum
absolute error about `6.76e-6`). The small merged-head check differs by at most
`7.45e-9`; the actual 896-wide, 151936-token head agrees with its unmerged adapter
calculation within `2.831e-7`. Repeated head export is byte-identical.

`make test` passes the head math and all 10 host/runner tests: ChatML IDs and budget, diff coordinates,
grounding, untrusted template text, output decoding, missing API patches,
partial failures, PR races, and local Git external-diff/textconv bypass.
Actual base-weight host smoke runs complete both chunks without schema errors:
the clean change and the violating change both return zero findings.

The implementation works. The learned juror has not yet justified her robe.
