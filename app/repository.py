"""Bounded SQL reads; eligibility is enforced before anything is scored."""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.database import parse_time, utc_text

ACTIVE_DAYS = 30
FEED_WINDOW_DAYS = 30


class UserNotFound(Exception):
    pass


class UnknownTopic(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str
    slug: str
    description: str | None
    topic: str | None
    tags: frozenset[str]
    cover_image_url: str | None
    format: str
    join_policy: str
    max_members: int | None
    member_count: int
    last_activity_at: datetime
    feed_posts_30d: int
    chat_messages_30d: int
    mean_engagement: float
    observed_feed_posts: int = 0
    distinct_feed_authors: int = 0
    dominant_author_share: float = 0.0
    active_feed_weeks: int = 0

    def taxonomy(self, labels: dict[str, str]) -> frozenset[str]:
        return frozenset(({self.topic} if self.topic else set()) | (self.tags & labels.keys()))


@dataclass(frozen=True)
class Context:
    user_id: int
    as_of: datetime
    labels: dict[str, str]
    interests: frozenset[str]
    membership_topics: dict[str, float]
    candidates: tuple[Candidate, ...]
    requested_topic: str | None = None
    requested_format: str | None = None


def load_context(
    connection: sqlite3.Connection,
    user_id: int,
    *,
    topic: str | None = None,
    circle_format: str | None = None,
    active_days: int = ACTIVE_DAYS,
) -> Context:
    # A consistent read snapshot includes membership, capacity and activity inputs.
    connection.execute("BEGIN")
    if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        raise UserNotFound(user_id)
    snapshot = connection.execute("SELECT value FROM metadata WHERE key = 'snapshot_at'").fetchone()
    if snapshot is None:
        raise ValueError("Database must be seeded before serving recommendations")
    as_of = parse_time(snapshot[0])
    cutoff = utc_text(as_of - timedelta(days=active_days))
    feed_cutoff = utc_text(as_of - timedelta(days=FEED_WINDOW_DAYS))
    labels = {row[0]: row[1] for row in connection.execute("SELECT slug, label FROM topics")}
    if topic is not None and topic not in labels:
        raise UnknownTopic(topic)
    interests = frozenset(
        row[0]
        for row in connection.execute(
            """SELECT t.slug FROM user_interests ui
               JOIN topics t ON t.id = ui.topic_id WHERE ui.user_id = ?""",
            (user_id,),
        )
    )
    if topic is not None:
        interests = frozenset({topic})
    membership_topics: dict[str, float] = defaultdict(float)
    for row in connection.execute(
        """SELECT c.id, t.slug FROM memberships m
           JOIN circles c ON c.id = m.circle_id
           LEFT JOIN topics t ON t.id = c.primary_topic_id WHERE m.user_id = ?""",
        (user_id,),
    ):
        if row[1]:
            membership_topics[row[1]] += 1
    for row in connection.execute(
        """SELECT ct.tag FROM memberships m
           JOIN circle_tags ct ON ct.circle_id = m.circle_id WHERE m.user_id = ?""",
        (user_id,),
    ):
        if row[0] in labels:
            membership_topics[row[0]] += 0.5
    if membership_topics:
        maximum = max(membership_topics.values())
        membership_topics = {slug: weight / maximum for slug, weight in membership_topics.items()}

    tags: dict[int, set[str]] = defaultdict(set)
    for row in connection.execute("SELECT circle_id, tag FROM circle_tags"):
        tags[row[0]].add(row[1])
    authors: dict[int, Counter] = defaultdict(Counter)
    weeks: dict[int, set[int]] = defaultdict(set)
    engagement: dict[int, int] = defaultdict(int)
    # Read evidence columns only, never post bodies. The observed feed is not
    # assumed to reconcile with independently supplied rolling aggregates.
    for row in connection.execute(
        """SELECT circle_id, author_user_id, created_at,
                  reaction_count + comment_count + save_count AS engagement
           FROM activity WHERE created_at > ? AND created_at <= ?""",
        (feed_cutoff, utc_text(as_of)),
    ):
        authors[row["circle_id"]][row["author_user_id"]] += 1
        age_days = (as_of - parse_time(row["created_at"])).total_seconds() / 86400
        weeks[row["circle_id"]].add(int(age_days // 7))
        engagement[row["circle_id"]] += row["engagement"]
    rows = connection.execute(
        """SELECT c.*, t.slug AS topic
           FROM circles c LEFT JOIN topics t ON t.id = c.primary_topic_id
           WHERE c.access = 'public'
             AND (c.max_members IS NULL OR c.member_count < c.max_members)
             AND c.created_at <= ?
             AND c.last_activity_at >= ? AND c.last_activity_at <= ?
             AND (c.feed_posts_30d > 0 OR c.chat_messages_30d > 0)
             AND (? IS NULL OR c.format = ?)
             AND NOT EXISTS (SELECT 1 FROM memberships m
                             WHERE m.user_id = ? AND m.circle_id = c.id)
           ORDER BY c.id""",
        (utc_text(as_of), cutoff, utc_text(as_of), circle_format, circle_format, user_id),
    )
    candidates = tuple(
        Candidate(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            description=row["description"],
            topic=row["topic"],
            tags=frozenset(tags[row["id"]]),
            cover_image_url=row["cover_image_url"],
            format=row["format"],
            join_policy=row["join_policy"],
            max_members=row["max_members"],
            member_count=row["member_count"],
            last_activity_at=parse_time(row["last_activity_at"]),
            feed_posts_30d=row["feed_posts_30d"],
            chat_messages_30d=row["chat_messages_30d"],
            mean_engagement=engagement[row["id"]] / max(1, authors[row["id"]].total()),
            observed_feed_posts=authors[row["id"]].total(),
            distinct_feed_authors=len(authors[row["id"]]),
            dominant_author_share=max(authors[row["id"]].values(), default=0)
            / max(1, authors[row["id"]].total()),
            active_feed_weeks=len(weeks[row["id"]]),
        )
        for row in rows
    )
    return Context(
        user_id, as_of, labels, interests, dict(membership_topics), candidates, topic, circle_format
    )
