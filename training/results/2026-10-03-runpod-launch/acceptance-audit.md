# Independent v6 acceptance evidence audit

The two original logs cited in `training/results/2026-10-03-v6-acceptance/summary.md`,
`red-run-v1.log` and `red-run-v2.log`, are absent from the current tracked tree and
the available Git history by matching path. A filename search of the current
scratch workspace found neither file. No checked-in mutation runner accompanying
the original v6 acceptance report was found. The historical claims therefore
remain unverified as historical runs; these files do not reconstruct them.

`acceptance-audit.py` provides a new independent, reproducible check. It runs the
unchanged `training/acceptance/v6_check.mjs` against temporary corpus copies and
asserts each named target check, rather than accepting the inevitable H1 hash
failure as proof that a semantic control worked. Mutations must actually change
input bytes. Original corpora and checker source are not modified.

The fresh run passed **18/18 controls**: the unmodified baseline, 16 rejection
controls, and the H9 content-adjudication branch control. Covered cases include
row identity, nonreview bytes, system bytes, nonuniform prompt suffix, findings
class and compact formatting, answer key order, explanation binding, sentence
count, nonexistent citations, REMOVED-side citations in mirrored pairs, unequal
pair sentence counts, forbidden shape language, and stale adjudications.

The synthetic H9 `content` adjudication checks only that branch: H9 passes, while
the overall checker still exits 1 because fixed input hashes changed. It is not
a substantive ruling that shape language is acceptable. The unmodified baseline
exits 0 with the already declared soft H4 strict deviation and superseded soft H8
failure retained.

Run from any directory:

```sh
python /path/to/jovovich/training/results/2026-10-03-runpod-launch/acceptance-audit.py
```

The adjacent JSON records checker and input hashes, commit, per-case statuses,
target failures, stdout, and exact pass count. This closes the present checker
validation gap for the two-arm launch; it does not supply missing original logs
or prove model quality. No model, training, native probe, generation, or cloud
resource operation was performed.
