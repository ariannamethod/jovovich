# jovovich
Juror Of Versioned Ontology, Vigilance, Integrity, Code &amp; Heresy

JOVOVICH reviews a change against the repository's stated rules. Its English
review starts with **CONCERN** or **CLEAN**, shows the reviewed file and exact
input excerpts, and ends with both choice probabilities.

The first prototype is a small C output library with recorded decisions from
the original [`OmniJev/OneJev-0.8B`](https://huggingface.co/OmniJev/OneJev-0.8B).
It runs without model weights or inference dependencies:

```sh
make
./build/review-demo
./build/review-demo accept-authority-True
./build/review-demo --json all
make check
```

The demo replays the 14 English reviews measured on 2026-11-06. OneJev selected
12 correct verdicts: 5/7 concerns and 7/7 clean changes. The saved run includes
the missed index boundary and disabled-writer cases. Tests compare the C output
against every recorded choice and probability, including those two misses.

See the [answer contract and examples](docs/review-output.md). The current model
decision is a probability vector over two labels; the quoted rule and change
come from the review input. Model inference and training are the next stages.

The intended inference dependency is NoTorch, with native Qwen3.5 support added
there first. The selected OneJev checkpoint retains its vision components;
the first review cases use text. The existing private model repository is
[`ataeff/jovovich`](https://huggingface.co/ataeff/jovovich).
