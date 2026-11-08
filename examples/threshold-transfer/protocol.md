# Does a threshold learned on witnessed reviews travel?

The original caught all six witnessed reversals in PR #57 at 0.50. OneJev 1.6
caught four and assigned more CONCERN to the reversal in every pair. Fit one
threshold per body on those six pairs, then measure it on eight different
merged fixes from five repositories outside that calibration set.

## Operating points fixed before inference

Use only the twelve `execution` rows in [the prior results](../release-trial/results.json),
SHA-256 `758dc0dc5bb0934518b9161bac3e5ab2ac108b1dde1b77b930644042ca69356d`.
Take the midpoint between the highest repair P(CONCERN) and the lowest
regression P(CONCERN) and round to native float32. The prior fixes have a
gap on both checkpoints.

| Body | Highest repair | Lowest regression | Fixed float32 threshold |
| --- | ---: | ---: | ---: |
| Original | 0.4520518482 | 0.5207821727 | 0.4864169955253601 |
| 1.6 | 0.3125877082 | 0.4687528610 | 0.3906702995300293 |

Score the ordinary 0.50 verdict on both bodies. For the two calibrated
policies use P(CONCERN) >= the corresponding threshold only when the
native gate admitted a distinguishing text observation. Keep the ordinary
verdict on source and shared inputs. Preserve the raw scores. Use the
published GGUFs, shared tokenizer, AML prompt, label order and native
two-logit readout. No adapter or weight update enters this trial.

## Fresh paired inputs

[The roster](cases.tsv) pins each upstream merge, implementation path and
inclusive base-rule lines. Review that file from the first parent to the
merge and in reverse. The rule bytes must match in both directions. For
each review run three presentations: source alone, a shared input and a
distinguishing input. The negative mode number selects the shared input,
the positive one selects the distinguishing input. The host must withhold
the whole observation on the shared input. Run both programs at both inputs
before inference. Abort on a wrong requirement, shared-output disagreement,
non-distinguishing case or missing row. Use all eight pairs as listed.

| Case | Shared input | Distinguishing input and required output |
| --- | --- | --- |
| cJSON #810 | Append 2 to [1,3] | Insert 2 at index 1. Serialized array [1,2,3]. |
| ms #111 | Parse -1.5h | Parse -10.5h. Return -37800000 milliseconds. |
| Underscore #3018 | Max of null with default iteratee | Max of null with numeric iteratee 0. Return -Infinity. Capture a thrown TypeError by its name. |
| Underscore #3026 | Convert the primitive empty string to an array | Convert a boxed empty string. Return []. |
| PapaParse #1124 | Serialize the fields a and xy with + as quote | Serialize a and x+y with + as quote. Return a,+x++y+. |
| PapaParse #1128 | Detect the delimiter on two ordinary semicolon-separated rows | Detect the semicolon on the upstream three-row CSV with quoted multiline JSON fields containing commas. |
| npm/ini #123 | Read b.name with the section heading [b] | Add a trailing space to that heading. Reading b.name must still yield value. |
| npm/ini #252 | Parse brr=1 with bracketedArray disabled | Parse brr=1 then brr=2. The brr property must contain the two strings in order. |

## Decision

Record both-right pairs, correct verdicts, false alarms on repairs and misses
on reversals for each view and operating point. Also count how often the
reversal receives a higher raw probability than its repair. Verify byte and
prompt identity across bodies, and exact prompt and vote identity between
shared and source within each body.

The conditional 1.6 policy qualifies for an opt-in operating point if it
closes at least seven of eight witnessed pairs, improves its own raw pair
count, matches or exceeds the shipped original's pair count, and incurs no
more false alarms or misses than the shipped original. Every source/shared
decision must equal the ordinary decision. The original with its own fitted
threshold is the symmetric sensitivity check. Publish all outcomes, including
any repository that loses a correct decision. The default release continues
to use the original body. Keep all threshold fitting outside the fresh panel.
