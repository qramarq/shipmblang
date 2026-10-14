"""Authenticated WSGI adapter for mobile clients using the bundled compiler.

The built-in server is for development. Deploy the WSGI factory behind an
HTTPS reverse proxy and a production WSGI server for access outside a LAN.
"""
from __future__ import annotations

import argparse
import hashlib
import threading
from socketserver import ThreadingMixIn
from pathlib import Path
import hmac
import json
import os
import subprocess
from wsgiref.simple_server import make_server, WSGIServer

from .notebook import execute_program
from .notebook_runtime import compiler_snapshot

MAX_BODY = 65536


def create_app(token=None, *, allowed_origin=None, runner=execute_program, media_root=None):
    token = token or os.environ.get("SHIPMB_MOBILE_TOKEN", "")
    if len(token) < 32:
        raise ValueError("Set SHIPMB_MOBILE_TOKEN to a random token of at least 32 characters.")
    snapshot = compiler_snapshot()
    from .media_jobs import MediaJobs
    from .notebook_store import default_database
    owner = hashlib.sha256(token.encode()).hexdigest()[:32]
    jobs = None
    job_lock = threading.Lock()
    def get_jobs():
        nonlocal jobs
        with job_lock:
            if jobs is None:
                jobs = MediaJobs(Path(media_root or os.environ.get("SHIPMB_MEDIA_ROOT", default_database().parent / "mobile-media")) / owner)
        return jobs
    allowed_origin = allowed_origin or os.environ.get("SHIPMB_MOBILE_ORIGIN")

    def app(environ, start_response):
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
        origin = environ.get("HTTP_ORIGIN")
        if origin and origin == allowed_origin:
            headers.extend([("Access-Control-Allow-Origin", origin), ("Vary", "Origin"),
                            ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS")])

        def reply(status, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            start_response(status, [*headers, ("Content-Length", str(len(body)))])
            return [body]

        if origin and origin != allowed_origin:
            return reply("403 Forbidden", {"error": "This browser origin is not allowed."})
        if environ["REQUEST_METHOD"] == "OPTIONS":
            return reply("200 OK", {})
        authorization = environ.get("HTTP_AUTHORIZATION", "")
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            return reply("401 Unauthorized", {"error": "Check the compiler access token."})
        path = environ.get("PATH_INFO", "")
        method = environ["REQUEST_METHOD"]
        if path.startswith("/v1/media/"):
            from .media_api import route
            return route(get_jobs(), snapshot, environ, reply, start_response, headers)
        if path == "/v1/info" and method == "GET":
            return reply("200 OK", {"compiler": snapshot, "language": "ShipMBLang", "model_calls": False})
        if path not in {"/v1/run", "/v1/check"}:
            return reply("404 Not Found", {"error": "Unknown endpoint."})
        if method != "POST":
            return reply("405 Method Not Allowed", {"error": "Use POST."})
        if environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
            return reply("415 Unsupported Media Type", {"error": "Send JSON."})
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
        except ValueError:
            return reply("400 Bad Request", {"error": "Invalid content length."})
        if not 0 < length <= MAX_BODY:
            return reply("413 Content Too Large", {"error": "Keep the request below 64 KiB."})
        try:
            value = json.loads(environ["wsgi.input"].read(length))
        except (ValueError, UnicodeDecodeError):
            return reply("400 Bad Request", {"error": "Invalid JSON."})
        if not isinstance(value, dict) or not isinstance(value.get("source"), str) or not value["source"].strip():
            return reply("400 Bad Request", {"error": "Write a program first."})
        if value.get("compiler") != snapshot:
            return reply("409 Conflict", {"error": "Compiler snapshot mismatch. Update the app and service together.", "compiler": snapshot})
        try:
            code, result = runner(value["source"], "compile" if path == "/v1/check" else "run", timeout=20)
        except subprocess.TimeoutExpired:
            return reply("408 Request Timeout", {"error": "Program stopped after 20 seconds."})
        except Exception:
            return reply("500 Internal Server Error", {"error": "The compiler could not finish this program."})
        return reply("200 OK", {"compiler": snapshot, "ok": code == 0,
                     "stdout": result.get("runtime", {}).get("stdout", ""),
                     "diagnostics": result.get("diagnostics", []),
                     "clarifications": result.get("clarifications", [])})

    app.media_jobs = get_jobs
    app.close = lambda: jobs.close() if jobs is not None else None
    return app


class MediaServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(30)
        return connection, address


def main():
    parser = argparse.ArgumentParser(description="Serve the bundled ShipMBLang compiler to a mobile development client.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        app = create_app()
    except ValueError as error:
        parser.error(str(error))
    with make_server(args.host, args.port, app, server_class=MediaServer) as server:
        print(f"ShipMB mobile development service: http://{args.host}:{server.server_port}", flush=True)
        print("Use an HTTPS reverse proxy and production WSGI server for remote deployment.", flush=True)
        try:
            server.serve_forever()
        finally:
            app.close()


if __name__ == "__main__":
    main()
