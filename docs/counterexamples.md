# Remember the input that exposed the bug

A case begins with a named Git rule and an execution that distinguishes two
revisions. JOVOVICH retains the exact original packed row in AML, including
its Git citations, the mode, measured callbacks and required effect. A later
review of the same file can recover that mode after a restart.

## Record once and replay on the next patch

Run from JOVOVICH's checkout. The operator supplies the executable test driver.
The ordinary reviewer consumes the resulting JSONL. The model and report run
through their existing entry points.

```sh
set -e
mkdir -p build/memory
repo=/path/to/reviewed-repository
driver=/absolute/path/to/your/test-driver

./build/jovovich-pack --remember build/memory studio/render draw-order \
  --all "$repo" OLD_BASE OLD_HEAD RULES.md 2 2 > original.jsonl
# This first review has one changed file. For a larger pack select its file row.
./build/jovovich-replay probe "$repo" "$driver" 1 < original.jsonl > measured.jsonl
./build/jovovich-replay remember build/memory "$repo" "$driver" < measured.jsonl > receipt.json

./build/jovovich-pack --recall build/memory studio/render draw-order \
  --all "$repo" NEW_BASE NEW_HEAD > next.jsonl
./build/jovovich-replay run build/memory "$repo" "$driver" < next.jsonl > replayed.jsonl
./build/jovovich jovovich.gguf tokenizer.gguf --json < replayed.jsonl > answers.jsonl
./build/jovovich-report replayed.jsonl answers.jsonl
```

`probe` takes a fresh single-file row and a signed 32-bit mode. `remember`
takes one named Git row with paired traces. If the original input contains a
driver digest, it must match. An earlier trace without that field can still be
captured by reproducing the original run with the supplied driver. The host verifies
the Git source, applies the ordinary trace selector, and independently repeats
both original executions and the old oracle before saving. If the historical
callbacks or requirement differ from the repeat, capture fails. Shared effects
supply no case. An identical capture returns the original receipt.

`run` accepts a fresh file row or a complete Git batch. One checkpoint snapshot
applies to the whole batch. The lookup matches repository name, rule key,
changed file and driver digest. It requires the
original base to be in the current base's ancestry and skips the identical
commit pair. It prefers the newest case whose head has already landed. When
the old head was rebased, squashed or is still on a sibling branch, it can
use the newest case with a shared ancestor base. A revision of
the named rule can reuse the input. The test driver obtains the expectation
from the current base's selected rule lines. Files without a compatible
case pass through byte-for-byte. The host stages the whole output before
publishing it. The rule and case journals share a directory and commit independently.

The checkpoint holds up to 256 original rows of up to 64 KiB each. Duplicate
captures reuse their entry. The writer lock covers checkpoint load through
the atomic AML commit. The recorded input SHA-256 covers the original JSONL
bytes, including a trailing newline if supplied. Run
`build/jovovich-replay show build/memory INPUT_SHA256` to restore that exact
row from the address in the receipt or Markdown report. The files and modes stay
local to the configured memory directory. [AML journal](../aml/counterexamples.aml)

## Test driver contract

The replay host invokes a driver chosen by the operator. Arguments are passed
literally. Its working interface uses Git object IDs, repository-relative
file names and decimal modes. The two `observe` calls share the same driver
and input. Run each revision in the test environment appropriate for that
repository. The digest identifies the executable file. A driver that loads
external fixtures, tools or a container owns the versioning of that setup.

| Invocation after the driver path | JSON on stdout |
| --- | --- |
| `observe REPO COMMIT FILE MODE` | Ordered callback array or single-line text result, for example `["scan","paint"]` or `"3.0.0-alpha.beta.5.5"`. Called once for the base and once for the head. |
| `expect REPO BASE FILE MODE RULES_PATH FIRST LAST` | The current contract's effect, for example `{"metric":"sequence","required":["scan","paint"]}` or `{"metric":"count","target":"paint","required":2}`. Use `{"metric":"text","required":"3.0.0-alpha.beta.5.5"}` for text. |

Each call returns one JSON value of at most 16 KiB and exits successfully.
Malformed outputs, a changed executable or a failed run stop the batch.
The project's fixture driver extracts `draw.c` from each named Git object,
compiles it and records the actual calls. Its oracle reads the selected Git
rule. [Fixture driver](../tests/fixtures/draw-driver.sh) · [Trace contract](trace-evidence.md)

## Six live answers

These reviews used the two GGUFs downloaded from the pinned JOVOVICH release.
The first landed case was a repair at mode 1. Every later execution was
measured against its own commit pair.

| Later review | Mode selection | P(CONCERN) | P(CLEAN) |
| --- | --- | ---: | ---: |
| Regression to the old callback order | AML memory | **87.8961%** | 12.1039% |
| Same regression | Manual probe | **87.8961%** | 12.1039% |
| Repair | AML memory | 31.0462% | **68.9538%** |
| Comment-only change, same callback order | AML memory | **66.4016%** | 33.5984% |
| Same comment-only change | Source only | **66.4016%** | 33.5984% |
| Original patch under a corrected order requirement | AML memory, fresh oracle | **96.4336%** | 3.5664% |

For the regression, the recalled and manual probes produced identical prompt
hashes and probabilities. For the comment, the gate emitted zero differing
runs. Its prompt and vote matched the source-only false positive. The
Markdown report still recorded which earlier review prompted the execution.

```sh
make all check
JOV_MEMORY_MODEL=/path/to/jovovich.gguf JOV_MEMORY_TOKENIZER=/path/to/tokenizer.gguf \
  sh tests/check_counterexamples.sh
```
