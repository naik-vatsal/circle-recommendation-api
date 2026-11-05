-- Times are normalized UTC ISO-8601 text (YYYY-MM-DDTHH:MM:SS.ffffffZ).
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    domain TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    has_photo INTEGER NOT NULL CHECK (has_photo IN (0, 1)),
    bio TEXT,
    job_title TEXT,
    company TEXT,
    industry TEXT,
    location TEXT,
    joined_at TEXT NOT NULL,
    profile_completeness REAL NOT NULL CHECK (profile_completeness BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS user_interests (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    PRIMARY KEY (user_id, topic_id)
);

CREATE TABLE IF NOT EXISTS circles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    primary_topic_id INTEGER REFERENCES topics(id),
    cover_image_url TEXT,
    format TEXT NOT NULL CHECK (format IN ('in_person', 'virtual', 'hybrid')),
    access TEXT NOT NULL CHECK (access IN ('public', 'unlisted')),
    join_policy TEXT NOT NULL CHECK (join_policy IN ('open', 'request')),
    max_members INTEGER CHECK (max_members IS NULL OR max_members >= 0),
    member_count INTEGER NOT NULL CHECK (member_count >= 0),
    created_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    feed_posts_30d INTEGER NOT NULL CHECK (feed_posts_30d >= 0),
    chat_messages_30d INTEGER NOT NULL CHECK (chat_messages_30d >= 0)
);

-- Tags are free form in the source: preserve unknown tags without inventing taxonomy.
CREATE TABLE IF NOT EXISTS circle_tags (
    circle_id INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (circle_id, tag)
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    circle_id INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('member', 'leader')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (user_id, circle_id)
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    circle_id INTEGER NOT NULL,
    author_user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    reaction_count INTEGER NOT NULL CHECK (reaction_count >= 0),
    comment_count INTEGER NOT NULL CHECK (comment_count >= 0),
    save_count INTEGER NOT NULL CHECK (save_count >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (author_user_id, circle_id)
        REFERENCES memberships(user_id, circle_id)
);

-- Candidate generation by visibility and recency; capacity remains a residual filter.
CREATE INDEX IF NOT EXISTS idx_circles_discovery ON circles(access, last_activity_at);
-- Reverse lookup: the PK already supports a user's memberships and exclusion checks.
CREATE INDEX IF NOT EXISTS idx_memberships_circle_role ON memberships(circle_id, role);
-- Time-window engagement aggregation; also supports per-Circle feed reads.
CREATE INDEX IF NOT EXISTS idx_activity_circle_time ON activity(circle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_time ON activity(created_at);
CREATE INDEX IF NOT EXISTS idx_circles_primary_topic ON circles(primary_topic_id);
