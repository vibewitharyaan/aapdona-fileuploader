import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import zipfile
from http.client import HTTPConnection

from app.config import Settings
from app.server import build_server


class UploaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.settings = Settings(
            host="127.0.0.1",
            port=0,
            upload_dir=cls.tmp,
            max_size=2048,
            storage_cap=3000,
            password="sekret",
            zip_scan_limit=1024 * 1024,
        )
        cls.server = build_server(cls.settings)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def conn(self):
        return HTTPConnection("127.0.0.1", self.port, timeout=10)

    def setUp(self):
        for n in self.files():
            os.remove(os.path.join(self.tmp, n))

    def upload(self, url, data, key="sekret", chunked=False):
        c = self.conn()
        headers = {"X-Upload-Key": key} if key else {}
        if chunked:
            c.request("POST", url, body=io.BytesIO(data), headers=headers, encode_chunked=True)
        else:
            c.request("POST", url, body=data, headers=headers)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def prepare(self, url, key="sekret"):
        c = self.conn()
        headers = {"X-Upload-Key": key} if key else {}
        c.request("POST", url, body=b"", headers=headers)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def get(self, path, headers=None):
        c = self.conn()
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def delete(self, path, headers=None):
        c = self.conn()
        c.request("DELETE", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def files(self):
        return sorted(os.listdir(self.tmp))

    def json(self, status, body):
        self.assertEqual(status, 200)
        return json.loads(body)

    def cleanup(self):
        for n in self.files():
            os.remove(os.path.join(self.tmp, n))

    def test_page_and_assets(self):
        r, page = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"AAP DO NA", page)
        self.assertIn(b"Lifetime", page)
        r, css = self.get("/static/style.css")
        self.assertEqual(r.status, 200)
        self.assertIn(b"--teal", css)

    def test_status_empty(self):
        r, body = self.get("/status")
        self.assertEqual(json.loads(body), {"pending": 0, "bytes": 0, "cap": 3000})

    def test_upload_requires_key(self):
        status, body = self.upload("/upload?name=a.txt&lifetime=1d", b"aaa", key=None)
        self.assertEqual(status, 401)
        status, body = self.upload("/upload?name=a.txt&lifetime=1d", b"aaa", key="wrong")
        self.assertEqual(status, 401)
        self.assertEqual(self.files(), [])

    def test_upload_download_cycle(self):
        data = b"hello-uploader"
        status, body = self.upload("/upload?name=payload.txt&lifetime=1d", data)
        j = self.json(status, body)
        token = j["ok"]

        self.assertTrue(os.path.isfile(os.path.join(self.tmp, token)))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, token + ".json")))

        r, body = self.get("/status")
        self.assertEqual(json.loads(body), {"pending": 1, "bytes": len(data), "cap": 3000})

        r, body = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        self.assertEqual(body, data)
        self.assertEqual(r.getheader("Content-Disposition"), 'attachment; filename="payload.txt"; filename*=UTF-8\'\'payload.txt')

        r, body = self.get("/status")
        self.assertEqual(json.loads(body), {"pending": 1, "bytes": len(data), "cap": 3000})
        self.cleanup()

    def test_one_shot_deletes_after_download(self):
        status, body = self.upload("/upload?name=s.txt&lifetime=once", b"oneshot")
        token = self.json(status, body)["ok"]
        r, _ = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        for _ in range(50):
            if not self.files():
                break
            time.sleep(0.02)
        self.assertEqual(self.files(), [])

    def test_download_page_for_browsers(self):
        data = b"page-test"
        status, body = self.upload("/upload?name=p.html&lifetime=1d", data)
        token = self.json(status, body)["ok"]
        r, page = self.get("/f/" + token, {"Accept": "text/html"})
        self.assertEqual(r.status, 200)
        self.assertIn(b"File ready", page)
        self.assertEqual(self.files(), [token, token + ".json"])

    def test_info_endpoint(self):
        data = b"info-test"
        status, body = self.upload("/upload?name=i.bin&lifetime=1d", data)
        token = self.json(status, body)["ok"]
        r, body = self.get("/f/" + token + "?info=1")
        j = json.loads(body)
        self.assertEqual(j["name"], "i.bin")
        self.assertEqual(j["size"], len(data))
        self.assertIn("eta", j)

    def test_ttl_expiry(self):
        status, body = self.upload("/upload?name=e.txt&lifetime=1h", b"expireme")
        token = self.json(status, body)["ok"]
        r, _ = self.get("/f/" + token, {"Accept": "text/html"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.files(), [token, token + ".json"])
        with open(os.path.join(self.tmp, token + ".json"), "w") as f:
            json.dump({"name": "e.txt", "size": 8, "ts": 0, "expires_at": 1, "lifetime": 3600, "once": False}, f)
        r, _ = self.get("/f/" + token)
        self.assertEqual(r.status, 410)

    def test_ttl_refresh_after_download(self):
        status, body = self.upload("/upload?name=r.txt&lifetime=1h", b"refresh")
        token = self.json(status, body)["ok"]
        r, _ = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        meta = None
        for _ in range(50):
            try:
                with open(os.path.join(self.tmp, token + ".json")) as f:
                    meta = json.load(f)
                break
            except ValueError:
                time.sleep(0.02)
        self.assertGreater(meta["expires_at"], time.time())

    def test_multiple_files_pending(self):
        self.upload("/upload?name=a.txt&lifetime=1d", b"aaa")
        status, body = self.upload("/upload?name=b.txt&lifetime=1d", b"bbb")
        j = self.json(status, body)
        self.assertEqual(len(self.files()), 4)
        self.cleanup()

    def test_storage_cap_507(self):
        status, body = self.upload("/upload?name=big1.txt&lifetime=1d", b"x" * 1500)
        j = self.json(status, body)
        status, body = self.upload("/upload?name=big2.txt&lifetime=1d", b"y" * 2000)
        self.assertEqual(status, 507)
        self.assertEqual(len(self.files()), 2)
        self.cleanup()

    def test_chunked_upload_stores_clean_bytes(self):
        data = b"chunked-body-bytes"
        status, body = self.upload("/upload?name=c.txt&lifetime=1d", data, chunked=True)
        j = self.json(status, body)
        with open(os.path.join(self.tmp, j["ok"]), "rb") as f:
            self.assertEqual(f.read(), data)
        self.cleanup()

    def test_oversize_content_length_413(self):
        c = self.conn()
        c.putrequest("POST", "/upload?name=big.txt&lifetime=1d")
        c.putheader("Content-Length", "999999")
        c.putheader("X-Upload-Key", "sekret")
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 413)
        r.read()
        c.close()
        self.assertEqual(self.files(), [])

    def test_oversize_streamed_413(self):
        status, body = self.upload("/upload?name=big.txt&lifetime=1d", b"x" * 4096)
        self.assertEqual(status, 413)
        self.assertEqual(self.files(), [])

    def test_zip_bomb_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(10):
                z.writestr("f%d" % i, b"0" * 10000)
        status, body = self.upload("/upload?name=bomb.zip&lifetime=1d", buf.getvalue())
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_normal_zip_accepted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("a.txt", b"hello")
        status, body = self.upload("/upload?name=ok.zip&lifetime=1d", buf.getvalue())
        j = self.json(status, body)
        self.cleanup()

    def test_bad_lifetime_400(self):
        status, body = self.upload("/upload?name=a.txt&lifetime=99d", b"aaa")
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_bad_name_400(self):
        status, body = self.upload("/upload?name=&lifetime=1d", b"x")
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_upload_traversal_400(self):
        status, body = self.upload("/upload?name=..%2fetc%2fpasswd&lifetime=1d", b"x")
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_missing_file_404(self):
        r, _ = self.get("/f/nope")
        self.assertEqual(r.status, 404)

    def test_download_does_not_need_key(self):
        status, body = self.upload("/upload?name=d.txt&lifetime=1d", b"data")
        token = self.json(status, body)["ok"]
        r, _ = self.get("/f/" + token, {"Accept": "text/html"})
        self.assertEqual(r.status, 200)

    def test_delete_clears(self):
        self.upload("/upload?name=a.txt&lifetime=1d", b"aaa")
        r, body = self.delete("/upload", {"X-Upload-Key": "sekret"})
        self.assertEqual(json.loads(body), {"cleared": True})
        self.assertEqual(self.files(), [])

    def test_delete_single_token(self):
        status, body = self.prepare("/upload/prepare?name=a.bin&lifetime=30m&size=10")
        token = self.json(status, body)["ok"]
        r, body = self.delete("/upload/" + token, {"X-Upload-Key": "sekret"})
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(self.files(), [])

    def test_delete_single_token_requires_key(self):
        status, body = self.prepare("/upload/prepare?name=a.bin&lifetime=30m&size=10")
        token = self.json(status, body)["ok"]
        r, _ = self.delete("/upload/" + token)
        self.assertEqual(r.status, 401)
        self.assertEqual(self.files(), [token + ".json"])

    def test_prepare_returns_link_before_upload(self):
        status, body = self.prepare("/upload/prepare?name=big.bin&lifetime=1d&size=100")
        j = self.json(status, body)
        self.assertIn("ok", j)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, j["ok"] + ".json")))
        self.assertEqual(len(self.files()), 1)
        self.cleanup()

    def test_prepare_requires_key(self):
        status, body = self.prepare("/upload/prepare?name=b.bin&lifetime=1d&size=10", key=None)
        self.assertEqual(status, 401)
        self.assertEqual(self.files(), [])

    def test_prepare_oversize_413(self):
        status, body = self.prepare("/upload/prepare?name=b.bin&lifetime=1d&size=999999")
        self.assertEqual(status, 413)
        self.assertEqual(self.files(), [])

    def test_prepare_bad_lifetime_400(self):
        status, body = self.prepare("/upload/prepare?name=b.bin&lifetime=99d&size=10")
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_prepare_then_stream_completes(self):
        data = b"streamed-body-bytes"
        status, body = self.prepare("/upload/prepare?name=s.bin&lifetime=1d&size=" + str(len(data)))
        token = self.json(status, body)["ok"]

        r, page = self.get("/f/" + token, {"Accept": "text/html"})
        self.assertEqual(r.status, 200)
        self.assertIn(b"Hold on!", page)

        r, body = self.get("/f/" + token + "?info=1")
        j = json.loads(body)
        self.assertEqual(j["status"], "uploading")
        self.assertEqual(j["written"], 0)

        r, _ = self.get("/f/" + token)
        self.assertEqual(r.status, 409)

        status, body = self.upload("/upload/" + token, data)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["ok"], token)

        r, body = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        self.assertEqual(body, data)
        self.cleanup()

    def test_upload_to_short_write_cancelled(self):
        status, body = self.prepare("/upload/prepare?name=c.bin&lifetime=30m&size=100")
        token = self.json(status, body)["ok"]
        status, body = self.upload("/upload/" + token, b"x" * 10)
        self.assertEqual(status, 400)
        self.assertEqual(self.files(), [])

    def test_upload_to_unknown_token_404(self):
        status, _ = self.upload("/upload/nope", b"x")
        self.assertEqual(status, 404)

    def test_upload_to_requires_key(self):
        status, body = self.prepare("/upload/prepare?name=b.bin&lifetime=1d&size=10")
        token = self.json(status, body)["ok"]
        status, _ = self.upload("/upload/" + token, b"x", key=None)
        self.assertEqual(status, 401)

    def test_sweep_removes_stalled_upload(self):
        status, body = self.prepare("/upload/prepare?name=b.bin&lifetime=1d&size=10")
        token = self.json(status, body)["ok"]
        with open(os.path.join(self.tmp, token + ".json")) as f:
            meta = json.load(f)
        meta["updated_at"] = time.time() - 99999
        with open(os.path.join(self.tmp, token + ".json"), "w") as f:
            json.dump(meta, f)
        from app import storage
        storage.sweep(self.tmp, stall=3600)
        self.assertEqual(self.files(), [])

    def test_sweep_removes_stalled_tmp(self):
        tmp = os.path.join(self.tmp, ".tmp-stale")
        with open(tmp, "w") as f:
            f.write("x")
        old = time.time() - 99999
        os.utime(tmp, (old, old))
        from app import storage
        storage.sweep(self.tmp, stall=3600)
        self.assertEqual(self.files(), [])

    def test_delete_all_requires_key(self):
        self.upload("/upload?name=a.txt&lifetime=1d", b"aaa")
        r, _ = self.delete("/upload")
        self.assertEqual(r.status, 401)
        self.assertEqual(len(self.files()), 2)

    def test_delete_all_wrong_key_rejected(self):
        self.upload("/upload?name=a.txt&lifetime=1d", b"aaa")
        r, _ = self.delete("/upload", {"X-Upload-Key": "nope"})
        self.assertEqual(r.status, 401)
        self.assertEqual(len(self.files()), 2)

    def test_empty_password_rejects_upload(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            upload_dir=self.tmp,
            max_size=2048,
            storage_cap=3000,
            password="",
            zip_scan_limit=1024 * 1024,
        )
        server = build_server(settings)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            for path in ("/upload?name=a.txt&lifetime=1d", "/upload/prepare?name=b.bin&lifetime=1d&size=10"):
                c = HTTPConnection("127.0.0.1", port, timeout=10)
                c.request("POST", path, body=b"x", headers={"X-Upload-Key": "sekret"})
                r = c.getresponse()
                r.read()
                c.close()
                self.assertEqual(r.status, 401)
            c = HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("DELETE", "/upload", headers={"X-Upload-Key": "sekret"})
            r = c.getresponse()
            r.read()
            c.close()
            self.assertEqual(r.status, 401)
        finally:
            server.shutdown()
            server.server_close()
            t.join()

    def test_unicode_filename_download(self):
        status, body = self.upload("/upload?name=%F0%9F%98%80.txt&lifetime=1d", b"emoji")
        token = self.json(status, body)["ok"]
        r, body = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        self.assertEqual(body, b"emoji")
        cd = r.getheader("Content-Disposition")
        self.assertIn("filename*=UTF-8''%F0%9F%98%80.txt", cd)

    def test_quoted_filename_download(self):
        status, body = self.upload("/upload?name=a%22b.txt&lifetime=1d", b"q")
        token = self.json(status, body)["ok"]
        r, _ = self.get("/f/" + token)
        self.assertEqual(r.status, 200)
        cd = r.getheader("Content-Disposition")
        self.assertNotIn('filename="a"b', cd)
        self.assertIn("a%22b.txt", cd)

    def test_truncated_oneshot_rejected(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(
            b"POST /upload?name=t.txt&lifetime=1d HTTP/1.1\r\n"
            b"Host: x\r\nX-Upload-Key: sekret\r\nContent-Length: 100\r\n\r\n"
            b"hello"
        )
        s.close()
        for _ in range(50):
            if not self.files():
                break
            time.sleep(0.02)
        self.assertEqual(self.files(), [])

    def test_orphan_data_swept(self):
        orphan = os.path.join(self.tmp, "orphan")
        with open(orphan, "w") as f:
            f.write("x" * 5000)
        old = time.time() - 99999
        os.utime(orphan, (old, old))
        from app import storage
        storage.sweep(self.tmp, stall=3600)
        self.assertEqual(self.files(), [])

    def test_once_never_downloaded_expires(self):
        status, body = self.upload("/upload?name=o.txt&lifetime=once", b"once")
        token = self.json(status, body)["ok"]
        with open(os.path.join(self.tmp, token + ".json")) as f:
            meta = json.load(f)
        self.assertGreater(meta["expires_at"], time.time())
        meta["expires_at"] = time.time() - 1
        with open(os.path.join(self.tmp, token + ".json"), "w") as f:
            json.dump(meta, f)
        from app import storage
        storage.sweep(self.tmp, stall=3600)
        self.assertEqual(self.files(), [])

    def test_concurrent_cap_not_exceeded(self):
        results = []

        def worker():
            status, _ = self.upload("/upload?name=c.bin&lifetime=1d", b"y" * 2000)
            results.append(status)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(507), 7)
        r, body = self.get("/status")
        self.assertEqual(json.loads(body)["bytes"], 2000)
        self.cleanup()

    def test_concurrent_sweep_no_crash(self):
        errors = []

        def uploader(i):
            try:
                self.upload("/upload?name=%d.txt&lifetime=1d" % i, b"x" * 100)
            except Exception as e:
                errors.append(e)

        def status():
            try:
                self.get("/status")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=uploader, args=(i,)) for i in range(8)]
        threads += [threading.Thread(target=status) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.cleanup()


if __name__ == "__main__":
    unittest.main()