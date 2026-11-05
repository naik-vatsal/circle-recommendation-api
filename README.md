# Circle Recommendations API

A FastAPI service that recommends relevant, active Lean In Circles from the supplied synthetic dataset. Each result explains why it was selected and how to join.

[Technical design](docs/design.md) · [Database schema](docs/schema.md) · [Ranking rules](docs/ranking.md) · [Evaluation](docs/evaluation.md)

## Run locally

Install **Python 3.11+** and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/naik-vatsal/circle-recommendation-api.git
cd circle-recommendation-api
uv sync --locked
uv run --locked uvicorn app.main:app --reload
```

The first startup imports the sample data into a local SQLite database. Open the [API explorer](http://127.0.0.1:8000/docs), expand **GET /users/{user_id}/recommendations**, select **Try it out**, and enter `7`. Press **Ctrl+C** in the terminal to stop the server.

<details>
<summary>Run with pip instead of uv</summary>

Run these commands from the cloned project folder.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

**macOS or Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --reload
```

</details>

## Use the API

```http
GET /users/7/recommendations?limit=5&include_scores=true
```

[Open this example in your browser](http://127.0.0.1:8000/users/7/recommendations?limit=5&include_scores=true) after starting the API. The response includes ranked Circles, their formats and join policies, a short explanation, and the evidence behind each recommendation.

| Parameter | Default | Behavior |
| --- | --- | --- |
| `user_id` | Required | Member ID. An unknown member returns 404. |
| `limit` | `5` | Maximum results, from 1 to 20. Eligibility and diversity rules can shorten the list. |
| `include_scores` | `false` | Include the score contributions for each result. |
| `topic` | None | Override the member's topic interests for this request. See [available topic slugs](http://127.0.0.1:8000/topics). |
| `format` | None | Filter to `virtual`, `hybrid`, or `in_person`. |

The service excludes full, inactive, and unlisted Circles, plus Circles the member has already joined. It ranks eligible Circles using topic fit, activity, participation, and ease of joining, then limits repeated topics. Activity is measured against the dataset snapshot of **September 21, 2026 at 00:00 UTC**, which the response reports as `as_of`.

## Try the assignment scenarios

| Scenario | Member ID | What to look for |
| --- | ---: | --- |
| Cold start | `42` | Five active, available Circles across different primary topics. |
| Clear matches | `7` | Women Who Lead and Speak Up Circle occupy the top two spots. |
| Duplicate topics | `15` | Confident Voices and The Negotiation Table lead the list, with at most one Circle from the duplicate negotiation group. |
| Unavailable Circles | `23` | Level Up Collective ranks first. Full and inactive Circles are excluded. |

## Verify

```sh
uv run --locked python -m scripts.check
```

This runs the 25 tests, checks lint and formatting, and verifies the saved evaluation. The tests cover all 100 seeded members and the four assignment scenarios. The [evaluation notes](docs/evaluation.md) explain how the ranking variants compare on the supplied data.

## AI use

AI assistance supported implementation, test development, and review of edge cases. I checked the changes with automated tests, reproducible ranking comparisons, and local API requests. I remain responsible for the submitted solution and its design decisions.
