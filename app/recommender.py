"""Deterministic ranking, bounded participation evidence, and honest explanations."""

from dataclasses import dataclass
from math import isfinite, log1p

from app.models import (
    ActivityEvidence,
    CircleSummary,
    MatchEvidence,
    Recommendation,
    RecommendationResponse,
    ScoreBreakdown,
    Topic,
)
from app.repository import Candidate, Context

ALGORITHM_VERSION = "rules-v2"
DIVERSITY_WEIGHT = 0.04
MAX_RELATED_RESULTS = 1


@dataclass(frozen=True)
class Weights:
    interests: float = 0.55
    memberships: float = 0.10
    activity: float = 0.25
    participation: float = 0.04

    def __post_init__(self):
        if any(
            not isfinite(v) or v < 0
            for v in (self.interests, self.memberships, self.activity, self.participation)
        ):
            raise ValueError("Weights must be finite and nonnegative")


DEFAULT_WEIGHTS = Weights()


def saturate(value: float, ceiling: float) -> float:
    return min(1.0, log1p(max(0, value)) / log1p(ceiling))


@dataclass(frozen=True)
class Features:
    stated_interests: float
    membership_topics: float
    activity: float
    joining: float
    participation: float

    @property
    def base_score(self) -> float:
        return sum(
            (
                self.stated_interests,
                self.membership_topics,
                self.activity,
                self.joining,
                self.participation,
            )
        )


def match_evidence(circle: Candidate, context: Context) -> MatchEvidence:
    matches = circle.taxonomy(context.labels) & context.interests
    if circle.topic in matches:
        kind = "primary_interest"
    elif matches:
        kind = "related_interest"
    elif circle.topic and context.membership_topics.get(circle.topic, 0) > 0:
        kind = "membership_topic"
    else:
        kind = "discovery"
    return MatchEvidence(
        kind=kind,
        matched_interests=[Topic(slug=t, label=context.labels[t]) for t in sorted(matches)],
    )


def participation_quality(circle: Candidate) -> float:
    """A small feed-only proxy, not a measure of inclusion or meeting quality.

    One author earns zero regardless of their volume. Sparse observations are
    shrunk toward zero; the entire contribution is capped by its 4% weight.
    """
    breadth = min(1.0, max(0, circle.distinct_feed_authors - 1) / 5)
    balance = 1 - circle.dominant_author_share
    reliability = circle.observed_feed_posts / (circle.observed_feed_posts + 5)
    consistency = 0.8 + 0.2 * min(1.0, circle.active_feed_weeks / 5)
    return breadth * balance * reliability * consistency


def features(circle: Candidate, context: Context, weights: Weights = DEFAULT_WEIGHTS) -> Features:
    matches = circle.taxonomy(context.labels) & context.interests
    # Secondary tags are bounded below even a single primary-topic match.
    if circle.topic in matches:
        explicit = min(1.0, 0.9 + 0.1 * (len(matches) - 1))
    elif matches:
        explicit = min(0.65, 0.45 + 0.1 * (len(matches) - 1))
    else:
        explicit = 0.0
    known_tags = circle.tags & context.labels.keys()
    membership = 0.8 * context.membership_topics.get(circle.topic, 0.0)
    if known_tags:
        # Extra unrelated tags must not dilute an existing affinity.
        membership += 0.2 * max(context.membership_topics.get(t, 0) for t in known_tags)
    age_days = max(0.0, (context.as_of - circle.last_activity_at).total_seconds() / 86400)
    activity = (
        0.40 * saturate(circle.feed_posts_30d, 20)
        + 0.25 * saturate(circle.chat_messages_30d, 200)
        + 0.20 * 2 ** (-age_days / 14)
        + 0.15 * saturate(circle.mean_engagement, 20)
    )
    return Features(
        stated_interests=weights.interests * explicit,
        membership_topics=weights.memberships * membership,
        activity=weights.activity * activity,
        joining=0.06 if circle.join_policy == "open" else 0.02,
        participation=weights.participation * participation_quality(circle),
    )


def topic_group(circle: Candidate, labels: dict[str, str]) -> tuple:
    if circle.topic:
        return ("primary", circle.topic)
    taxonomy = circle.taxonomy(labels)
    return ("tags", *sorted(taxonomy)) if taxonomy else ("untagged", circle.id)


def similarity(left: Candidate, right: Candidate, labels: dict[str, str]) -> float:
    a, b = left.taxonomy(labels), right.taxonomy(labels)
    return len(a & b) / len(a | b) if a | b else 0.0


def explain(circle: Candidate, context: Context) -> str:
    fit = match_evidence(circle, context)
    focus = context.labels.get(circle.topic)
    if fit.kind == "primary_interest":
        source = (
            "the topic you chose for this search"
            if context.requested_topic
            else "one of your selected interests"
        )
        opening = f"Focuses on {focus}, {source}."
    elif fit.kind == "related_interest":
        label = fit.matched_interests[0].label
        if focus:
            opening = f"Focuses on {focus} and also covers {label}, a related suggestion."
        else:
            opening = f"Lists {label} as a topic tag; its main focus is not specified."
    elif fit.kind == "membership_topic":
        opening = f"Focuses on {focus}, a topic in Circles you've joined."
    else:
        opening = f"Explore a Circle focused on {focus}." if focus else "Explore an active Circle."
    if circle.distinct_feed_authors >= 2:
        activity = f"{circle.distinct_feed_authors} people posted in the observed feed in the past 30 days."
    elif circle.feed_posts_30d and circle.chat_messages_30d:
        activity = "Recent posts and chat activity."
    elif circle.feed_posts_30d:
        activity = "Recent feed activity."
    else:
        activity = "Recent chat activity."
    joining = "Join directly." if circle.join_policy == "open" else "You can request to join."
    return f"{opening} {activity} {joining}"


@dataclass(frozen=True)
class RankedCandidate:
    circle: Candidate
    features: Features
    diversity_penalty: float

    @property
    def ranking_score(self) -> float:
        return self.features.base_score - self.diversity_penalty


def rank_candidates(
    context: Context,
    limit: int = 5,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
    diversify: bool = True,
) -> list[RankedCandidate]:
    """Internal comparison hooks are intentionally not exposed as HTTP parameters."""
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    remaining = {c.id: (c, features(c, context, weights)) for c in context.candidates}
    selected: list[RankedCandidate] = []
    groups: set[tuple] = set()
    related_count = 0
    # Cache running maximum overlap: O(N*K), with bounded taxonomy sets.
    overlap = dict.fromkeys(remaining, 0.0)
    while len(selected) < limit:
        options = []
        for circle, score in remaining.values():
            if diversify:
                if topic_group(circle, context.labels) in groups:
                    continue
                if (
                    match_evidence(circle, context).kind == "related_interest"
                    and related_count >= MAX_RELATED_RESULTS
                ):
                    continue
            penalty = DIVERSITY_WEIGHT * overlap[circle.id] if diversify else 0.0
            options.append((score.base_score - penalty, circle.id, circle, score, penalty))
        if not options:
            break
        _, _, circle, score, penalty = min(options, key=lambda row: (-row[0], row[1]))
        selected.append(RankedCandidate(circle, score, penalty))
        groups.add(topic_group(circle, context.labels))
        related_count += match_evidence(circle, context).kind == "related_interest"
        del remaining[circle.id]
        if diversify:
            for candidate, _ in remaining.values():
                overlap[candidate.id] = max(
                    overlap[candidate.id], similarity(candidate, circle, context.labels)
                )
    return selected


def recommend(
    context: Context, limit: int = 5, include_scores: bool = False
) -> RecommendationResponse:
    selected = rank_candidates(context, limit)
    results = []
    for rank, item in enumerate(selected, 1):
        circle, score = item.circle, item.features
        results.append(
            Recommendation(
                rank=rank,
                circle=CircleSummary(
                    id=circle.id,
                    name=circle.name,
                    slug=circle.slug,
                    description=circle.description,
                    topic=Topic(slug=circle.topic, label=context.labels[circle.topic])
                    if circle.topic
                    else None,
                    tags=sorted(circle.tags),
                    cover_image_url=circle.cover_image_url,
                    format=circle.format,
                    join_policy=circle.join_policy,
                    member_count=circle.member_count,
                    max_members=circle.max_members,
                    seats_available=circle.max_members - circle.member_count
                    if circle.max_members is not None
                    else None,
                    last_activity_at=circle.last_activity_at,
                ),
                explanation=explain(circle, context),
                fit=match_evidence(circle, context),
                activity_evidence=ActivityEvidence(
                    observed_feed_posts=circle.observed_feed_posts,
                    distinct_feed_authors=circle.distinct_feed_authors,
                    active_feed_weeks=circle.active_feed_weeks,
                    last_activity_days_ago=int(
                        (context.as_of - circle.last_activity_at).total_seconds() // 86400
                    ),
                ),
                scores=ScoreBreakdown(
                    stated_interests=score.stated_interests,
                    membership_topics=score.membership_topics,
                    activity=score.activity,
                    joining=score.joining,
                    participation=score.participation,
                    base_score=score.base_score,
                    diversity_penalty=item.diversity_penalty,
                    ranking_score=item.ranking_score,
                )
                if include_scores
                else None,
            )
        )
    return RecommendationResponse(
        user_id=context.user_id,
        as_of=context.as_of,
        algorithm_version=ALGORITHM_VERSION,
        strategy="request_topic"
        if context.requested_topic
        else (
            "stated_interests"
            if context.interests
            else ("membership_topics" if context.membership_topics else "cold_start")
        ),
        requested_topic=context.requested_topic,
        requested_format=context.requested_format,
        requested_limit=limit,
        returned_count=len(results),
        eligible_count=len(context.candidates),
        diversity_limited=len(results) < min(limit, len(context.candidates)),
        recommendations=results,
    )
