"""Import the synthetic fixture in a single transaction; never reset existing data."""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.database import connect, parse_time, utc_text

SNAPSHOT_AT = "2026-09-21T00:00:00Z"  # ANCHOR in the supplied generate.mjs
SCHEMA_VERSION = "1"


def seed_database(database_path: Path, data_dir: Path, snapshot_at: str = SNAPSHOT_AT) -> bool:
    """Return True after first import, False if this schema already has a snapshot.

    BEGIN IMMEDIATE serializes competing startup importers. Any bad row rolls back
    the whole fixture. The source member_count is the authoritative capacity input.
    """
    snapshot_at = utc_text(snapshot_at)
    with connect(database_path) as connection:
        connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = dict(connection.execute("SELECT key, value FROM metadata"))
            if "schema_version" in existing:
                if existing["schema_version"] != SCHEMA_VERSION:
                    raise ValueError("Unsupported database schema. Use a new database path.")
                if "snapshot_at" not in existing:
                    raise ValueError("Database snapshot metadata is missing.")
                parse_time(existing["snapshot_at"])
                return False

            def load(name: str) -> list[dict]:
                rows = json.loads((data_dir / f"{name}.json").read_text(encoding="utf-8"))
                for row in rows:
                    for field in ("created_at", "joined_at", "last_activity_at"):
                        if field in row:
                            row[field] = utc_text(row[field])
                            if parse_time(row[field]) > parse_time(snapshot_at):
                                raise ValueError(f"{name}.{field} is after the snapshot time")
                return rows

            topics = load("topics")
            users = load("users")
            circles = load("circles")
            memberships = load("memberships")
            activity = load("activity")
            topic_ids = {topic["slug"]: topic["id"] for topic in topics}
            connection.executemany(
                "INSERT INTO topics (id, slug, label, domain) VALUES (:id, :slug, :label, :domain)",
                topics,
            )
            connection.executemany(
                """INSERT INTO users VALUES (
                    :id, :first_name, :last_name, :has_photo, :bio, :job_title,
                    :company, :industry, :location, :joined_at, :profile_completeness
                )""",
                users,
            )
            connection.executemany(
                "INSERT INTO user_interests VALUES (?, ?)",
                [
                    (u["id"], topic_ids[slug])
                    for u in users
                    for slug in sorted(set(u["topic_interests"]))
                ],
            )
            connection.executemany(
                """INSERT INTO circles VALUES (
                    :id, :name, :slug, :description, :primary_topic_id, :cover_image_url,
                    :format, :access, :join_policy, :max_members, :member_count,
                    :created_at, :last_activity_at, :feed_posts_30d, :chat_messages_30d
                )""",
                [
                    {**c, "primary_topic_id": topic_ids[c["topic"]] if c["topic"] else None}
                    for c in circles
                ],
            )
            connection.executemany(
                "INSERT INTO circle_tags VALUES (?, ?)",
                [(c["id"], tag) for c in circles for tag in sorted(set(c["tags"]))],
            )
            connection.executemany(
                "INSERT INTO memberships VALUES (:user_id, :circle_id, :role, :joined_at)",
                memberships,
            )
            connection.executemany(
                """INSERT INTO activity VALUES (
                    :id, :circle_id, :author_user_id, :body,
                    :reaction_count, :comment_count, :save_count, :created_at
                )""",
                activity,
            )
            connection.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                [("schema_version", SCHEMA_VERSION), ("snapshot_at", snapshot_at)],
            )
    return True


def main() -> None:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=settings.database_path)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--snapshot-at", default=SNAPSHOT_AT)
    args = parser.parse_args()
    created = seed_database(args.database, args.data_dir, args.snapshot_at)
    print(
        f"{'Imported snapshot into' if created else 'Snapshot already exists in'} {args.database}"
    )


if __name__ == "__main__":
    main()
