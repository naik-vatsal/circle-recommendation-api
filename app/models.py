"""Public response contracts, also exposed through OpenAPI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Topic(BaseModel):
    slug: str
    label: str


class CircleSummary(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    topic: Topic | None
    tags: list[str]
    cover_image_url: str | None
    format: Literal["in_person", "virtual", "hybrid"]
    join_policy: Literal["open", "request"]
    member_count: int
    max_members: int | None
    seats_available: int | None = Field(
        description="null means uncapped; availability is snapshot-only"
    )
    last_activity_at: datetime


class ScoreBreakdown(BaseModel):
    stated_interests: float
    membership_topics: float
    activity: float
    joining: float
    participation: float
    base_score: float
    diversity_penalty: float
    ranking_score: float


class Recommendation(BaseModel):
    rank: int
    circle: CircleSummary
    explanation: str
    fit: "MatchEvidence"
    activity_evidence: "ActivityEvidence"
    scores: ScoreBreakdown | None = None


class RecommendationResponse(BaseModel):
    user_id: int
    as_of: datetime
    algorithm_version: str
    strategy: Literal["request_topic", "stated_interests", "membership_topics", "cold_start"]
    requested_topic: str | None
    requested_format: Literal["in_person", "virtual", "hybrid"] | None
    requested_limit: int
    returned_count: int
    eligible_count: int
    diversity_limited: bool
    recommendations: list[Recommendation]


class MatchEvidence(BaseModel):
    kind: Literal["primary_interest", "related_interest", "membership_topic", "discovery"]
    matched_interests: list[Topic]


class ActivityEvidence(BaseModel):
    window_days: int = 30
    observed_feed_posts: int
    distinct_feed_authors: int
    active_feed_weeks: int
    last_activity_days_ago: int
    scope: Literal["observed_feed_only"] = "observed_feed_only"
