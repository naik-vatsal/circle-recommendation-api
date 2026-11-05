import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from app.config import ROOT
from app.database import parse_time


def get_recommendations(client, user_id, **params):
    response = client.get(f"/users/{user_id}/recommendations", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_obvious_matches_cover_both_selected_interests(client):
    response = get_recommendations(client, 7)
    assert {r["circle"]["id"] for r in response["recommendations"][:2]} == {5, 6}
    assert response["strategy"] == "stated_interests"
    reasons = " ".join(r["explanation"] for r in response["recommendations"][:2])
    assert "Leadership skills" in reasons and "Public speaking" in reasons


def test_negotiation_duplicates_do_not_fill_list_even_at_large_limit(client):
    response = get_recommendations(client, 15, limit=20)
    ids = [r["circle"]["id"] for r in response["recommendations"]]
    assert len(set(ids) & {10, 11, 12}) == 1
    assert ids[0] in {10, 11, 12, 13}
    assert 13 in ids[:2]  # Confidence is also a stated interest.


def test_full_and_inactive_circles_are_excluded(client):
    response = get_recommendations(client, 23, limit=20)
    ids = [r["circle"]["id"] for r in response["recommendations"]]
    assert ids[0] == 22
    assert not set(ids) & {20, 21, 32}
    assert "request to join" in response["recommendations"][0]["explanation"]


def test_cold_start_has_diverse_honest_suggestions(client):
    response = get_recommendations(client, 42)
    assert response["strategy"] == "cold_start"
    assert response["returned_count"] == 5
    assert (
        len(
            {
                r["circle"].get("topic", {}).get("slug")
                if r["circle"]["topic"]
                else r["circle"]["id"]
                for r in response["recommendations"]
            }
        )
        == 5
    )
    for item in response["recommendations"]:
        assert "your interest" not in item["explanation"]
        assert "you've joined" not in item["explanation"]


def test_every_seeded_member_gets_valid_recommendations(client):
    users = json.loads((ROOT / "data/users.json").read_text(encoding="utf8"))
    memberships = json.loads((ROOT / "data/memberships.json").read_text(encoding="utf8"))
    circles = {
        circle["id"]: circle
        for circle in json.loads((ROOT / "data/circles.json").read_text(encoding="utf8"))
    }
    joined = defaultdict(set)
    for membership in memberships:
        joined[membership["user_id"]].add(membership["circle_id"])

    assert users
    for user in users:
        user_id = user["id"]
        response = get_recommendations(client, user_id, include_scores=True)
        assert response["as_of"] == "2026-09-21T00:00:00Z"
        results = response["recommendations"]
        assert len(results) == response["returned_count"] == 5, user_id
        assert len({item["circle"]["id"] for item in results}) == len(results), user_id
        assert [item["rank"] for item in results] == [1, 2, 3, 4, 5], user_id
        scores = [item["scores"]["ranking_score"] for item in results]
        assert scores == sorted(scores, reverse=True), user_id
        topics = []
        for item in results:
            circle = circles[item["circle"]["id"]]
            context = (user_id, circle["id"])
            assert circle["id"] not in joined[user_id], context
            assert circle["access"] == "public", context
            capacity = circle["max_members"]
            assert capacity is None or circle["member_count"] < capacity, context
            age = parse_time(response["as_of"]) - parse_time(circle["last_activity_at"])
            assert 0 <= age.total_seconds() <= 30 * 24 * 60 * 60, context
            assert circle["feed_posts_30d"] or circle["chat_messages_30d"], context
            assert item["explanation"], context
            if circle["topic"]:
                topics.append(circle["topic"])
        assert len(topics) == len(set(topics)), user_id


def test_request_validation(client):
    route = "/users/7/recommendations"
    for suffix in (
        "?limit=0",
        "?limit=21",
        "?include_scores=maybe",
        "?format=remote",
        "?topic=not-a-topic",
    ):
        assert client.get(route + suffix).status_code == 422, suffix
    assert client.get("/users/99999/recommendations").status_code == 404
    assert client.get("/users/999999999999999999999999999999/recommendations").status_code == 422


def test_defaults_null_contract_and_determinism(client):
    first = get_recommendations(client, 42)
    assert first == get_recommendations(client, 42)
    assert all(r["scores"] is None for r in first["recommendations"])
    all_items = get_recommendations(client, 42, limit=20)["recommendations"]
    uncapped = [r["circle"] for r in all_items if r["circle"]["max_members"] is None]
    assert uncapped
    assert all(c["seats_available"] is None for c in uncapped)


def test_smaller_limit_is_prefix_of_same_ranking(client):
    full = get_recommendations(client, 7, limit=10)["recommendations"]
    assert get_recommendations(client, 7, limit=3)["recommendations"] == full[:3]


def test_health_docs_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    assert "/users/{user_id}/recommendations" in client.get("/openapi.json").json()["paths"]
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"
    topics = client.get("/topics").json()
    assert len(topics) == 22
    assert {"slug": "negotiation", "label": "Negotiation"} in topics


def test_concurrent_requests_use_independent_connections(client):
    ids = [7, 15, 23, 42] * 4
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda user_id: get_recommendations(client, user_id), ids))
    assert [r["user_id"] for r in results] == ids
