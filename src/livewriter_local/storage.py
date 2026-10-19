"""SQLite metadata and atomic local file storage."""

from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.posts_dir = data_dir / "posts"
        self.media_dir = data_dir / "media"
        self.trash_dir = data_dir / "trash"
        self.database = data_dir / "database" / "livewriter.sqlite3"
        for directory in (self.posts_dir, self.media_dir, self.trash_dir, self.database.parent):
            directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body_file TEXT NOT NULL,
                    status TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    published_at TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media (
                    media_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _write_atomic(self, directory: Path, filename: str, content: bytes) -> Path:
        destination = directory / filename
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
        return destination

    @staticmethod
    def _categories(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
            raise ValueError("categories must be a list of strings")
        return list(dict.fromkeys(item for item in value if item))

    @staticmethod
    def _tags(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [tag.strip() for tag in value.split(",") if tag.strip()]
        if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
            raise ValueError("mt_keywords must be a string or list of strings")
        return list(value)

    def create_post(self, fields: dict, publish: bool, permalink: str) -> dict:
        title = fields.get("title", "")
        body = fields.get("description", "")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("title and description must be strings")
        post_id = uuid.uuid4().hex
        now = utc_now()
        created_at = self._created_at(fields.get("dateCreated"), now)
        categories = self._categories(fields.get("categories"))
        tags = self._tags(fields.get("mt_keywords"))
        known = {"title", "description", "categories", "mt_keywords", "dateCreated", "wp_slug"}
        metadata = {key: value for key, value in fields.items() if key not in known}
        self._write_atomic(self.posts_dir, f"{post_id}.html", body.encode("utf-8"))
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (post_id, title, f"{post_id}.html", "published" if publish else "draft",
                     json.dumps(categories), json.dumps(tags), created_at, now,
                     now if publish else None, json.dumps(metadata)),
                )
        except Exception:
            (self.posts_dir / f"{post_id}.html").unlink(missing_ok=True)
            raise
        return self.get_post(post_id, permalink)

    @staticmethod
    def _created_at(value: object, fallback: str) -> str:
        if value is None:
            return fallback
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("dateCreated must be a valid date/time") from error
        else:
            raise ValueError("dateCreated must be a date/time value")
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat(timespec="seconds")

    def _decode_post(self, row: sqlite3.Row, permalink: str) -> dict:
        body = (self.posts_dir / row["body_file"]).read_text(encoding="utf-8")
        return {
            "postid": row["post_id"], "title": row["title"], "description": body,
            "categories": json.loads(row["categories_json"]),
            "mt_keywords": ",".join(json.loads(row["tags_json"])),
            "dateCreated": row["created_at"], "link": f"{permalink.rstrip('/')}/posts/{row['post_id']}",
            "permaLink": f"{permalink.rstrip('/')}/posts/{row['post_id']}",
            "post_status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "published_at": row["published_at"],
            **json.loads(row["metadata_json"]),
        }

    def get_post(self, post_id: str, permalink: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM posts WHERE post_id = ?", (str(post_id),)).fetchone()
        return self._decode_post(row, permalink) if row else None

    def update_post_metadata(self, post_id: str, updates: dict) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT metadata_json FROM posts WHERE post_id=?", (str(post_id),)).fetchone()
            if row is None:
                raise ValueError("post not found while updating external metadata")
            metadata = json.loads(row["metadata_json"])
            metadata.update(updates)
            connection.execute("UPDATE posts SET metadata_json=?, updated_at=? WHERE post_id=?",
                               (json.dumps(metadata), utc_now(), str(post_id)))

    def edit_post(self, post_id: str, fields: dict, publish: bool, permalink: str) -> dict | None:
        existing = self.get_post(post_id, permalink)
        if existing is None:
            return None
        title = fields.get("title", existing["title"])
        body = fields.get("description", existing["description"])
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("title and description must be strings")
        categories = self._categories(fields.get("categories", existing["categories"]))
        tags = self._tags(fields.get("mt_keywords", existing["mt_keywords"]))
        merged = {key: value for key, value in existing.items() if key not in {
            "postid", "title", "description", "categories", "mt_keywords", "dateCreated",
            "link", "permaLink", "post_status", "created_at", "updated_at", "published_at",
        }}
        known = {"title", "description", "categories", "mt_keywords", "dateCreated", "wp_slug"}
        merged.update({key: value for key, value in fields.items() if key not in known})
        now = utc_now()
        old_content = (self.posts_dir / f"{post_id}.html").read_bytes()
        temporary_content = body.encode("utf-8")
        temporary_path = self._write_atomic(self.posts_dir, f".{post_id}.tmp", temporary_content)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN")
                os.replace(temporary_path, self.posts_dir / f"{post_id}.html")
                connection.execute(
                    "UPDATE posts SET title=?, status=?, categories_json=?, tags_json=?, updated_at=?, "
                    "published_at=?, metadata_json=? WHERE post_id=?",
                    (title, "published" if publish else "draft", json.dumps(categories), json.dumps(tags),
                     now, existing["published_at"] or (now if publish else None), json.dumps(merged), str(post_id)),
                )
        except Exception:
            temporary_path.unlink(missing_ok=True)
            self._write_atomic(self.posts_dir, f"{post_id}.html", old_content)
            raise
        return self.get_post(post_id, permalink)

    def recent_posts(self, count: int, permalink: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM posts ORDER BY updated_at DESC LIMIT ?", (max(0, min(count, 1000)),)
            ).fetchall()
        return [self._decode_post(row, permalink) for row in rows]

    def categories(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT categories_json FROM posts").fetchall()
        values = {category for row in rows for category in json.loads(row[0])}
        return sorted(values) or ["Uncategorized"]

    def delete_post(self, post_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT body_file FROM posts WHERE post_id=?", (str(post_id),)).fetchone()
            if row is None:
                return False
            source = self.posts_dir / row["body_file"]
            archived = self.trash_dir / f"{post_id}-{row['body_file']}"
            if source.exists():
                os.replace(source, archived)
            try:
                connection.execute("DELETE FROM posts WHERE post_id=?", (str(post_id),))
            except Exception:
                if archived.exists():
                    os.replace(archived, source)
                raise
        return True

    def save_media(self, name: str, content_type: str, content: bytes) -> dict:
        safe_name = Path(name.replace("\\", "/")).name
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name).strip("._") or "upload"
        media_id = uuid.uuid4().hex
        suffix = Path(safe_name).suffix[:16]
        stored_name = f"{media_id}{suffix}"
        self._write_atomic(self.media_dir, stored_name, content)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?)",
                    (media_id, safe_name, stored_name,
                     content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
                     len(content), utc_now()),
                )
        except Exception:
            (self.media_dir / stored_name).unlink(missing_ok=True)
            raise
        return {"media_id": media_id, "name": stored_name, "content_type": content_type,
                "size_bytes": len(content), "created_at": utc_now()}

    def get_media_path(self, stored_name: str) -> Path | None:
        if not re.fullmatch(r"[a-f0-9]{32}(?:\.[A-Za-z0-9]{1,16})?", stored_name):
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT stored_filename FROM media WHERE stored_filename=?", (stored_name,)).fetchone()
        path = self.media_dir / row[0] if row else None
        return path if path and path.is_file() else None

    def get_media_type(self, stored_name: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT content_type FROM media WHERE stored_filename=?", (stored_name,)).fetchone()
        return row[0] if row else None

    def list_media(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM media ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]