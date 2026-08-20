# aapdona-fileuploader

Self-hosted file sharing. You drop a file, you get a link, the file quietly
expires on its own. No accounts, no cloud bill, no reason to keep anything
around longer than it needs to be.

Why this exists? Boredom, mostly. It's stdlib-only and deliberately small.

## What it does

- Password-protected uploads — one shared key, not a user system
- Links expire on a timer (5m to 3d, your pick)
- "Once" links that self-delete after the first download
- Caps on file size and total storage, so it can't eat your disk
- Rejects archive bombs, because that seemed wise

## Run

```bash
UPLOAD_PASSWORD=secret python3 -m app
```

Server on `127.0.0.1:8000`. Leave `UPLOAD_PASSWORD` unset and uploads are
disabled.

## Configuration

Environment variables (defaults in `app/config.py`):

| Var | Default | What |
| --- | --- | --- |
| `UPLOAD_HOST` | `127.0.0.1` | Bind address |
| `UPLOAD_PORT` | `8000` | Port |
| `UPLOAD_PASSWORD` | empty | Key for uploads; unset = disabled |
| `UPLOAD_DIR` | `uploads/` | Where files go |
| `MAX_SIZE` | 4 GB | Per-file limit |
| `STORAGE_CAP` | 4 GB | Total cap |
| `SOCK_TIMEOUT` | 300s | Socket timeout |

## Self-hosting

Needs nothing but Python 3.7+ — no packages, no `pip install`, no build step.

1. Clone or download this repo.
2. Set a password and start it:

   ```bash
   UPLOAD_PASSWORD=secret python3 -m app
   ```

3. That's it. Upload at `http://localhost:8000`.

If the server isn't the machine you're browsing from, tell it to listen
everywhere and reach it over your network:

```bash
UPLOAD_HOST=0.0.0.0 UPLOAD_PASSWORD=secret python3 -m app
```

From there, it's whatever transport you like: a reverse proxy (nginx, Caddy),
a tunnel (Cloudflare, ngrok), or just a LAN IP. The app doesn't care.

Two practical notes:

- Files land in `uploads/` — back it up if you want files to survive the
  machine.
- Running it in a terminal means it dies with the terminal. For something
  longer-lived, wrap it however you normally do: `systemd`, Docker, `tmux`,
  a `&`. Your call, all fine.

## Test

```bash
python3 -m unittest discover -s tests
```
