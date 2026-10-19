"""Validated application configuration."""

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    allow_remote: bool = False
    port: int = 8080
    data_dir: Path = Path("data")
    blog_id: str = "livewriter-local"
    blog_name: str = "LiveWriter Local"
    blog_url: str = "http://127.0.0.1:8080/"
    xmlrpc_path: str = "/xmlrpc"
    rsd_path: str = "/rsd"
    username: str = "writer"
    password_hash: str = ""
    max_request_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 20 * 1024 * 1024
    diagnostic_logging: bool = False
    protect_dashboard: bool = False
    blogger_enabled: bool = False
    blogger_blog_id: str = ""
    blogger_client_id: str = ""
    blogger_client_secret: str = ""
    blogger_refresh_token: str = ""

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        values = json.loads(path.read_text(encoding="utf-8"))
        if "data_dir" in values:
            values["data_dir"] = Path(values["data_dir"])
        return cls(**values).validated()

    @classmethod
    def from_environment(cls) -> "Config":
        required = ("LW_USERNAME", "LW_PASSWORD_HASH")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError("missing environment variables: " + ", ".join(missing))
        blog_url = os.getenv("LW_BLOG_URL") or os.getenv("RENDER_EXTERNAL_URL")
        if not blog_url:
            raise ValueError("set LW_BLOG_URL to the public HTTPS service URL")
        config = cls(
            host=os.getenv("HOST", "0.0.0.0"),
            allow_remote=True,
            port=int(os.getenv("PORT", "10000")),
            data_dir=Path(os.getenv("LW_DATA_DIR", "/var/data")),
            blog_id=os.getenv("LW_BLOG_ID", "livewriter-local"),
            blog_name=os.getenv("LW_BLOG_NAME", "LiveWriter Local"),
            blog_url=blog_url.rstrip("/") + "/",
            xmlrpc_path=os.getenv("LW_XMLRPC_PATH", "/xmlrpc"),
            rsd_path=os.getenv("LW_RSD_PATH", "/rsd"),
            username=os.environ["LW_USERNAME"],
            password_hash=os.environ["LW_PASSWORD_HASH"],
            max_request_bytes=int(os.getenv("LW_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))),
            max_upload_bytes=int(os.getenv("LW_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))),
            diagnostic_logging=os.getenv("LW_DIAGNOSTIC_LOGGING", "false").lower() == "true",
            protect_dashboard=True,
            blogger_enabled=os.getenv("BLOGGER_ENABLED", "false").lower() == "true",
            blogger_blog_id=os.getenv("BLOGGER_BLOG_ID", ""),
            blogger_client_id=os.getenv("BLOGGER_CLIENT_ID", ""),
            blogger_client_secret=os.getenv("BLOGGER_CLIENT_SECRET", ""),
            blogger_refresh_token=os.getenv("BLOGGER_REFRESH_TOKEN", ""),
        )
        return config.validated()

    def validated(self) -> "Config":
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.username or not self.password_hash.startswith("scrypt$"):
            raise ValueError("configure a username and scrypt password_hash before starting")
        if self.blogger_enabled and not all((self.blogger_blog_id, self.blogger_client_id,
                                             self.blogger_client_secret, self.blogger_refresh_token)):
            raise ValueError("Blogger mirroring requires blog ID, OAuth client ID/secret, and refresh token")
        try:
            loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            loopback = self.host.lower() == "localhost"
        if not loopback and not self.allow_remote:
            raise ValueError("non-loopback binding requires allow_remote=true")
        for name, value in (("xmlrpc_path", self.xmlrpc_path), ("rsd_path", self.rsd_path)):
            if not value.startswith("/") or value.startswith("//"):
                raise ValueError(f"{name} must be an absolute URL path")
        parsed = urlparse(self.blog_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("blog_url must be an absolute HTTP or HTTPS URL")
        if min(self.max_request_bytes, self.max_upload_bytes) <= 0:
            raise ValueError("request and upload limits must be positive")
        return self


def example_config() -> dict[str, object]:
    return {
        "host": "127.0.0.1",
        "allow_remote": False,
        "port": 8080,
        "data_dir": "data",
        "blog_id": "livewriter-local",
        "blog_name": "LiveWriter Local",
        "blog_url": "http://127.0.0.1:8080/",
        "xmlrpc_path": "/xmlrpc",
        "rsd_path": "/rsd",
        "username": "writer",
        "password_hash": "REPLACE_WITH_GENERATED_SCRYPT_HASH",
        "max_request_bytes": 2097152,
        "max_upload_bytes": 20971520,
        "diagnostic_logging": False,
    }