import io
import json
import os
import secrets
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote, parse_qs, quote

from .config import Settings
from . import storage

CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "ico": "image/x-icon",
}

MAX_RATIO = 50
ONE_SHOT = "once"


def content_disposition(name):
    ascii_fallback = name.encode("ascii", "replace").decode("ascii").replace('"', "_") or "download"
    encoded = quote(name.encode("utf-8"), safe="")
    return 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_fallback, encoded)


def body_chunks(rfile, headers, chunk):
    length = headers.get("Content-Length")
    if length:
        try:
            remaining = int(length)
        except ValueError:
            return
        while remaining:
            buf = rfile.read(min(chunk, remaining))
            if not buf:
                return
            remaining -= len(buf)
            yield buf
        return
    if (headers.get("Transfer-Encoding") or "").lower() == "chunked":
        while True:
            line = rfile.readline()
            if not line:
                return
            try:
                size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError:
                return
            if size == 0:
                rfile.readline()
                return
            remaining = size
            while remaining:
                buf = rfile.read(min(chunk, remaining))
                if not buf:
                    return
                remaining -= len(buf)
                yield buf
            rfile.read(2)
        return
    while True:
        buf = rfile.read(chunk)
        if not buf:
            return
        yield buf


def archive_bomb(path, scan_limit):
    if os.path.getsize(path) > scan_limit or not zipfile.is_zipfile(path):
        return False
    with open(path, "rb") as f:
        data = f.read()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
            return total > len(data) * MAX_RATIO
    except zipfile.BadZipFile:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "Uploader"

    def log_message(self, fmt, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.settings.sock_timeout)

    def handle(self):
        if not self.server.sem.acquire(blocking=False):
            try:
                self.send_bytes(b"busy", 503, "text/plain")
            finally:
                self.close_connection = True
            return
        try:
            super().handle()
        finally:
            self.server.sem.release()

    def send_bytes(self, data, code=200, ctype="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def send_json(self, obj, code=200):
        self.send_bytes(json.dumps(obj).encode(), code, "application/json")

    def serve_static(self, rel):
        settings = self.server.settings
        real = storage.resolve(settings.static_dir, rel)
        if not real or not os.path.isfile(real):
            return self.send_bytes(b"not found", 404, "text/plain")
        ext = os.path.splitext(real)[1].lstrip(".").lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(real, "rb") as f:
            data = f.read()
        cache = "no-cache" if rel == "index.html" else "public, max-age=300"
        self.send_bytes(data, 200, ctype, {"Cache-Control": cache})

    def check_auth(self):
        key = self.headers.get("X-Upload-Key", "")
        ok = bool(self.server.settings.password) and secrets.compare_digest(
            key, self.server.settings.password)
        if not ok:
            print("uploader: auth rejected from %s" % (self.client_address[0],), flush=True)
        return ok

    def info(self, token, meta):
        settings = self.server.settings
        return {
            "name": meta.get("name", token),
            "size": meta.get("size", 0),
            "bandwidth": settings.bandwidth,
            "eta": round(meta.get("size", 0) / max(settings.bandwidth, 1), 1),
            "expires_at": meta.get("expires_at"),
            "once": meta.get("once", False),
        }

    def pending_download(self, token, meta):
        settings = self.server.settings
        qs = parse_qs(urlsplit(self.path).query)
        if "info" in qs:
            written = meta.get("size", 0)
            total = meta.get("expected", 0)
            return self.send_json({
                "status": "uploading",
                "name": meta.get("name", token),
                "written": written,
                "total": total,
                "remaining": max(total - written, 0),
            })
        if "text/html" in self.headers.get("Accept", "") and "dl" not in qs:
            return self.serve_static("wait.html")
        return self.send_bytes(b"still uploading", 409, "text/plain")

    def download(self, token):
        settings = self.server.settings
        if not token or "/" in token:
            return self.send_bytes(b"bad token", 400, "text/plain")
        meta = storage.read_meta(settings.upload_dir, token)
        if not meta:
            return self.send_bytes(b"not found", 404, "text/plain")
        if meta.get("status") == "uploading":
            return self.pending_download(token, meta)
        if not storage.token_exists(settings.upload_dir, token):
            return self.send_bytes(b"not found", 404, "text/plain")
        if meta.get("expires_at") and meta["expires_at"] <= time.time():
            storage.delete(settings.upload_dir, token)
            return self.send_bytes(b"expired", 410, "text/plain")

        accept = self.headers.get("Accept", "")
        qs = parse_qs(urlsplit(self.path).query)
        if "text/html" in accept and "dl" not in qs:
            return self.serve_static("download.html")
        if "info" in qs:
            return self.send_json(self.info(token, meta))

        real = storage.data_path(settings.upload_dir, token)
        size = os.path.getsize(real)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", content_disposition(meta.get("name", token)))
        self.end_headers()
        try:
            with open(real, "rb") as f:
                while True:
                    buf = f.read(settings.chunk)
                    if not buf:
                        break
                    self.wfile.write(buf)
        except (BrokenPipeError, ConnectionResetError):
            return
        if meta.get("once"):
            storage.delete(settings.upload_dir, token)
        elif meta.get("lifetime"):
            meta["expires_at"] = time.time() + meta["lifetime"]
            storage.save(settings.upload_dir, token, meta)

    def upload(self, qs):
        settings = self.server.settings
        if not self.check_auth():
            return self.send_json({"error": "bad key"}, 401)
        name = storage.sanitize(qs.get("name", [""])[0])
        if not name:
            return self.send_bytes(b"bad name", 400, "text/plain")
        lifetime = qs.get("lifetime", ["30m"])[0]
        ttl = settings.lifetimes.get(lifetime)
        if ttl is None:
            return self.send_bytes(b"bad lifetime", 400, "text/plain")
        once = lifetime == ONE_SHOT
        declared = 0
        length = self.headers.get("Content-Length")
        if length:
            try:
                declared = int(length)
                if declared > settings.max_size:
                    return self.send_json({"error": "too large"}, 413)
            except ValueError:
                return self.send_bytes(b"bad request", 400, "text/plain")
        token = secrets.token_urlsafe(16)
        tmp = os.path.join(settings.upload_dir, ".tmp-" + token)
        written = 0
        over = False
        try:
            with open(tmp, "wb") as f:
                for buf in body_chunks(self.rfile, self.headers, settings.chunk):
                    written += len(buf)
                    if written > settings.max_size:
                        over = True
                        break
                    f.write(buf)
        except OSError:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            return self.send_json({"error": "write failed"}, 500)
        if over:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            return self.send_json({"error": "too large"}, 413)
        if declared and written != declared:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            return self.send_json({"error": "incomplete"}, 400)
        if archive_bomb(tmp, settings.zip_scan_limit):
            storage.delete(settings.upload_dir, ".tmp-" + token)
            return self.send_json({"error": "archive bomb rejected"}, 400)
        with storage.lock:
            if storage.total_bytes(settings.upload_dir) + written > settings.storage_cap:
                storage.delete(settings.upload_dir, ".tmp-" + token)
                return self.send_json({"error": "storage full"}, 507)
            final = storage.data_path(settings.upload_dir, token)
            os.replace(tmp, final)
            now = time.time()
            storage.save(settings.upload_dir, token, {
                "name": name,
                "size": written,
                "ts": now,
                "expires_at": now + (ttl or settings.once_ttl),
                "lifetime": ttl,
                "once": once,
            })
        self.send_json({"ok": token, "name": name})

    def prepare(self, qs):
        settings = self.server.settings
        if not self.check_auth():
            return self.send_json({"error": "bad key"}, 401)
        name = storage.sanitize(qs.get("name", [""])[0])
        if not name:
            return self.send_bytes(b"bad name", 400, "text/plain")
        lifetime = qs.get("lifetime", ["30m"])[0]
        ttl = settings.lifetimes.get(lifetime)
        if ttl is None:
            return self.send_bytes(b"bad lifetime", 400, "text/plain")
        once = lifetime == ONE_SHOT
        expected = 0
        try:
            expected = int(qs.get("size", ["0"])[0])
        except ValueError:
            return self.send_bytes(b"bad request", 400, "text/plain")
        if expected < 0 or expected > settings.max_size:
            return self.send_json({"error": "too large"}, 413)
        token = secrets.token_urlsafe(16)
        now = time.time()
        with storage.lock:
            if storage.total_bytes(settings.upload_dir) + expected > settings.storage_cap:
                return self.send_json({"error": "storage full"}, 507)
            storage.save(settings.upload_dir, token, {
                "name": name,
                "size": 0,
                "expected": expected,
                "ts": now,
                "updated_at": now,
                "expires_at": now + (ttl or settings.once_ttl),
                "lifetime": ttl,
                "once": once,
                "status": "uploading",
            })
        self.send_json({"ok": token, "name": name})

    def upload_to(self, token):
        settings = self.server.settings
        if not token or "/" in token:
            return self.send_bytes(b"bad token", 400, "text/plain")
        if not self.check_auth():
            return self.send_json({"error": "bad key"}, 401)
        meta = storage.read_meta(settings.upload_dir, token)
        if not meta or meta.get("status") != "uploading":
            return self.send_bytes(b"bad token", 404, "text/plain")
        expected = meta.get("expected", 0)
        tmp = os.path.join(settings.upload_dir, ".tmp-" + token)
        written = 0
        over = False
        last_save = 0
        try:
            with open(tmp, "wb") as f:
                for buf in body_chunks(self.rfile, self.headers, settings.chunk):
                    written += len(buf)
                    if written > settings.max_size:
                        over = True
                        break
                    f.write(buf)
                    now = time.time()
                    if now - last_save > 0.25:
                        meta["size"] = written
                        meta["updated_at"] = now
                        storage.save(settings.upload_dir, token, meta)
                        last_save = now
        except OSError:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            storage.delete(settings.upload_dir, token)
            return self.send_json({"error": "write failed"}, 500)
        if over:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            storage.delete(settings.upload_dir, token)
            return self.send_json({"error": "too large"}, 413)
        if written < expected:
            storage.delete(settings.upload_dir, ".tmp-" + token)
            storage.delete(settings.upload_dir, token)
            return self.send_json({"error": "upload cancelled"}, 400)
        if archive_bomb(tmp, settings.zip_scan_limit):
            storage.delete(settings.upload_dir, ".tmp-" + token)
            storage.delete(settings.upload_dir, token)
            return self.send_json({"error": "archive bomb rejected"}, 400)
        with storage.lock:
            used = storage.total_bytes(settings.upload_dir) - meta.get("size", 0) + written
            if used > settings.storage_cap:
                storage.delete(settings.upload_dir, ".tmp-" + token)
                storage.delete(settings.upload_dir, token)
                return self.send_json({"error": "storage full"}, 507)
            final = storage.data_path(settings.upload_dir, token)
            os.replace(tmp, final)
            now = time.time()
            meta["size"] = written
            meta["expires_at"] = now + (meta.get("lifetime") or settings.once_ttl)
            meta.pop("status", None)
            storage.save(settings.upload_dir, token, meta)
        self.send_json({"ok": token, "name": meta.get("name", token)})

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/":
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(unquote(path[len("/static/"):]))
        if path == "/status":
            total = storage.total_bytes(self.server.settings.upload_dir)
            return self.send_json({
                "pending": len(storage.pending(self.server.settings.upload_dir)),
                "bytes": total,
                "cap": self.server.settings.storage_cap,
            })
        if path == "/auth":
            if self.check_auth():
                return self.send_json({"ok": True})
            return self.send_bytes(b"unauthorized", 401, "text/plain")
        if path.startswith("/f/"):
            return self.download(unquote(path[len("/f/"):]))
        self.send_bytes(b"not found", 404, "text/plain")

    def do_POST(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/upload":
            return self.upload(parse_qs(parts.query))
        if path == "/upload/prepare":
            return self.prepare(parse_qs(parts.query))
        if path.startswith("/upload/"):
            return self.upload_to(unquote(path[len("/upload/"):]))
        self.send_bytes(b"not found", 404, "text/plain")

    def do_DELETE(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/upload":
            if not self.check_auth():
                return self.send_json({"error": "bad key"}, 401)
            return self.send_json({"cleared": storage.clear(self.server.settings.upload_dir)})
        if path.startswith("/upload/"):
            if not self.check_auth():
                return self.send_json({"error": "bad key"}, 401)
            token = unquote(path[len("/upload/"):])
            if not token or "/" in token:
                return self.send_bytes(b"bad token", 400, "text/plain")
            storage.delete(self.server.settings.upload_dir, token)
            return self.send_json({"ok": True})
        self.send_bytes(b"not found", 404, "text/plain")


def build_server(settings):
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    server.settings = settings
    server.sem = threading.BoundedSemaphore(settings.max_threads)
    return server


def main():
    settings = Settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    if not settings.password:
        print("WARNING: UPLOAD_PASSWORD unset; uploads disabled", flush=True)
    server = build_server(settings)
    print(
        "uploader on %s:%s max_size=%d cap=%d uploads=%s"
        % (settings.host, settings.port, settings.max_size, settings.storage_cap, settings.upload_dir),
        flush=True,
    )
    server.serve_forever()