# Ranking rules and rationale

The ranker is in `app/recommender.py`; eligibility and feature reads are in `app/repository.py`. `rules-v2` is deterministic. No user IDs, Circle IDs or planted names influence scoring; ascending Circle ID only breaks exact ties.

## Eligibility and member controls

A candidate must be public, created by the observation time, not already joined, below capacity, active within `[as_of - 30 days, as_of]` inclusively, and have positive feed or chat volume. Null capacity is uncapped; zero/full/overfull capacity is ineligible. Request-to-join is available but explained as a request, never guaranteed admission.

The optional `format` filter is exact: `virtual`, `hybrid` and `in_person` remain distinct. It runs before scoring and diversity and never relaxes eligibility to fill a list. Without a filter, no remote-format bonus applies. Meeting location is absent, so no geographic compatibility is claimed.

An optional canonical `topic` replaces profile interests for that request. Membership affinity remains weaker supporting evidence. Stored interests never change. Unknown topics/formats return 422. `/topics` exposes valid choices. `strategy=request_topic` distinguishes explicit search intent from profile personalization.

## Features and equations

Let `T(c)` contain a Circle's primary topic and known taxonomy tags, and `I(u)` contain effective interests. Repeated tags count once; unknown tags are retained but do not infer interests.

**Explicit affinity E:** A primary-topic match starts at `0.9`; add `0.1` per additional distinct matching topic and cap at `1`. Tag-only matches start at `0.45`, receive the same additional-match increment, and cap at `0.65`. No match contributes zero. Primary evidence is stronger in this feature; final scores also reflect other terms, so this is not an unconditional priority tier.

**Membership affinity M:** Add `1` per joined primary topic and `0.5` per distinct known tag. A primary topic repeated as a tag receives both contributions. Normalize topic totals by the largest total to produce `w(t)` in `[0,1]`.

```text
M = 0.8 * w(candidate.primary_topic)
  + 0.2 * max(w(t) for known candidate tags)
```

Missing components contribute zero. The strongest tag prevents unrelated tags from diluting an existing affinity. This signal is weaker than stated intent.

**Activity A:** Define `L(x, cap) = min(1, log(1 + max(0, x)) / log(1 + cap))`, fractional `age` in days since last activity, and `g` as mean reactions + comments + saves per observed feed post in `(as_of - 30 days, as_of]`. No observed posts means zero mean engagement.

```text
A = 0.40 * L(feed_posts_30d, 20)
  + 0.25 * L(chat_messages_30d, 200)
  + 0.20 * 2^(-age / 14)
  + 0.15 * L(g, 20)
```

Volume and engagement saturate. Rolling counts and observed feed rows are not assumed to reconcile. The last-activity gate is authoritative; feed evidence cannot rescue a stale Circle.

**Participation P:** Let `n` be observed feed posts, `a` distinct authors, `d` the largest author's share, and `b` nonempty relative-week buckets (`floor(age_days / 7)`, at most five within the window).

```text
P = min(1, max(0, a - 1) / 5)
  * (1 - d)
  * n / (n + 5)
  * (0.8 + 0.2 * min(1, b / 5))
```

No posts or one author earn zero. More independent contributors, less concentration and repeated participation support peer interaction. Five pseudo-observations shrink sparse evidence; six authors saturate breadth. These constants are hypotheses, not calibrated confidence. Missing data earns no bonus rather than a negative score or exclusion. Quiet members, private support and meetings are unobserved. This is not an inclusion, trust or safety score.

**Joining J:** `0.06` for open joining, `0.02` for request-to-join.

```text
base_score = 0.55 * E + 0.10 * M + 0.25 * A + 0.04 * P + J
```

Every default contribution is bounded and the base score is at most 1. Cold-start members have zero interest/membership contributions; no profile-completeness penalty applies. Scores are ranking utilities, not probabilities. Sensitivity weights are internal evaluation hooks, not public request controls.

## List selection

Select greedily by `base_score - 0.04 * maximum_topic_overlap_with_previous_selections`. Overlap is Jaccard similarity of canonical topic sets; an empty union has zero similarity.

Allow at most one Circle per primary topic and one `related_interest` result (a tag match without a primary-topic match). Topic-less groups use their exact known tag set; untagged groups remain independent. Constraints are not relaxed when a list is short. `diversity_limited` covers shortening caused by either list constraint; eligibility/filter shortages alone do not set it.

Format filtering lets a member choose an alternative before the cap applies. The default cap can still hide different groups on a broad topic; it is a conservative duplicate proxy, not semantic duplicate detection. Richer clustering needs feedback and better group metadata.

Cached running overlap gives `O(N*K)` comparisons over small topic sets. Scores are nonincreasing in selection order; base scores need not be. Smaller limits are prefixes of the same ranking, independent of input order.

## Explanation contract

`fit.kind` distinguishes `primary_interest`, `related_interest`, `membership_topic` and `discovery`; `fit.matched_interests` lists the exact intersection used in scoring. Primary explanations name the main topic. Related explanations disclose the main focus and matched tag; missing main focus is stated explicitly. Discovery never invents an interest or identity.

`activity_evidence` contains observed feed counts, a 30-day window, occupied relative-week buckets and days since recorded activity. It contains no author IDs, post bodies, other-member profiles, or fractions of the entire membership. Explanations report observed author counts without claiming that everyone participates. Join policy is explicit.

## What the fixture cannot validate

Timestamps and rolling counts belong to the fixed observation time. Lean In describes most Circles as meeting monthly; upcoming meetings, leader confirmation and response patterns are needed before labeling quieter groups inactive. [Lean In's guidance](https://leanin.org/circles/)

The 30/45/60-day experiments find no candidate differences and cannot establish an optimal inactivity threshold. Exclusion of seven-month-old records is tested; healthy offline groups are not represented well enough to validate production policy.

No member-outcome labels exist. Coverage, duplication, exposure and sensitivity are diagnostics only. The participation bonus changes exposure without improving measured topic coverage; it remains small pending feedback. Track accepted joins, sustained participation, usefulness and leader request load. Do not infer fairness or outcome improvements from synthetic data.
