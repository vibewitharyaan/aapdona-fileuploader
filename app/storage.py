import json
import os
import threading
import time

lock = threading.Lock()


def is_meta(name):
    return name.endswith(".json")


def data_path(root, token):
    return os.path.join(root, token)


def meta_path(root, token):
    return os.path.join(root, token + ".json")


def save(root, token, meta):
    with open(meta_path(root, token), "w") as f:
        json.dump(meta, f)


def read_meta(root, token):
    try:
        with open(meta_path(root, token)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def token_exists(root, token):
    return os.path.isfile(data_path(root, token))


def delete(root, token):
    for p in (data_path(root, token), meta_path(root, token)):
        try:
            os.remove(p)
        except OSError:
            pass


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def sweep(root, now=None, stall=3600):
    now = now if now is not None else time.time()
    removed = []
    for name in os.listdir(root):
        if name.startswith(".tmp-"):
            mtime = _mtime(os.path.join(root, name))
            if mtime is not None and now - mtime > stall:
                delete(root, name)
                removed.append(name)
            continue
        if is_meta(name):
            token = name[: -len(".json")]
            meta = read_meta(root, token)
            if meta and meta.get("status") == "uploading" and now - meta.get("updated_at", 0) > stall:
                delete(root, token)
                removed.append(token)
            continue
        meta = read_meta(root, name)
        if meta and meta.get("expires_at") and meta["expires_at"] <= now:
            delete(root, name)
            removed.append(name)
        elif not meta:
            mtime = _mtime(os.path.join(root, name))
            if mtime is not None and now - mtime > stall:
                delete(root, name)
                removed.append(name)
    return removed


def pending(root, now=None):
    sweep(root, now)
    now = now if now is not None else time.time()
    result = []
    for token in os.listdir(root):
        if is_meta(token):
            continue
        meta = read_meta(root, token)
        if meta:
            result.append((token, meta))
    return result


def total_bytes(root, now=None):
    return sum(meta.get("size", 0) for _, meta in pending(root, now))


def clear(root):
    removed = False
    for token in os.listdir(root):
        if is_meta(token):
            continue
        delete(root, token)
        removed = True
    return removed


def sanitize(name):
    raw = (name or "").replace("\\", "/")
    if ".." in raw.split("/"):
        return None
    name = os.path.basename(raw)
    if not name or name in (".", ".."):
        return None
    if any(ord(c) < 32 for c in name):
        return None
    return name


def resolve(root, name):
    root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, name))
    if real != root and not real.startswith(root + os.sep):
        return None
    return real