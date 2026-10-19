"""Obtain a Blogger OAuth refresh token for the configured Google account."""

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize LiveWriter Local to publish to Blogger")
    parser.add_argument("client_secret_file", type=Path,
                        help="OAuth Desktop app client-secret JSON downloaded from Google Cloud")
    args = parser.parse_args()
    flow = InstalledAppFlow.from_client_secrets_file(
        args.client_secret_file,
        scopes=["https://www.googleapis.com/auth/blogger"],
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print("Keep this refresh token private. Set it as BLOGGER_REFRESH_TOKEN in Render.")
    print(json.dumps({"client_id": credentials.client_id,
                      "client_secret": credentials.client_secret,
                      "refresh_token": credentials.refresh_token}, indent=2))
    response = httpx.get(
        "https://www.googleapis.com/blogger/v3/users/self/blogs",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=20.0,
    )
    response.raise_for_status()
    print("Available Blogger blogs (use the matching ID as BLOGGER_BLOG_ID):")
    for blog in response.json().get("items", []):
        print(f"{blog.get('name', '(untitled)')}: {blog['id']}")


if __name__ == "__main__":
    main()