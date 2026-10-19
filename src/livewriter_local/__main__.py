"""Command-line entry point."""

import argparse
import getpass
import json
import logging
from pathlib import Path

import uvicorn

from .auth import hash_password
from .app import create_app
from .config import Config, example_config


def initialize(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing config: {path}")
    username = input("Local username [writer]: ").strip() or "writer"
    password = getpass.getpass("Local password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords must be non-empty and match")
    values = example_config()
    values["username"] = username
    values["password_hash"] = hash_password(password)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    print(f"Created {path}. Keep this file private; it contains your password hash.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Windows Live Writer publishing server")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--init-config", action="store_true", help="create config interactively")
    parser.add_argument("--cloud", action="store_true", help="load secure cloud settings from environment")
    args = parser.parse_args()
    if args.init_config:
        initialize(args.config)
        return
    try:
        config = Config.from_environment() if args.cloud else Config.from_file(args.config)
    except FileNotFoundError as error:
        raise SystemExit(f"Config not found: {args.config}. Run with --init-config first.") from error
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Invalid config {args.config}: {error}") from error
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()