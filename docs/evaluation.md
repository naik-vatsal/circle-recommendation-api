# Evaluation interpretation

Run `uv run --locked python -m scripts.evaluate` to reproduce `evaluation.json`. Use `--output docs/evaluation.json` to regenerate it or `--check docs/evaluation.json` to reject a stale report. Evaluation uses a temporary database, never the running service's data.

## Method

All 100 users receive up to five recommendations under the same eligibility rules and observation time:

- **activity_and_access:** activity and joining ease, without interest/membership/participation contributions or list diversification.
- **topic_ranked:** all final score features, without caps or overlap penalties.
- **final:** all features and list constraints.
- **without_participation:** final selection with participation weight zero.

The report fingerprints canonical JSON from the five inputs with SHA-256. It has no wall-clock timestamp and is reproducible across line endings.

## Results on this fixture

| Diagnostic | Activity/access | Topic-ranked | Final | Without participation |
| --- | ---: | ---: | ---: | ---: |
| Returned slots | 500 | 500 | 500 | 500 |
| Eligibility violations | 0 | 0 | 0 | 0 |
| Attainable stated-topic coverage | 18.8% | 100% | 100% | 100% |
| Repeated primary-topic slots | 136 | 86 | 0 | 0 |
| Primary-interest slots | 29 | 162 | 117 | 117 |
| Related-interest slots | 42 | 138 | 70 | 70 |
| Distinct Circles exposed | 9 | 33 | 32 | 33 |
| Largest share of first positions | 76% | 13% | 13% | 11% |

**Attainable coverage** sums, per user, distinct selected interests appearing as primary topics in the list, divided by distinct interests with an eligible primary-topic Circle. It excludes interests with no eligible primary match. It is not precision, satisfaction or retention. Repeated recommendations inflate matching-slot counts; diversity reduces those counts while retaining distinct-topic coverage.

Repeated-topic slots count occurrences beyond the first non-null primary topic within a list. Exposure is descriptive, not a fairness objective; users have different interests. All variants return 500 slots here, so slot counts are comparable.

The participation ablation is reported even though it does not improve coverage or catalogue exposure. It changes ordering and some selected groups; these are hypotheses about peer interaction, not demonstrated improvements in member experience.

## Stability and limits

Independent plus/minus 10% weight changes retain 97.4%-100% mean top-five set overlap. First position remains unchanged for 97%-100% of users. This checks local sensitivity, not optimality; near-equal groups can exchange positions. Weights are not tuned to maximize these figures.

The 30/45/60-day windows all produce 3,116 eligible user-Circle pairs. This fixture cannot validate an optimal inactivity threshold or monthly offline cadence.

Named checks pass independently of metrics: the obvious matches lead user 7's list; user 15 avoids repeated negotiation groups; the healthy promotion alternative leads user 23's list; user 42 gets five discoveries. Eligibility checks compare results directly to source rows and memberships rather than trusting candidate generation to validate itself.

Real evaluation needs member feedback and outcomes: accepted joins, participation after joining, usefulness and leader request burden. Offline topic diagnostics and passing tests do not substitute for these measurements.
