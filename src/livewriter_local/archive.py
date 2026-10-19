"""Portable, path-validated export and import for local content."""

import json
import os
from pathlib import Path
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from .storage import Storage

_POST_ID = re.compile(r"[a-f0-9]{32}\Z")
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}(?:\.[A-Za-z0-9]{1,16})?\Z")
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def export_archive(storage: Storage, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with storage._connect() as connection:
        posts = [dict(row) for row in connection.execute("SELECT * FROM posts ORDER BY post_id")]
        media = [dict(row) for row in connection.execute("SELECT * FROM media ORDER BY media_id")]
    manifest = {"format_version": 1, "posts": posts, "media": media}
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False, suffix=".zip") as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            for post in posts:
                archive.write(storage.posts_dir / post["body_file"], f"posts/{post['body_file']}")
            for item in media:
                archive.write(storage.media_dir / item["stored_filename"], f"media/{item['stored_filename']}")
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def import_archive(storage: Storage, source: Path) -> tuple[int, int]:
    if not is_zipfile(source):
        raise ValueError("archive is not a valid ZIP file")
    with ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > 20002 or sum(info.file_size for info in infos) > _MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds the supported size or item count")
        info_by_name = {info.filename: info for info in infos}
        if len(info_by_name) != len(infos) or "manifest.json" not in info_by_name:
            raise ValueError("archive has duplicate members or no manifest")
        if info_by_name["manifest.json"].file_size > 4 * 1024 * 1024:
            raise ValueError("archive manifest is too large")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
            raise ValueError("unsupported archive format")
        posts = manifest.get("posts")
        media = manifest.get("media")
        if not isinstance(posts, list) or not isinstance(media, list):
            raise ValueError("archive manifest must contain post and media lists")

        expected_names = {"manifest.json"}
        post_entries = []
        for post in posts:
            if not isinstance(post, dict) or not _POST_ID.fullmatch(str(post.get("post_id", ""))):
                raise ValueError("archive contains an invalid post ID")
            post_id = post["post_id"]
            filename = f"{post_id}.html"
            if post.get("body_file") != filename or post.get("status") not in {"draft", "published", "archived"}:
                raise ValueError("archive contains invalid post metadata")
            categories = json.loads(post.get("categories_json", ""))
            tags = json.loads(post.get("tags_json", ""))
            metadata = json.loads(post.get("metadata_json", ""))
            if not isinstance(categories, list) or not isinstance(tags, list) or not isinstance(metadata, dict):
                raise ValueError("archive contains invalid post JSON metadata")
            member = f"posts/{filename}"
            expected_names.add(member)
            post_entries.append((post, member, storage.posts_dir / filename))

        media_entries = []
        for item in media:
            if not isinstance(item, dict) or not _POST_ID.fullmatch(str(item.get("media_id", ""))):
                raise ValueError("archive contains an invalid media ID")
            filename = item.get("stored_filename", "")
            if (not _MEDIA_NAME.fullmatch(filename) or not filename.startswith(item["media_id"])
                    or not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0):
                raise ValueError("archive contains an invalid media filename")
            member = f"media/{filename}"
            expected_names.add(member)
            media_entries.append((item, member, storage.media_dir / filename))
        if set(info_by_name) != expected_names:
            raise ValueError("archive contains unexpected or missing files")

        post_payloads = [(row, target, archive.read(member)) for row, member, target in post_entries]
        media_payloads = [(row, target, archive.read(member)) for row, member, target in media_entries]
        if any(len(content) != row["size_bytes"] for row, _, content in media_payloads):
            raise ValueError("archive media size does not match its metadata")

    paths = [target for _, target, _ in post_payloads + media_payloads]
    if len(set(paths)) != len(paths) or any(path.exists() for path in paths):
        raise ValueError("import would overwrite existing content files")
    with storage._connect() as connection:
        existing_posts = {row[0] for row in connection.execute("SELECT post_id FROM posts")}
        existing_media = {row[0] for row in connection.execute("SELECT media_id FROM media")}
        if existing_posts.intersection(row["post_id"] for row, _, _ in post_payloads):
            raise ValueError("one or more post IDs already exist")
        if existing_media.intersection(row["media_id"] for row, _, _ in media_payloads):
            raise ValueError("one or more media IDs already exist")

    written = []
    try:
        for _, target, content in post_payloads + media_payloads:
            storage._write_atomic(target.parent, target.name, content)
            written.append(target)
        with storage._connect() as connection:
            connection.execute("BEGIN")
            for post, _, _ in post_payloads:
                connection.execute(
                    "INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(post[key] for key in (
                        "post_id", "title", "body_file", "status", "categories_json", "tags_json",
                        "created_at", "updated_at", "published_at", "metadata_json",
                    )),
                )
            for item, _, _ in media_payloads:
                connection.execute(
                    "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?)",
                    tuple(item[key] for key in (
                        "media_id", "original_filename", "stored_filename", "content_type",
                        "size_bytes", "created_at",
                    )),
                )
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return len(post_payloads), len(media_payloads)