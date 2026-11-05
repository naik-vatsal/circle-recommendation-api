# Database schema

The executable source of truth is [`app/schema.sql`](../app/schema.sql). SQLite needs no separate server and makes the submission easy to run. The schema preserves the source fields while normalizing repeated relationships; production would use migrations and a managed relational database.

## Tables and relationships

| Table | Key and relationships | Purpose |
| --- | --- | --- |
| `metadata` | `key` primary key | Schema version and snapshot observation time |
| `topics` | `id` PK; unique `slug` | Canonical topic labels and domain |
| `users` | `id` PK | Original member profiles and account join time |
| `user_interests` | PK `(user_id, topic_id)`; FKs to users/topics | Many-to-many, deduplicated stated interests |
| `circles` | `id` PK; unique `slug`; nullable topic FK | Circle details, policies, format, snapshot member count/capacity and activity aggregates |
| `circle_tags` | PK `(circle_id, tag)`; Circle FK | Deduplicated free-form tags; unknown tags retained without inventing taxonomy |
| `memberships` | PK `(user_id, circle_id)`; user/Circle FKs | Many-to-many membership, leader role and join time |
| `activity` | `id` PK; composite FK `(author_user_id, circle_id)` to memberships | Feed posts and engagement, with authors required to belong to the Circle |

Relationship outline: `users → user_interests → topics ← circles`; `users → memberships ← circles`; `circles → circle_tags`; `memberships → activity`.

Both leaders and members use the same membership table; leader profiles can be joined through `users`, with no duplicate person representation. Networks are not present in the input, so no fictional network records or signal are introduced.

## Integrity and semantics

- Foreign keys are enabled on **every connection**, including imports and tests. Composite membership keys reject duplicates, and composite activity references reject posts by nonmembers.
- Checks restrict format, visibility, join policy and role; require nonnegative counts/capacity; restrict photo to a boolean and completeness to `[0,1]`.
- Capacity is nullable for uncapped Circles. Zero capacity and over-capacity rows are representable but ineligible, allowing faithful imports of operational snapshots.
- `member_count` is an explicit capacity snapshot. Do not silently recalculate it from memberships, which may be partial in future exports. All counts happen to match in this fixture. A production membership-write transaction must update capacity atomically.
- ISO timestamps are normalized on import to fixed-width UTC text, preserving chronological SQL ordering across input time zones. Source timestamps after the observation time fail import.
- Topic/tag duplicates in arrays are collapsed. Missing topic, description and image remain null. Unknown interest/primary-topic slugs fail import because they must reference the taxonomy; free-form tags are preserved and ignored for affinity if unknown.
- The schema retains profile fields and post bodies, but ranking reads neither; only aggregate engagement is used. No raw chat is present.
- The importer locks before checking its snapshot marker. All row inserts and metadata commit together or roll back together; existing imported databases are preserved. Schema creation itself is safe to repeat. An incompatible recorded schema version fails rather than attempting an implicit migration.

## Index rationale

| Index | Reason |
| --- | --- |
| PK on `memberships(user_id, circle_id)` | Fetch a member's groups and efficient `NOT EXISTS` exclusion |
| PK on `user_interests(user_id, topic_id)` | Fetch interests and enforce uniqueness |
| PK on `circle_tags(circle_id, tag)` | Fetch tags and enforce uniqueness |
| `circles(access, last_activity_at)` | Restrict discovery to public groups in the activity window; capacity comparison is a residual filter |
| `memberships(circle_id, role)` | Reverse membership and leader lookup; complements user-first PK |
| `activity(circle_id, created_at)` | Per-Circle feed/engagement inspection; complements the batch time-window index |
| `activity(created_at)` | Current batch query for the observation window without reading post bodies |
| `circles(primary_topic_id)` | Topic lookup and FK maintenance; useful for future topic-first candidate retrieval |
| Unique topic/Circle slugs | Stable identities and duplicate prevention |

The current query batch reads all Circle tags and the observed feed's author/time/engagement columns within the 30-day window, then scores eligible Circles. This is appropriate for 40 groups, not a claim of large-scale retrieval. Post bodies and other members' profiles are not loaded by ranking. The batch computes distinct-author counts, dominant-author share, relative-week buckets and mean engagement, without assuming the feed reconciles with the separately supplied aggregate counts. Author IDs stay internal and never appear in recommendation responses. Production would bound feature retrieval to a candidate pool, precompute aggregates, and inspect query plans before adding indexes on profile fields.

Deletion of a user or Circle with authored activity is intentionally restricted by the activity membership reference; this read-only API has no deletion workflow. Production should define soft deletion, erasure and post-retention policies explicitly instead of relying on cascading deletes.
