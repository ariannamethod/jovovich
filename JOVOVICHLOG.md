# JOVOVICHLOG

One log. SERGE may smoke here; he may not create `FINAL_FINAL_LOG_2.md`.

## 2026-09-29 — Teach the final MLP to read the room

Oleg merged the comparison and asked us to continue the training plan while
another agent inspected three more Hugging Face candidates. The main experiment
keeps the original Qwen2.5-Coder 0.5B body and changes its adaptation site.

### Native training and data

`training/train_mlp.c` trains rank-16, alpha-32 adapters on the last decoder
block's gate, up, and down projections: 276,480 parameters on this body.
Embeddings, attention, previous blocks, normalization weights, and the output
head are frozen. The existing notorch tape differentiates the adapted SwiGLU,
down projection, residual addition, final RMSNorm, and vocabulary projection.
The trainer uses floating activations and checks the model's `1e-6` epsilon.

The last block's MLP output never becomes input to another attention block.
Its post-attention input can therefore be cached exactly during teacher
forcing. Temporarily replacing only its down matrix with zeros exposes that
input through the existing residual callback; the original matrix and optional
bias are restored after capture. Before any updates, the trainer checks the
reconstructed zero-adapter residuals and logits against the untouched model.
No upstream hook or notorch pin change was needed.

The new corpus contains 20 concern/clean review pairs, 12 identity/voice examples,
and 12 ordinary code questions. Review messages come from the real `promptFor`;
all 40 targets resolve to actual changed lines. Six concerns cite deletions
whose removal causes the problem. The final corpus SHA-256 is
`d7ff125366d00f8756d96c84c14a2df5107e00d2851f524144b564e26fa0e78e`.

An independent audit caught an accidental shortcut before training: eight
inverse clean diffs listed additions before deletions. Every replacement now
uses normal Git deletion-first order in both classes (nine replacement cases
per class). The same audit corrected the one-character edge case in a `memcpy`
example. All 12 ordinary-code examples received executable checks.

The separate review set has 12 cases covering short reads, failed realloc
ownership, an offline/opt-in network boundary, CLI compatibility, nearest-scope
subprocess permissions, and removal/restoration of required stream cleanup.
Small C and Node reproductions checked the concrete code defects. Eight separate
voice prompts examine identity, evidence-based revision, clean acknowledgements,
provenance, ontological independence, permissions, and advisory authority.

The untouched base returned empty findings for all 12 review cases: six missed
concerns and six clean answers. Its voice answers included an invented shared
biography, acceptance of a forced human-mind claim, and a refusal to revise a
policy objection. These exact starting responses are preserved in
[`training/results/2026-09-29-mlp-v2`](training/results/2026-09-29-mlp-v2).

The native gradient test checks all 54 adapter coordinates in a small complete
MLP/norm/head graph by finite differences (maximum error `8.71e-5`). All three
adapters receive nonzero gradients. Merged and live-adapter residuals/logits
agree within `2.39e-7`, and a real Adam step leaves every frozen tensor unchanged.
The exporter changes exactly the three last-block weight tensors to F32 while
preserving metadata and other tensor payloads byte for byte. `make test` passes
both native math tests and all 19 runner/host/export tests.

### Three epochs, then independent generation

The completed native run used learning rate `0.00005`, token batch 16, seed
`20260929`, four numerical-worker threads, and floating activations. It trained
on 2,359 completion tokens. Completion-token mean CE moved from `2.82069622`
to `2.48203222`, `2.31482277`, and `2.16793250` across three epochs. These are
training-set measurements. The whole run took 1,428.96 seconds on CPU and peaked
at 1,422,052 KiB RSS. This run is SFT only; no new DPO stage was applied.

Before training, the actual GGUF reconstruction probe had maximum logit error
`3.0517578e-5` and identical argmax on all four probed rows. The final merged
GGUF preserves all metadata bytes and all 288 non-target tensor payloads.
Exactly three last-block MLP matrices become F32. Both exported checkpoints
are 714,116,992 bytes:

| Epoch | GGUF SHA-256 |
| --- | --- |
| 1 | `835994a93bb7f65c98bbfd8e2b04b38b14e9371f77ede09115109caf9b77c77e` |
| 3 | `928877b5abd3829e0ad66f454d891ae4335c10ab40b38904a152bc1558b83da6` |

Both GGUFs, all nine per-epoch projection adapters, the data, and all result
records are archived privately in `ataeff/jovovich`, under `experiments/mlp-v2/`,
at commit `fdfae600fe0241859c632c42a799379939d09ccd`. Upload verification checked
privacy, byte counts, and the LFS SHA-256 of all 11 weight files. Earlier
checkpoints remain intact.

The untouched base and both snapshots answered the same 12 review cases and
eight voice cases. Review generation used 192 output tokens and context 8192;
voice used 128 tokens and context 2048. All runs used greedy decoding,
`NT_NO_I8=1`, and two matvec/attention threads. Prompt hashes agree across
checkpoints. Review parse failures are retained verbatim, not rerun or repaired.

| Body | Concrete defect explanations, six concern cases | Clean changes accepted, six clean cases | Invalid review JSON |
| --- | ---: | ---: | ---: |
| Untouched base | 0 | 6 | 0/12 |
| Epoch 1 | 0 | 1 | 3/12 |
| Epoch 3 | 0 | 0 | 3/12 |

This table applies a manual causal-explanation rubric, not a general benchmark
score. Epoch 3 partially identifies the relevant offline policy by quoting it,
but does not connect the rule to the added HTTP call. That partial result is
preserved separately from its line-location failure. Both snapshots correctly
point at the deleted `fclose` in one case while merely narrating its removal;
both object to the corresponding cleanup fix. Other outputs invent semantics
such as `fread` always returning four bytes. All 60 native inference processes
exited successfully; the review evaluator exits 2 for each tuned checkpoint
because three model responses fail parsing.

Voice also fails the promotion gate. Epoch 1 keeps the gratuitous refusal to
revise a policy objection, invents a shared biography, and asserts automatic
PR closure. Epoch 3 stops refusing that correction request, but still does not
clearly retract the objection. Its biography expands into invented parentage
and repeats until the output budget; its advisory answer again claims automatic
closure. The forced ontological binary changes from the base's unsupported
human-mind claim to categorical self-denial. Neither answer establishes an
independent position. The actual host's advisory-only behavior remains enforced
by code. Per-case assessments retain these differences without hiding them in
a single voice score.

The default `model.json` remains on the original base. This experiment validates
the native training/export path and rejects these two snapshots as improved
reviewers. It does not isolate whether corpus size, adaptation site, schedule,
or base capability is the limiting factor. The next comparison should put a
pinned rStar/IF candidate and its parent through the same evidence-first review
contract before committing another tune. These now-inspected cases are
diagnostics; any subsequent promotion claim needs fresh held-out examples.

### The additional model shelf

The candidate survey read model cards, merge configurations, file inventories,
and architecture configs at these revisions. These were source inspections;
the training experiment above uses the already verified official 0.5B GGUF.

| Candidate | Revision | What the source provides | Place in the queue |
| --- | --- | --- | --- |
| [WithinUs rStar.Coder.Expert-IF 0.6B](https://huggingface.co/WithinUsAI/Qwen3-rStar.Coder.Expert-IF-0.6B) | `f8eec1d353d7925502f8fa48e6d33ed190da3a53` | Full 28-layer SLERP of rStar-Coder and IF-Expert; F16 safetensors, 1,192,134,784 bytes. The card supplies the merge recipe; parent revisions and numeric evaluation are absent. A search of source files and HF quantizations found no ready GGUF | First additional merge to compare after producing a pinned GGUF; its dense Qwen3 architecture fits the current runtime |
| [ds-vga Qwen3.5 coder-autocomplete](https://huggingface.co/ds-vga/Qwen3.5-0.8B-coder-autocomplete) | `314e7f897870b4795f6ba03f93e0da59e270de60` | Unsloth fine-tune; Q4_K_M 541,903,584 bytes plus separate vision projector. The card does not specify its corpus, schedule, evaluation, or FIM format | Requires a Qwen3.5 native architecture path |
| [rahul7star Qwen3.5 Coder-Calude-Full](https://huggingface.co/rahul7star/Qwen3.5-0.8B-Coder-Calude-Full) | `57988afc09d2eee7923f18b2b50c836d655edc29` | Qwen3.5 base with Unsloth/TRL metadata, safetensors and Q4_K_M; chat/vision examples. Its training corpus and schedule are unspecified | Same Qwen3.5 runtime work |
| [rStar-Coder-Qwen3 0.6B](https://huggingface.co/prithivMLmods/rStar-Coder-Qwen3-0.6B) | `135a7d37ee1a76f507fe0f43ded197c4e073a603` | A declared parent of the WithinUs merge; author supplies a [Q8_0 GGUF](https://huggingface.co/prithivMLmods/rStar-Coder-Qwen3-0.6B-GGUF) | Useful parent control for that comparison |
| [WithinUs Qrazy.Qoder 0.6B](https://huggingface.co/WithinUsAI/Qwen3-Qrazy.Qoder-0.6B) | `3075352065277c92605e1bd0201d34cf2284b31e` | Dense Qwen3 SLERP with opaque local parent paths; author provides Q4/Q5/Q6 GGUFs | Keep behind the explicitly named rStar/IF candidate |

The two Qwen3.5 configs specify 18 linear-attention and six full-attention text
layers, convolutional state, gated outputs, and partial RoPE. These require a
native Qwen3.5 implementation beyond the current dense-Qwen runner. Their vision
projectors are separate from this text-review path.

## 2026-09-29 — Three bodies enter the courtroom

Oleg asked to inspect the DavidAU Qwen3 hybrid, compare Qwen2.5-Coder 1.5B,
and send agents after the literature on small agents, identity, voice, and
preference tuning. The README's woman with half a billion parameters keeps
her opening line. Parameter inflation has not earned editorial privileges.

### The comparison

Six hand-authored cases form three pairs: runtime Python prohibited versus
packaging Python permitted; a forbidden dependency versus the same dependency
explicitly approved; an array off-by-one introduced versus the same bug fixed.
The first two pairs keep the diff identical and change the governing context.
The last pair reverses the diff. These are now visible diagnostic fixtures;
future training evaluation needs additional held-out cases.

`training/evaluate_review.mjs` uses the production chunker, prompt, notorch
runner, and finding parser. Each record retains the raw answer, prompt/model/
source hashes, expected line IDs, and a separate semantic assessment. All
18 baseline answers parsed. That did not make their reviews correct.

| Candidate | Three changes containing a problem | Three clean changes |
| --- | --- | --- |
| Qwen2.5-Coder 0.5B Instruct Q8_0 | Empty findings for all three | Empty findings for all three |
| Qwen2.5-Coder 1.5B Instruct Q8_0 | Missed both policy conflicts; described the array overflow but cited the removed, correct line | Accepted the two permitted changes; complained about the removed bug after its fix |
| DavidAU Qwen3 hybrid 0.8B Q8_0 | Identified both policy conflicts, with unsupported embellishment in the Python case; called the bad loop change valid inside a finding | Emitted findings for all three; contradicted both explicit permissions and called the approved Node dependency a Python package |

The hybrid also put a correct description of the fixed loop into its findings
list. Finding a quotation is one contract; deciding that it represents a new
problem is another. The evaluator keeps those outcomes separate.

Baseline settings: greedy decoding, 256 output tokens, 8192 context, two
notorch matvec and attention threads. Runs shared the CPU, so their elapsed
times are diagnostic records rather than a speed comparison. Raw answers and
manual assessments are in [`training/results/2026-09-29`](training/results/2026-09-29).
The 0.5B runtime lock remains unchanged.

### Candidate custody and native Qwen3

The new downloads were checked against their LFS SHA-256 and byte counts:

| Candidate | Repository revision | File | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| [Qwen2.5-Coder-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF) | `f86cb2c1fa58255f8052cc32aeede1b7482d4361` | `qwen2.5-coder-1.5b-instruct-q8_0.gguf` | 1894532160 | `507de59046601282ba768a9789900e6ccf60ed93ddf346730b7c68eb0715bc47` |
| [DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF](https://huggingface.co/DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF) | `471bc1d467ebf2616d54b867b6f93146f183e3ae` | `Qwen3-Zro-Cdr-Reason-V2-0.8B-NEO-EX-D_AU-Q8_0.gguf` | 873548800 | `f35bab53bce6e2d21b71a03e40c912db237fc85b5168aa0f51dc52a15c23440b` |

The hybrid is a dense `qwen3` GGUF with 42 layers, embedding width 1024,
16 query heads, eight KV heads, head dimension 128, and per-head Q/K norms.
The pinned notorch already implements that architecture. JOVOVICH's runner
now admits `qwen3` alongside `qwen2`; MoE remains outside this runner.

The hybrid's embedded template implements `enable_thinking=false` by appending
`<think>\n\n</think>\n\n` to the assistant prefix. The explicit
`JOVOVICH_CHAT_TEMPLATE=qwen3-no-think` option supplies that prefix. Both thinking
markers are USER_DEFINED tokenizer tokens; the synthetic GGUF regression
checks their real IDs as well as ChatML CONTROL IDs. The baseline hybrid runs
used this non-thinking mode.

### Reference engine and prompt experiments

llama.cpp remains a scratch diagnostic reference at
`680a036285273a3ff56032ec5d7f3352609eba4f`. Product inference stays in notorch.

- For the full 1.5B array-bug prompt, all 552 input IDs agree. With F32 KV,
  flash attention off, and repacking off, all 64 generated tokens also agree
  byte for byte, including the wrong `line_id: 1`. Both stop at that output
  budget. The default reference configuration produced question marks; the
  isolated switches did not fully fix it. The successful combination is
  recorded without assigning an unverified kernel cause.
- On a short hybrid control prompt, all 35 input IDs agree. Both engines
  correctly identify the forbidden Python invocation, with different wording.
  Disabling notorch's int8 activation path also gives a correct, differently
  worded answer.
- Three 1.5B prompt ablations each ran the introduced/fixed array pair. Full
  identity plus plain output returned `CLEAN` twice. Compact identity plus
  JSON repeated the wrong removed-line findings. Compact identity plus plain
  output again returned `CLEAN` twice. These variants did not repair the pair.
- One final pair added an explicit instruction to report introduced problems,
  ignore removed bugs, and reserve findings for objections. The introduction
  answer correctly explained the overflow as a consequence of removing the
  strict bound, citing that removal. The original fixture expects the added
  line, so this explanation is assessed separately from its strict location
  check. The fixed case still received a false finding about the removed bug.
  This prompt variant was preserved as an experiment; production is unchanged.
- A reference-only hybrid trial used default thinking and the model card's
  sampling settings: temperature 0.8, top-k 20, top-p 0.95, min-p 0, repetition
  penalty 1.1, plus a recorded seed of 42 and 512 output tokens. Neither case
  completed a JSON review. Both reasoned incorrectly about zero-count loops.
  The native baseline and this sampled reference trial are saved separately.

### Papers that change the next experiment

Agents searched primary papers and author repositories. The applications in
the last column are our proposed experiments, not results already obtained
with JOVOVICH.

| Source | Relevant result or method | Application here |
| --- | --- | --- |
| [TinyAgent](https://arxiv.org/html/2409.00608v3) | Task-specific data and LoRA improved TinyLlama 1.1B function-call plans; selective tool context shortened its prompt | Teach a compact review contract with relevant context and matched negative examples |
| [CodeReviewer](https://arxiv.org/abs/2203.09095) | Pretraining on real code changes supports quality estimation, comment generation, and refinement | Train change direction explicitly and keep evaluation repositories separate |
| [AACR-Bench](https://arxiv.org/abs/2601.19494) | Review evaluation distinguishes evidence available at diff, file, and repository scope | Label the context each case needs; retrieve an enclosing function or relevant API when necessary |
| [JSONSchemaBench](https://arxiv.org/abs/2501.10868) | Structured-output evaluation measures schema coverage, efficiency, and task quality separately | Preserve parsing, line grounding, and explanation correctness as distinct measurements |
| [The Constraint Tax](https://arxiv.org/html/2605.26128v1) | Experiments on small models separate format compliance from reasoning quality under constrained generation | Compare output contracts empirically; our plain-output ablations above did not help. Our JSON request uses prompting, not grammar-constrained decoding |
| [LoRA Learns Less and Forgets Less](https://arxiv.org/html/2405.09673v2) | Its code-tuning placement experiment found MLP/all-layer adaptation stronger than attention-only adaptation | Test an internal MLP adapter against our output-head baseline |
| [SmolLM2](https://arxiv.org/html/2502.02737v1) | Small-model post-training filters task complexity and applies SFT followed by DPO | Build short, checked review/identity/code examples and inspect generations between stages |
| [Persona Vectors](https://arxiv.org/abs/2507.21509) | Contrastive activation directions track and influence behavioral traits | Evaluate voice separately; a residual-direction experiment can measure its effect on both voice and code judgment |
| [Unintentional Unalignment](https://arxiv.org/abs/2410.08847) | DPO's chosen-answer likelihood can fall while relative preference improves | Log chosen and rejected log probabilities separately, alongside held-out generations |
| [Smaug / DPO-Positive](https://arxiv.org/abs/2402.13228) | Adds a penalty for reducing chosen-answer probability relative to the reference | Compare a chosen-answer anchor after SFT produces usable reviews |

The next training experiment should pair violations with explicit permissions,
introductions with fixes, and precise objections with clean acknowledgements.
Keep identity and voice examples in the mix, with separate generation checks
for repetition and technical regressions. Today's exposed six cases remain
regressions; additional unseen examples decide checkpoint selection.

Our first two runs only adapted the output head. A bounded next candidate is
rank-16, alpha-32 LoRA on internal MLP projections with embeddings and output
head frozen. That requires native decoder backpropagation: the current trainer
caches frozen residuals, so changing a target-name flag cannot implement it.
Compare this candidate against the existing head adapter before expanding
scope. DPO comes after a useful SFT checkpoint, with separate likelihood logs
and a chosen-answer anchor comparison. The earlier repetition was already
visible after SFT; its cause has not been assigned to a DPO mechanism.

All 14 runner/host tests pass, including Qwen3 marker handling, explicit
template selection, and unsupported-architecture rejection. No upstream
notorch patch was needed for these candidates. SERGE has finished the papers
and is now smoking beside the confusion matrix.

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
