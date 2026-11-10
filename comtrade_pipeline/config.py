"""
Configuration & environment management.

Settings are read from environment variables (optionally loaded from a ``.env`` file
at the project root). Nothing here has import-time side effects other than loading
``.env`` - the output directory is created lazily by :func:`get_output_dir`.
"""

import logging
import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; plain environment variables still work
    load_dotenv = None

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output"

API_KEY_ENV = "COMTRADE_API_KEY"
OUTPUT_DIR_ENV = "COMTRADE_OUTPUT_DIR"
_PLACEHOLDERS = {"", "your_subscription_key_here", "your_api_key", "changeme"}

if load_dotenv is not None:
    load_dotenv(ENV_FILE)

logger = logging.getLogger("comtrade_pipeline")


class ConfigError(RuntimeError):
    """Raised when required configuration (e.g. the API key) is missing or invalid."""


def setup_logging(level: int = logging.INFO) -> None:
    """Configure console logging once. Call from entry points only (never on import)."""
    root = logging.getLogger("comtrade_pipeline")
    if root.handlers:
        root.setLevel(level)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


def get_output_dir(create: bool = True) -> Path:
    """Return the output directory (``COMTRADE_OUTPUT_DIR`` or ``./output``)."""
    raw = os.getenv(OUTPUT_DIR_ENV, "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_OUTPUT_DIR
    if not path.is_absolute():
        path = ROOT_DIR / path
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_api_key(explicit_key: Optional[str] = None) -> str:
    """
    Resolve the UN Comtrade subscription key, in priority order:
      1. ``explicit_key`` (e.g. the ``--api-key`` CLI flag)
      2. the ``COMTRADE_API_KEY`` environment variable / ``.env`` file
    """
    for candidate in (explicit_key, os.getenv(API_KEY_ENV)):
        if candidate and candidate.strip().lower() not in _PLACEHOLDERS:
            return candidate.strip()
    raise ConfigError(
        f"ไม่พบ UN Comtrade API Key! กำหนด {API_KEY_ENV} ในไฟล์ {ENV_FILE} "
        f"(ดูตัวอย่างใน .env.example) หรือส่งผ่าน --api-key"
    )


def mask_key(key: str) -> str:
    """Return a safely printable version of a secret."""
    return key[:2] + "*" * 6 + key[-2:] if len(key) > 8 else "***"

