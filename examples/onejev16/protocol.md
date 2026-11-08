# OneJev 1.6 and the comment-only false alarm

PR #55's comment-only edit received 66.4016% CONCERN. Compare the shipped
OmniJev/OneJev-0.8B (c02e305b430b56c1e82f9675ba8c293a22646891) with
OmniJev/OneJev1.6-0.8B (c89933c277629b707895bff752c61d2b0664c85e).
Both run the unchanged English AML question, option order, F32 NoTorch
forward pass, two-logit softmax and 0.5 decision threshold. Use the published
base weights in both arms, with no fitted adapter or temperature.

## Patches and executable oracle

Build eight new pairs of sibling Git patches. Four test callback order and
four test how often paint is called. Each pair shares a correct base. Its
first head adds a C comment. Its second adds the identical comment and
introduces a regression on exactly one of the two supported modes, 0 and 1.
Balance the affected mode across each family. Change the branch layout
across pairs. Compile every revision, execute both modes and check the
expected effect from the base rule before running inference. Keep labels,
pair numbers and expected classes outside the model input.

Submit every head twice, first as an ordinary Git pack, then through the
existing paired-trace gate at the affected mode. The gate admits an observation
when the versions differ. The inputs and effective prompt hashes must match
between models. Check that a comment-only head gets the same prompt and vote
with and without the gate. Score both-right pairs, false alarms on comments,
missed regressions and binary Brier score (positive class CONCERN). Report the
old and new probabilities for the original PR #55 false alarm separately.

## Carryover and decision

Replay the existing 32 mechanically selected order/count reviews from
examples/run-selection on both bodies. The release reference is 32/32.
A candidate qualifies for a wider promotion trial if its gated run has more
fully correct new pairs, fewer false alarms, no additional missed regressions,
and preserves all 32 archived decisions. Only after those conditions and a
separate wider trial would we replace the private release. Record the result
of every comparison, including ties. This experiment changes no weights.
