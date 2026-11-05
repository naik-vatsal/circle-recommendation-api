"""Behavioral and adversarial checks for product rules, independent of score snapshots."""

from dataclasses import replace

import pytest

from app.database import connect
from app.recommender import features
from app.repository import load_context


@pytest.fixture
def context(seeded_database):
    with connect(seeded_database, readonly=True) as connection:
        return load_context(connection, 7)


def test_secondary_matches_reveal_primary_focus_and_are_limited(client):
    response = client.get("/users/23/recommendations?limit=20").json()
    related = [r for r in response["recommendations"] if r["fit"]["kind"] == "related_interest"]
    assert len(related) == 1
    for item in related:
        focus = item["circle"]["topic"]
        assert focus["label"] in item["explanation"]
        assert "related suggestion" in item["explanation"]
        assert {t["slug"] for t in item["fit"]["matched_interests"]} == {"getting-promoted"}
        assert item["circle"]["topic"]["slug"] != "getting-promoted"


def test_breadth_adds_small_bounded_evidence_with_other_features_fixed(context):
    circle = context.candidates[0]
    narrow = replace(
        circle,
        observed_feed_posts=10,
        distinct_feed_authors=1,
        dominant_author_share=1.0,
        active_feed_weeks=2,
    )
    broad = replace(narrow, distinct_feed_authors=5, dominant_author_share=0.2)
    assert features(replace(narrow, observed_feed_posts=1000), context).participation == 0
    assert 0 < features(broad, context).participation <= 0.04


def test_request_filters_use_selected_topic_and_format_without_mutating_member(client):
    original = client.get("/users/7/recommendations").json()
    changed = client.get("/users/7/recommendations?topic=negotiation&format=hybrid").json()
    assert changed["strategy"] == "request_topic"
    assert changed["requested_topic"] == "negotiation"
    assert changed["requested_format"] == "hybrid"
    assert changed["recommendations"][0]["circle"]["topic"]["slug"] == "negotiation"
    assert all(r["circle"]["format"] == "hybrid" for r in changed["recommendations"])
    assert all(
        t["slug"] == "negotiation"
        for r in changed["recommendations"]
        for t in r["fit"]["matched_interests"]
    )
    assert client.get("/users/7/recommendations").json() == original


def test_observed_feed_window_and_week_buckets_are_exact(editable_client):
    client, path = editable_client
    with connect(path) as connection, connection:
        members = [
            row[0]
            for row in connection.execute(
                "SELECT user_id FROM memberships WHERE circle_id=5 ORDER BY user_id LIMIT 2"
            )
        ]
        connection.execute("DELETE FROM activity WHERE circle_id=5")
        timestamps = [
            "2026-09-21T00:00:00.000000Z",
            "2026-09-20T00:00:00.000000Z",
            "2026-09-13T00:00:00.000000Z",
            "2026-08-23T00:00:00.000000Z",
            "2026-08-22T00:00:00.000000Z",
            "2026-09-21T00:00:00.000001Z",
        ]
        for offset, timestamp in enumerate(timestamps):
            connection.execute(
                "INSERT INTO activity VALUES (?,5,?,'Observed post',1,2,3,?)",
                (100000 + offset, members[1] if offset == 3 else members[0], timestamp),
            )
    with connect(path, readonly=True) as connection:
        circle = next(c for c in load_context(connection, 7).candidates if c.id == 5)
    assert circle.observed_feed_posts == 4
    assert circle.distinct_feed_authors == 2
    assert circle.active_feed_weeks == 3
    assert circle.dominant_author_share == 0.75
    assert circle.mean_engagement == 6
    response = client.get("/users/7/recommendations?limit=20")
    assert "author_user_id" not in response.text


def test_format_filter_never_falls_back_to_other_formats(editable_client):
    client, path = editable_client
    with connect(path) as connection, connection:
        connection.execute("UPDATE circles SET access='unlisted' WHERE id!=5")
    response = client.get("/users/42/recommendations?format=virtual").json()
    assert response["eligible_count"] == 0
    assert response["recommendations"] == []
    assert response["diversity_limited"] is False


def test_new_membership_is_reflected_on_next_request(editable_client):
    client, path = editable_client
    assert 5 in [
        r["circle"]["id"] for r in client.get("/users/7/recommendations").json()["recommendations"]
    ]
    with connect(path) as connection, connection:
        connection.execute(
            "INSERT INTO memberships VALUES (7,5,'member','2026-09-21T00:00:00.000000Z')"
        )
    assert 5 not in [
        r["circle"]["id"] for r in client.get("/users/7/recommendations").json()["recommendations"]
    ]
