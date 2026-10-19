from pathlib import Path
from datetime import datetime
import json
from xmlrpc.client import Fault, dumps, loads
from zipfile import ZipFile

from fastapi.testclient import TestClient

from livewriter_local.archive import export_archive, import_archive
from livewriter_local.app import create_app
from livewriter_local.auth import hash_password
from livewriter_local.config import Config
from livewriter_local.storage import Storage
from livewriter_local.blogger import BloggerMirror
import httpx


def make_client(tmp_path: Path):
    config = Config(data_dir=tmp_path, password_hash=hash_password("test-pass"))
    return TestClient(create_app(config)), config


def test_dashboard_serves_responsive_assets_and_local_endpoint(tmp_path):
    client, _ = make_client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "A home for" in page.text
    assert "http://127.0.0.1:8080/xmlrpc" in page.text
    assert client.get("/static/dashboard.css").status_code == 200
    assert client.get("/static/dashboard.js").status_code == 200


def test_cloud_config_reads_render_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LW_USERNAME", "cloud-writer")
    monkeypatch.setenv("LW_PASSWORD_HASH", hash_password("cloud-secret"))
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://writer.onrender.com")
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("LW_DATA_DIR", str(tmp_path))
    config = Config.from_environment()
    assert config.host == "0.0.0.0"
    assert config.port == 10000
    assert config.blog_url == "https://writer.onrender.com/"
    assert config.protect_dashboard is True


def test_cloud_dashboard_auth_does_not_block_xmlrpc(tmp_path):
    config = Config(data_dir=tmp_path, password_hash=hash_password("secret"), protect_dashboard=True)
    client = TestClient(create_app(config))
    assert client.get("/").status_code == 401
    assert client.get("/", auth=(config.username, "secret")).status_code == 200
    assert client.get("/rsd").status_code == 200


def test_blogger_mirror_refreshes_token_and_updates_existing_post():
    requests_seen = []

    def respond(request):
        requests_seen.append((request.method, str(request.url), request.read().decode("utf-8")))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "blog-post-42"})
        return httpx.Response(200, json={"id": "blog-post-42"})

    transport = httpx.MockTransport(respond)
    http_client = httpx.Client(transport=transport)
    config = Config(data_dir=Path("."), password_hash=hash_password("secret"), blogger_enabled=True,
                    blogger_blog_id="blog-123", blogger_client_id="client", blogger_client_secret="secret",
                    blogger_refresh_token="refresh")
    mirror = BloggerMirror(config, http_client)
    post = {"title": "Hello", "description": "<p>World</p>", "categories": ["Notes"], "mt_keywords": "one,two"}
    assert mirror.publish(post) == "blog-post-42"
    post["blogger_is_draft"] = False
    assert mirror.publish(post, "blog-post-42", is_draft=True) == "blog-post-42"
    post["blogger_is_draft"] = True
    assert mirror.publish(post, "blog-post-42", is_draft=False) == "blog-post-42"
    assert [item[0] for item in requests_seen] == ["POST", "POST", "POST", "PUT", "PUT", "POST"]
    assert requests_seen[2][1].endswith("/blog-post-42/revert")
    assert requests_seen[-1][1].endswith("/blog-post-42/publish")


def rpc(client, method, *params):
    body = dumps(params, methodname=method, allow_none=True, encoding="utf-8")
    response = client.post("/xmlrpc", content=body, headers={"content-type": "text/xml"})
    assert response.status_code == 200
    params, method_name = loads(response.content, use_builtin_types=True)
    return params[0], method_name


def test_discovery_and_post_round_trip(tmp_path):
    client, config = make_client(tmp_path)
    discovery = client.get("/rsd")
    assert discovery.status_code == 200
    assert config.xmlrpc_path in discovery.text

    blogs, _ = rpc(client, "blogger.getUsersBlogs", "", config.username, "test-pass")
    assert blogs[0]["blogid"] == config.blog_id

    post_id, _ = rpc(client, "metaWeblog.newPost", config.blog_id, config.username, "test-pass",
                     {"title": "A local post", "description": "<p>kept intact</p>",
                      "categories": ["Notes"], "dateCreated": datetime(2020, 1, 2, 3, 4, 5)}, False)
    post, _ = rpc(client, "metaWeblog.getPost", post_id, config.username, "test-pass")
    assert post["title"] == "A local post"
    assert post["description"] == "<p>kept intact</p>"
    assert post["categories"] == ["Notes"]
    assert post["dateCreated"] == datetime(2020, 1, 2, 3, 4, 5)
    assert post["post_status"] == "draft"

    rpc(client, "metaWeblog.editPost", post_id, config.username, "test-pass", {"title": "Updated"}, True)
    updated, _ = rpc(client, "metaWeblog.getPost", post_id, config.username, "test-pass")
    assert updated["postid"] == post_id
    assert updated["title"] == "Updated"
    assert updated["description"] == "<p>kept intact</p>"
    assert updated["post_status"] == "published"


def test_upload_is_retrievable_and_filename_is_not_a_path(tmp_path):
    client, config = make_client(tmp_path)
    result, _ = rpc(client, "metaWeblog.newMediaObject", config.blog_id, config.username, "test-pass",
                    {"name": "../photo.png", "type": "image/png", "bits": b"image-data"})
    uploaded = client.get(result["url"])
    assert uploaded.content == b"image-data"
    assert uploaded.headers["content-disposition"] == "inline"
    assert "/../" not in result["url"]
    assert client.get("/media/../../outside.png").status_code == 404


def test_bad_credentials_return_xmlrpc_fault(tmp_path):
    client, config = make_client(tmp_path)
    try:
        rpc(client, "blogger.getUsersBlogs", "", config.username, "wrong")
    except Fault as error:
        assert error.faultCode == 403
        assert error.faultString == "Authentication failed"
    else:
        raise AssertionError("invalid credentials must return an XML-RPC fault")


def test_post_survives_restart_and_delete_is_recoverable(tmp_path):
    client, config = make_client(tmp_path)
    post_id, _ = rpc(client, "metaWeblog.newPost", config.blog_id, config.username, "test-pass",
                     {"title": "Persistent", "description": "saved"}, True)

    restarted, _ = make_client(tmp_path)
    post, _ = rpc(restarted, "metaWeblog.getPost", post_id, config.username, "test-pass")
    assert post["description"] == "saved"

    result, _ = rpc(restarted, "blogger.deletePost", "", post_id, config.username, "test-pass", True)
    assert result is True
    assert not list((tmp_path / "posts").glob(f"{post_id}.html"))
    assert list((tmp_path / "trash").glob(f"*-{post_id}.html"))


def test_user_info_categories_recent_posts_and_unknown_method_fault(tmp_path):
    client, config = make_client(tmp_path)
    rpc(client, "metaWeblog.newPost", config.blog_id, config.username, "test-pass",
        {"title": "Tagged", "description": "body", "categories": ["Research"]}, True)
    user, _ = rpc(client, "blogger.getUserInfo", "", config.username, "test-pass")
    categories, _ = rpc(client, "metaWeblog.getCategories", config.blog_id, config.username, "test-pass")
    recent, _ = rpc(client, "metaWeblog.getRecentPosts", config.blog_id, config.username, "test-pass", 5)
    assert user["userid"] == config.username
    assert categories[0]["categoryName"] == "Research"
    assert len(recent) == 1 and recent[0]["title"] == "Tagged"
    try:
        rpc(client, "metaWeblog.notImplemented")
    except Fault as error:
        assert error.faultCode == 404
    else:
        raise AssertionError("unknown methods must return an XML-RPC fault")


def test_oversized_xmlrpc_request_returns_fault(tmp_path):
    config = Config(
        data_dir=tmp_path,
        password_hash=hash_password("test-pass"),
        max_request_bytes=16,
    )
    client = TestClient(create_app(config))
    body = dumps(("", config.username, "test-pass"), methodname="blogger.getUsersBlogs").encode()
    response = client.post("/xmlrpc", content=body, headers={"content-type": "text/xml"})
    assert response.status_code == 200
    try:
        loads(response.content, use_builtin_types=True)
    except Fault as error:
        assert error.faultCode == 413
    else:
        raise AssertionError("oversized requests must return an XML-RPC fault")


def test_diagnostics_counts_xmlrpc_faults_without_exposing_secrets(tmp_path):
    client, config = make_client(tmp_path)
    try:
        rpc(client, "blogger.getUsersBlogs", "", config.username, "wrong-secret")
    except Fault:
        pass
    diagnostics = client.get("/diagnostics").text
    assert "Requests: 2" in diagnostics
    assert "Errors: 1" in diagnostics
    assert "wrong-secret" not in diagnostics


def test_archive_round_trip_preserves_posts_and_media(tmp_path):
    client, config = make_client(tmp_path / "source")
    post_id, _ = rpc(client, "metaWeblog.newPost", config.blog_id, config.username, "test-pass",
                     {"title": "Archive me", "description": "<p>portable</p>", "categories": ["Notes"]}, True)
    rpc(client, "metaWeblog.newMediaObject", config.blog_id, config.username, "test-pass",
        {"name": "cover.png", "type": "image/png", "bits": b"cover-bytes"})
    archive_path = tmp_path / "backup.zip"
    export_archive(client.app.state.storage, archive_path)

    imported_storage = Storage(tmp_path / "clean")
    assert import_archive(imported_storage, archive_path) == (1, 1)
    imported = imported_storage.get_post(post_id, config.blog_url)
    assert imported["description"] == "<p>portable</p>"
    media = imported_storage.list_media()[0]
    assert (imported_storage.media_dir / media["stored_filename"]).read_bytes() == b"cover-bytes"


def test_archive_rejects_path_traversal_metadata(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    manifest = {"format_version": 1, "posts": [{"post_id": "../outside"}], "media": []}
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    try:
        import_archive(Storage(tmp_path / "clean"), archive_path)
    except ValueError as error:
        assert "invalid post ID" in str(error)
    else:
        raise AssertionError("archive path traversal metadata must be rejected")