# Can OneJev pick the distinguishing run?

When a contract describes callback order or counts, one input can expose a
change while another input gives the same trace on both implementations.
In [PR 51](execution-traces.md), supplying both the required and the observed
effect at the distinguishing input led to 32/32 correct reviews. Here the
model first saw just two source bodies, the effect to compare and two input
options. Its task was to predict which input would expose a difference.

The [protocol](../examples/run-selection/protocol.json) was committed at
[1aeea46](https://github.com/ariannamethod/jovovich/commit/1aeea467b3b37ff97996f5a92d621eeeab9a7701)
before the first selection. Frozen OneJev-0.8B used its original A/B output
logits. The host rendered four independent presentations of each of the
eight PR 51 APIs, crossing source order with the assignment of modes 0 and 1
to letters A and B. Each choice had a fresh cache. The English prompt contains
no fixture ID, contract verdict, expected effects or execution results.
Executing both bodies at both modes provided the physical target for scoring.

## Choosing before execution

| Source order | A = 0, B = 1 | A = 1, B = 0 |
| --- | ---: | ---: |
| Original | 3/8 | 6/8 |
| Reversed | 3/8 | 6/8 |

The selector chose the right mode in all four presentations for two APIs:
`finish_box` (order) and `sample` (count). The criterion was seven of eight
with at least three per family. `advance` consistently received the wrong
mode. The five other APIs changed choices across presentations.

The model chose B 24 times in 32 presentations. Exchanging the input labels
changed the physical choice on 8/16 matched comparisons. Exchanging the two
source bodies changed it on 2/16. The mean binary Brier score for P(mode 1)
was 0.2390, compared with 0.2500 for a constant probability of 0.5. The
32 presentations reuse eight underlying decisions. The
[fixture table](../examples/run-selection/results.json) and
[choice receipts](../examples/run-selection/choices-answers.jsonl) record the
physical modes and the individual probabilities.

## Consequence for review

The downstream policy was fixed to original body order with A = 0 and B = 1.
It selected the distinguishing mode for three of eight APIs. Each choice
then served the four source/contract combinations of its API.

| Evidence selection | Correct /32 | Complete mutation pairs /16 | False alarms | Missed violations |
| --- | ---: | ---: | ---: | ---: |
| Source alone | 17 | 1 | 3 | 12 |
| Model choice, always show the chosen run | 22 | 6 | 0 | 10 |
| Model choice, suppress shared effects | 22 | 6 | 3 | 7 |
| Host compares both modes | 32 | 16 | 0 | 0 |

The unfiltered row reuses the matching PR 51 witness or control answer.
The two gated rows are 64 new end-to-end NoTorch reviews. When the chosen
run has a shared effect, the gate gives exactly the source-only prompt.
When it differs, it gives exactly the published full-witness prompt.
Every one of the 64 prompt digests and both F32 probabilities per review
matched its corresponding PR 51 case. Removing the common green test
recovered three violations and introduced three false alarms across the
model-selected reviews. The mechanical policy found the distinguishing
input for all eight APIs by comparing both available executions.

## Research behind the comparison

TypeSafe named Jev after William Stanley Jevons. Its system accepts a state
and typed questions. The `OmniJev/OneJev-0.8B` model used here is a multimodal
fine-tune of Qwen3.5-0.8B trained on 99,193 questions. The OneJev authors
describe one epoch with the vision encoder frozen and an equally weighted
cross-entropy and Brier objective on the option letters. For inference the
model takes the last-position logits of the allowed letters and applies
softmax in F32. This gives the selector a probability that we can score
against an executed target. [TypeSafe's account](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
· [Model card](https://huggingface.co/OmniJev/OneJev-0.8B)
· [OneJev training and inference](https://omnijev.github.io/OneJev/index.html)

The published OneJev training code shuffles the option ordering and remaps the
target to the rendered labels. Its multimodal evaluation path uses a fixed
production rendering. Zheng et al. found option-ID preferences across multiple
models and datasets. We therefore score the physical mode after swapping the
letters and count repeated presentations at the API level. [OneJev training source](https://github.com/OmniJev/OneJev/blob/2a933603789a79d046cb95d9ef21ce80f186b8a8/train/shared.py#L133-L142)
· [Evaluation source](https://github.com/OmniJev/OneJev/blob/2a933603789a79d046cb95d9ef21ce80f186b8a8/train/sft.py#L310-L317)
· [Zheng et al., ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/54dd9e0cff6d9214e20d97eb2a3bae49-Abstract-Conference.html)

McKeeman's differential testing compares comparable systems on the same
input to identify an execution worth examining. Here the observable is
contract-specific. Reordering two events changes the ordered sequence but
can preserve the count of a named callback. The host uses that observable to
select evidence. The separate required value establishes which behavior the
contract permits. [McKeeman, Digital Technical Journal, 1998](https://vmssoftware.com/docs/dtj-v10-01-1998.pdf)

## Reproduce

```sh
make build/jovovich build/trace-corpus build/score-quality build/score-run-selection
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tools/run_selection.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/new-run
```

The research mode `build/jovovich MODEL TOKENIZER --select-run` reads
`build/trace-corpus choices` JSONL rows. Its inputs carry two code bodies,
`metric`, an optional count target and the mode assigned to A. It returns the
selected physical mode, both letter probabilities, and input, prompt, model
and tokenizer digests. For reviewing changes with available executions, see
the [structured trace input and Git example](trace-evidence.md).
