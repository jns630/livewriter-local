"""Command-line archive operations."""

import argparse
from pathlib import Path

from .archive import export_archive, import_archive
from .config import Config
from .storage import Storage


def export_main() -> None:
    parser = argparse.ArgumentParser(description="Export LiveWriter Local content")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = Config.from_file(args.config)
    export_archive(Storage(config.data_dir), args.output)
    print(f"Exported content to {args.output}")


def import_main() -> None:
    parser = argparse.ArgumentParser(description="Import a LiveWriter Local archive")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    config = Config.from_file(args.config)
    posts, media = import_archive(Storage(config.data_dir), args.input)
    print(f"Imported {posts} posts and {media} media files")