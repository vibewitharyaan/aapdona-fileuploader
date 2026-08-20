import os
from dataclasses import dataclass, field

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("UPLOAD_HOST", "127.0.0.1")
    port: int = _int("UPLOAD_PORT", 8000)
    upload_dir: str = os.environ.get("UPLOAD_DIR", os.path.join(PROJECT, "uploads"))
    max_size: int = _int("MAX_SIZE", 4 * 1024 ** 3)
    storage_cap: int = _int("STORAGE_CAP", 4 * 1024 ** 3)
    password: str = os.environ.get("UPLOAD_PASSWORD", "")
    bandwidth: int = _int("ASSUMED_BANDWIDTH", 20 * 1024 ** 2)
    zip_scan_limit: int = _int("ZIP_SCAN_LIMIT", 64 * 1024 ** 2)
    once_ttl: int = _int("ONCE_TTL", 3 * 24 * 3600)
    sock_timeout: float = _int("SOCK_TIMEOUT", 300)
    max_threads: int = _int("MAX_THREADS", 32)
    chunk: int = 256 * 1024
    static_dir: str = os.path.join(BASE, "static")

    lifetimes: dict = field(default_factory=lambda: {
        "5m": 5 * 60,
        "30m": 30 * 60,
        "1h": 3600,
        "6h": 6 * 3600,
        "1d": 24 * 3600,
        "3d": 3 * 24 * 3600,
        "once": 0,
    })