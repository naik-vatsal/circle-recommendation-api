"""Offline diagnostics, not an estimate of real-member satisfaction.

Run `python -m scripts.evaluate` to print deterministic JSON; --output saves it.
The input is imported into a temporary database, never the application database.
"""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import ROOT
from app.database import connect, parse_time
from app.recommender import ALGORITHM_VERSION, DEFAULT_WEIGHTS, Weights, rank_candidates
from app.repository import load_context
from app.seed import seed_database


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "data").glob("*.json")):
        digest.update(path.name.encode())
        canonical = json.dumps(
            json.loads(path.read_text(encoding="utf8")), sort_keys=True, separators=(",", ":")
        )
        digest.update(canonical.encode("utf8"))
    return digest.hexdigest()


def evaluate() -> dict:
    with TemporaryDirectory(prefix="circles-evaluation-") as directory:
        database = Path(directory) / "evaluation.sqlite3"
        seed_database(database, ROOT / "data")
        users = json.loads((ROOT / "data/users.json").read_text(encoding="utf8"))
        circles = {
            c["id"]: c for c in json.loads((ROOT / "data/circles.json").read_text(encoding="utf8"))
        }
        memberships = json.loads((ROOT / "data/memberships.json").read_text(encoding="utf8"))
        joined = {(m["user_id"], m["circle_id"]) for m in memberships}
        contexts = []
        for user in sorted(users, key=lambda u: u["id"]):
            with connect(database, readonly=True) as connection:
                contexts.append(load_context(connection, user["id"]))

        variants = {
            "activity_and_access": (Weights(interests=0, memberships=0, participation=0), False),
            "topic_ranked": (DEFAULT_WEIGHTS, False),
            "final": (DEFAULT_WEIGHTS, True),
            "without_participation": (replace(DEFAULT_WEIGHTS, participation=0), True),
        }
        metrics = {}
        rankings = {}
        for name, (weights, diversify) in variants.items():
            slots = duplicates = primary_matches = attainable = covered = related = violations = 0
            exposed = set()
            first = Counter()
            rankings[name] = {}
            for context in contexts:
                selected = rank_candidates(context, 5, weights=weights, diversify=diversify)
                rankings[name][context.user_id] = [r.circle.id for r in selected]
                if selected:
                    first[selected[0].circle.id] += 1
                topics = [r.circle.topic for r in selected if r.circle.topic]
                duplicates += len(topics) - len(set(topics))
                available = {c.topic for c in context.candidates} & context.interests
                attainable += len(available)
                covered += len(set(topics) & available)
                for item in selected:
                    c = item.circle
                    slots += 1
                    exposed.add(c.id)
                    primary_matches += c.topic in context.interests
                    related += c.topic not in context.interests and bool(
                        c.taxonomy(context.labels) & context.interests
                    )
                    # Check independently against source rows, rather than trusting
                    # candidate generation to validate its own output.
                    source = circles[c.id]
                    age = (
                        context.as_of - parse_time(source["last_activity_at"])
                    ).total_seconds() / 86400
                    invalid = (
                        source["access"] != "public"
                        or (context.user_id, c.id) in joined
                        or (
                            source["max_members"] is not None
                            and source["member_count"] >= source["max_members"]
                        )
                        or not 0 <= age <= 30
                        or not (source["feed_posts_30d"] or source["chat_messages_30d"])
                    )
                    violations += bool(invalid)
            metrics[name] = {
                "returned_slots": slots,
                "eligibility_violations": violations,
                "primary_interest_slots": primary_matches,
                "related_interest_slots": related,
                "repeated_primary_topic_slots": duplicates,
                "attainable_interest_coverage": round(covered / max(1, attainable), 4),
                "distinct_circles_exposed": len(exposed),
                "largest_first_position_share": round(
                    max(first.values(), default=0) / len(contexts), 4
                ),
            }

        baseline = rankings["final"]
        sensitivity = {}
        for feature in ("interests", "memberships", "activity", "participation"):
            for multiplier in (0.9, 1.1):
                weights = replace(
                    DEFAULT_WEIGHTS, **{feature: getattr(DEFAULT_WEIGHTS, feature) * multiplier}
                )
                overlaps = []
                same_top = 0
                for context in contexts:
                    candidate = [r.circle.id for r in rank_candidates(context, 5, weights=weights)]
                    original = baseline[context.user_id]
                    overlaps.append(len(set(candidate) & set(original)) / max(1, len(original)))
                    same_top += candidate[:1] == original[:1]
                sensitivity[f"{feature}_x{multiplier}"] = {
                    "mean_top5_overlap": round(sum(overlaps) / len(overlaps), 4),
                    "same_first_position_share": round(same_top / len(contexts), 4),
                }
        recency = {}
        for days in (30, 45, 60):
            counts = []
            for user in users:
                with connect(database, readonly=True) as connection:
                    counts.append(
                        len(load_context(connection, user["id"], active_days=days).candidates)
                    )
            recency[str(days)] = {"eligible_user_circle_pairs": sum(counts)}

        cases = {str(i): baseline[i] for i in (7, 15, 23, 42)}
        scenario_checks = {
            "cold_start_has_five": len(cases["42"]) == 5,
            "obvious_matches_first_two": set(cases["7"][:2]) == {5, 6},
            "negotiation_not_repeated": len(set(cases["15"]) & {10, 11, 12}) == 1,
            "healthy_promotion_first": cases["23"][0] == 22,
            "full_and_inactive_absent": not set(cases["23"]) & {20, 21, 32},
        }
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "dataset_sha256": source_fingerprint(),
            "as_of": contexts[0].as_of.isoformat(),
            "users_evaluated": len(contexts),
            "limit": 5,
            "interpretation": "Synthetic-data diagnostics only; no relevance labels, causal lift, or member-outcome claims.",
            "variants": metrics,
            "weight_sensitivity": sensitivity,
            "recency_window_sensitivity": recency,
            "scenario_top5_circle_ids": cases,
            "scenario_checks": scenario_checks,
            "passed": all(scenario_checks.values())
            and all(m["eligibility_violations"] == 0 for m in metrics.values()),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check", type=Path, help="Fail if a saved report differs from current results"
    )
    args = parser.parse_args()
    result = evaluate()
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check and json.loads(args.check.read_text(encoding="utf8")) != result:
        raise SystemExit("Evaluation report is stale. Regenerate it before submitting.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf8")
        print(f"Saved evaluation to {args.output}")
    elif args.check:
        print(f"Evaluation report matches current results: {args.check}")
    else:
        print(rendered)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
