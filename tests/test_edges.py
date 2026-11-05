from pathlib import Path

from app.database import connect


def edit(path: Path, sql: str, parameters=()):
    with connect(path) as connection, connection:
        connection.execute(sql, parameters)


def ids(client, user_id=42):
    response = client.get(f"/users/{user_id}/recommendations?limit=20")
    assert response.status_code == 200
    return [r["circle"]["id"] for r in response.json()["recommendations"]]


def test_recent_timestamp_without_actual_activity_is_not_enough(editable_client):
    client, path = editable_client
    edit(path, "UPDATE circles SET feed_posts_30d=0, chat_messages_30d=0 WHERE id=5")
    assert 5 not in ids(client, 7)


def test_recent_activity_cannot_make_an_unlisted_circle_discoverable(editable_client):
    client, path = editable_client
    edit(path, "UPDATE circles SET access='unlisted' WHERE id=5")
    assert 5 not in ids(client, 7)


def test_diversity_returns_short_list_instead_of_relaxing_topic_cap(editable_client):
    client, path = editable_client
    edit(path, "UPDATE circles SET access='unlisted' WHERE id NOT IN (10,11,12)")
    response = client.get("/users/15/recommendations").json()
    assert response["eligible_count"] == 3
    assert response["returned_count"] == 1
    assert response["diversity_limited"] is True


def test_membership_only_user_has_weak_personalization(editable_client):
    client, path = editable_client
    edit(path, "DELETE FROM user_interests WHERE user_id=7")
    response = client.get("/users/7/recommendations?include_scores=true").json()
    assert response["strategy"] == "membership_topics"
    assert all(r["scores"]["stated_interests"] == 0 for r in response["recommendations"])
    assert any(r["scores"]["membership_topics"] > 0 for r in response["recommendations"])


def test_profile_completeness_or_personal_details_do_not_affect_ranking(editable_client):
    client, path = editable_client
    before = client.get("/users/7/recommendations?include_scores=true").json()
    edit(
        path,
        """UPDATE users SET first_name='Changed', has_photo=0, bio=NULL,
                 job_title=NULL, industry=NULL, company=NULL, location=NULL,
                 profile_completeness=0 WHERE id=7""",
    )
    assert client.get("/users/7/recommendations?include_scores=true").json() == before


def test_recency_boundary_is_inclusive_and_strictly_older_is_excluded(editable_client):
    client, path = editable_client
    # Isolate eligibility from ranking: another Circle on the same topic can
    # legitimately win the single topic slot even when #5 remains eligible.
    edit(path, "UPDATE circles SET access='unlisted' WHERE id != 5")
    edit(path, "UPDATE circles SET last_activity_at='2026-08-22T00:00:00.000000Z' WHERE id=5")
    assert 5 in ids(client, 7)
    edit(path, "UPDATE circles SET last_activity_at='2026-08-21T23:59:59.999999Z' WHERE id=5")
    assert 5 not in ids(client, 7)
