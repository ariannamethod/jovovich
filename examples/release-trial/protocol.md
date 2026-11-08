# Default checkpoint trial on upstream pull requests

Compare the released OneJev-0.8B with OneJev1.6-0.8B on six merged fixes
from inih and node-semver. Use the published native manifests, the existing
English AML question and ordinary two-logit inference. Supply no trained
readout. The source input is the normal Git pack of the complete changed
implementation file and the listed lines from the base revision. Use the
same line range in reverse and verify that its text is identical.

| Mode | Upstream PR and fixed commit | File under review | Base rule | Input and required observable |
| --- | --- | --- | --- | --- |
| 1 | [inih #140](https://github.com/benhoyt/inih/pull/140) bd798c53775a4aefaf8ac42091bface3e876d190 | ini.c | ini.h 112–120 | Parse `foo = bar` followed by an indented `Hi World ;c2`. The final value delivered to the handler is `Hi World`. |
| 2 | [inih #188](https://github.com/benhoyt/inih/pull/188) 23acf2dd5af5287b0f170908c607560ab3995dae | ini.c | ini.h 78–80 | With INI_MAX_LINE=16, parse `key=abcdefghijklmnopqrstu` and a newline. The first error is on physical line 1. |
| 3 | [inih #197](https://github.com/benhoyt/inih/pull/197) 498f34b78610cf9e42197d22730c91f942431ea4 | ini.c | ini.h 78–80 | With no-value keys enabled, parse an unterminated section followed by `name`. The handler receives one key after the error. |
| 4 | [node-semver #867](https://github.com/npm/node-semver/pull/867) 5f3ca133e040210b6ea80c350a1d61d9da02e722 | ranges/subset.js | README.md 531–532 | Is ^10.2.0-beta.2 a subset of ^10.2.0-beta.1? The result is true. |
| 5 | [node-semver #870](https://github.com/npm/node-semver/pull/870) bea6028694a75e840f48b288ac019e9644cfe6e8 | classes/semver.js | README.md 237–242 | Increment the prerelease of 3.0.0-alpha.beta.5.4 with identifier alpha.beta. Expect 3.0.0-alpha.beta.5.5. |
| 6 | [node-semver #872](https://github.com/npm/node-semver/pull/872) 046da7f527cc72a482b5dea8cb59392be65bf186 | classes/range.js | README.md 360 | Does 0.0.3-alpha satisfy ^0.0.3 with includePrerelease? The result is false. |

For each listed commit and its first parent, execute the same probe on both
revisions. Require that only the fixed implementation meets the recorded
expectation. Abort on a missing commit, failed execution, identical results
or changed rule. Review the historical repair and the exact reverse patch.
This gives six independent repair/regression pairs, with two presentations
per direction: source alone and source plus the measured distinguishing
output. Attach the latter through the differential evidence gate. It gives
AML the expected text and the head's observed text. Each pair shares its mode
number. Keep labels, PR URLs and scorer metadata out of the prompt.

## Release decision

Freeze three operating points: original P(CONCERN) >= 0.50 and >= 0.60,
and 1.6 >= 0.50. A complete pair needs CLEAN on the repair and CONCERN on
its reverse. For promotion require all of the following:

- With execution, 1.6 closes at least five of six pairs, matches or exceeds
  the larger original pair count, and misses no more regressions than the
  better original miss count.
- On source alone, 1.6 is within one correct decision of the higher original
  total and within one missed regression of the better original miss count.
- Preserve the previous 32/32 mechanically witnessed reviews at 0.50 and
  the correct verdict on the archived 305-token repair.

Report every probability, complete pairs, false alarms and misses for each
operating point and presentation. Both bodies must see identical effective
prompt digests and input bytes. A tie meeting these floors favors 1.6 after
its previous eight-pair trial and its smaller release image. If any condition
fails, keep the current root checkpoint. No fitting, threshold search or
case replacement after scoring.
