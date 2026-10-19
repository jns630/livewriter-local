"""HTTP application and local publishing interface."""

from contextlib import asynccontextmanager
import html
import logging
from pathlib import Path
import base64
import secrets
import time
from xmlrpc.client import Fault, dumps, loads

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .dashboard import render_dashboard
from .storage import Storage
from .auth import verify_password
from .blogger import create_mirror
from .xmlrpc_endpoint import ApiFault, XmlRpcApi


def create_app(config: Config | None = None) -> FastAPI:
    config = (config or Config()).validated()
    if config.allow_remote:
        logging.getLogger("livewriter_local").warning(
            "Remote binding is enabled; the server may be reachable by other devices"
        )
    storage = Storage(config.data_dir)
    blogger = create_mirror(config)
    api = XmlRpcApi(config, storage, blogger)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title=config.blog_name, lifespan=lifespan)
    app.state.config = config
    app.state.storage = storage
    app.state.metrics = {"requests": 0, "errors": 0}
    app.state.recent_errors = []
    app.state.blogger_enabled = config.blogger_enabled
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        path = request.url.path
        protected_page = path in {"/", "/media-library", "/diagnostics"} or path.startswith("/posts/")
        if config.protect_dashboard and protected_page:
            credentials = request.headers.get("authorization", "").removeprefix("Basic ")
            try:
                decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (ValueError, UnicodeDecodeError):
                username, password = "", ""
            if username != config.username or not verify_password(password, config.password_hash):
                return Response("Authentication required", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="LiveWriter Local", charset="UTF-8"'})
        started = time.monotonic()
        app.state.metrics["requests"] += 1
        response = await call_next(request)
        if response.status_code >= 400:
            app.state.metrics["errors"] += 1
            app.state.recent_errors.append(f"HTTP {response.status_code} {request.method} {request.url.path}")
            del app.state.recent_errors[:-50]
        if config.diagnostic_logging:
            logging.getLogger("livewriter_local").info(
                "%s %s rpc_method=%s status=%s error=%s duration_ms=%.1f", request.method,
                request.url.path, getattr(request.state, "rpc_method", "-"), response.status_code,
                getattr(request.state, "rpc_error", "-"), (time.monotonic() - started) * 1000,
            )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home():
        posts = storage.recent_posts(100, config.blog_url)
        return HTMLResponse(render_dashboard(config, posts, len(storage.list_media())))

    @app.get(config.rsd_path)
    async def rsd():
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rsd version="1.0" xmlns="http://archipelago.phrasewise.com/rsd"><service><engineName>LiveWriter Local</engineName><engineLink>http://localhost/</engineLink><homePageLink>{html.escape(config.blog_url)}</homePageLink><apis><api name="MetaWeblog" preferred="true" apiLink="{html.escape(config.blog_url.rstrip('/') + config.xmlrpc_path)}" blogID="{html.escape(config.blog_id)}"/></apis></service></rsd>'''
        return Response(xml, media_type="application/rsd+xml; charset=utf-8")

    @app.post(config.xmlrpc_path)
    async def xmlrpc(request: Request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"text/xml", "application/xml"}:
            return _fault_response(400, "Expected an XML request")
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > config.max_request_bytes:
                    return _fault_response(413, "XML-RPC request exceeds configured limit")
            except ValueError:
                return _fault_response(400, "Invalid Content-Length")
        body = await request.body()
        if len(body) > config.max_request_bytes:
            return _fault_response(413, "XML-RPC request exceeds configured limit")
        try:
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                return _fault_response(400, "XML declarations with a document type are not supported")
            params, method = loads(body, use_builtin_types=True)
            request.state.rpc_method = method
            result = api.call(method, params)
            payload = dumps((result,), methodresponse=True, allow_none=True, encoding="utf-8")
            return Response(payload, media_type="text/xml; charset=utf-8")
        except ApiFault as error:
            request.state.rpc_error = f"fault:{error.code}"
            app.state.metrics["errors"] += 1
            app.state.recent_errors.append(f"XML-RPC {getattr(request.state, 'rpc_method', 'unknown')} fault {error.code}")
            del app.state.recent_errors[:-50]
            return _fault_response(error.code, str(error))
        except Exception:
            request.state.rpc_error = "malformed-or-unsupported-request"
            app.state.metrics["errors"] += 1
            app.state.recent_errors.append("Malformed or unsupported XML-RPC request")
            del app.state.recent_errors[:-50]
            logging.getLogger("livewriter_local").warning("Malformed XML-RPC request")
            return _fault_response(400, "Malformed XML-RPC request")

    @app.get("/media/{filename}")
    async def media(filename: str):
        path = storage.get_media_path(filename)
        if path is None:
            return Response("Not found", status_code=404)
        return FileResponse(path, media_type=storage.get_media_type(filename),
                    headers={"Content-Disposition": "inline"})

    @app.get("/posts/{post_id}", response_class=HTMLResponse)
    async def post_preview(post_id: str):
        post = storage.get_post(post_id, config.blog_url)
        if post is None:
            return HTMLResponse("Not found", status_code=404)
        return HTMLResponse(f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{html.escape(post['title'])}</title></head>"
                            f"<body><main><h1>{html.escape(post['title'])}</h1>{post['description']}</main></body></html>")

    @app.get("/media-library", response_class=HTMLResponse)
    async def media_library():
        entries = "".join(
            f'<li><a href="/media/{html.escape(item["stored_filename"])}">{html.escape(item["original_filename"])}</a> ({item["size_bytes"]} bytes)</li>'
            for item in storage.list_media()
        )
        return HTMLResponse(f"<!doctype html><html><meta charset=\"utf-8\"><title>Media</title><h1>Media</h1><ul>{entries or '<li>No media uploaded</li>'}</ul><a href='/'>Posts</a></html>")

    @app.get("/diagnostics", response_class=HTMLResponse)
    async def diagnostics():
        errors = "".join(f"<li>{html.escape(item)}</li>" for item in reversed(app.state.recent_errors))
        return HTMLResponse(
            "<!doctype html><html><meta charset=\"utf-8\"><title>Diagnostics</title>"
            f"<h1>Diagnostics</h1><p>Requests: {app.state.metrics['requests']}</p>"
            f"<p>Errors: {app.state.metrics['errors']}</p><h2>Recent errors</h2>"
            f"<ul>{errors or '<li>No errors recorded</li>'}</ul><a href='/'>Posts</a></html>"
        )

    return app


def _fault_response(code: int, message: str) -> Response:
    payload = dumps(Fault(code, message), allow_none=True, encoding="utf-8")
    return Response(payload, status_code=200, media_type="text/xml; charset=utf-8")