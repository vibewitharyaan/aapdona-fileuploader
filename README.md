# AAP DO NA

Simple self-hosted file sharing. Drop a file, get a link, file expires on its own.

Built for fun. Password-protected uploads, TTL-based expiry, "once" links that self-delete after one download.

## Run

```bash
UPLOAD_PASSWORD=secret python3 -m app
```

No dependencies, stdlib only. Server on `127.0.0.1:8000`.

## Configuration

Environment variables (see `app/config.py` for defaults):

| Var | Default | What |
| --- | --- | --- |
| `UPLOAD_HOST` | `127.0.0.1` | Bind address |
| `UPLOAD_PORT` | `8000` | Port |
| `UPLOAD_PASSWORD` | empty | Required key for uploads; unset = uploads disabled |
| `UPLOAD_DIR` | `uploads/` | Where files go |
| `MAX_SIZE` | 4 GB | Per-file limit |
| `STORAGE_CAP` | 4 GB | Total cap |
| `SOCK_TIMEOUT` | 300s | Socket timeout |

## Test

```bash
python3 -m unittest discover -s tests
```

## Hosting

Cloudflare Tunnel + Docker, localhost-only. See `docs/HOSTING.md`.
Live at https://aapdona.vibewitharyaan.dev