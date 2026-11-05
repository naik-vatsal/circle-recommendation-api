"""HTTP entry point. Start with: uv run uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse

from app.config import Settings
from app.database import connect
from app.models import RecommendationResponse, Topic
from app.recommender import recommend
from app.repository import UnknownTopic, UserNotFound, load_context
from app.seed import seed_database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        seed_database(settings.database_path, settings.data_dir)
        application.state.settings = settings
        yield

    application = FastAPI(
        title="Circle Recommendations API",
        version="2.0.0",
        description=(
            "Relevant, active, available Circles with member-facing explanations. "
            "Uses the supplied synthetic snapshot's reference time; no authentication in this local demo. "
            "Circle locations are unavailable: confirm meeting details for in-person and hybrid Circles."
        ),
        lifespan=lifespan,
    )

    @application.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @application.get("/health", tags=["Operations"])
    def health(request: Request) -> dict:
        with connect(request.app.state.settings.database_path, readonly=True) as connection:
            snapshot = connection.execute(
                "SELECT value FROM metadata WHERE key = 'snapshot_at'"
            ).fetchone()
        return {"status": "ok", "snapshot_at": snapshot[0]}

    @application.get(
        "/topics",
        response_model=list[Topic],
        tags=["Recommendations"],
        summary="List valid topic choices",
    )
    def topics(request: Request) -> list[Topic]:
        with connect(request.app.state.settings.database_path, readonly=True) as connection:
            return [
                Topic(slug=row[0], label=row[1])
                for row in connection.execute("SELECT slug, label FROM topics ORDER BY slug")
            ]

    @application.get(
        "/users/{user_id}/recommendations",
        response_model=RecommendationResponse,
        tags=["Recommendations"],
        summary="Recommend Circles for a member",
        responses={404: {"description": "Member does not exist"}},
    )
    def recommendations(
        request: Request,
        user_id: Annotated[int, Path(gt=0, le=2**63 - 1)],
        limit: Annotated[
            int, Query(ge=1, le=20, description="May return fewer to preserve diversity")
        ] = 5,
        include_scores: Annotated[
            bool, Query(description="Include score contributions for inspection")
        ] = False,
        topic: Annotated[
            str | None,
            Query(
                min_length=1,
                max_length=80,
                description="Canonical topic slug for this request only; replaces profile interests",
            ),
        ] = None,
        circle_format: Annotated[
            Literal["in_person", "virtual", "hybrid"] | None,
            Query(
                alias="format",
                description="Exact format filter; hybrid is a separate format. No geographic fit is inferred.",
            ),
        ] = None,
    ) -> RecommendationResponse:
        try:
            with connect(request.app.state.settings.database_path, readonly=True) as connection:
                context = load_context(
                    connection, user_id, topic=topic, circle_format=circle_format
                )
            return recommend(context, limit=limit, include_scores=include_scores)
        except UserNotFound:
            raise HTTPException(status_code=404, detail="User not found") from None
        except UnknownTopic:
            raise HTTPException(status_code=422, detail="Unknown topic slug") from None

    return application


app = create_app()
