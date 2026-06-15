"""Configuration loader.

Reads credentials from the project .env file (never hard-coded). The .env file
is gitignored; see .env.example for the template.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root (one level up from src/). The .env there is loaded lazily in
# from_env() rather than at import time so that importing this module has no side
# effects (keeps tests hermetic).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        # load_dotenv does not override variables already set in the environment.
        load_dotenv(PROJECT_ROOT / ".env")
        username = os.environ.get("METEOLOGICA_USERNAME", "")
        password = os.environ.get("METEOLOGICA_PASSWORD", "")
        base_url = os.environ.get(
            "METEOLOGICA_BASE_URL", "https://api-markets.meteologica.com"
        )
        if not username or not password:
            raise RuntimeError(
                "Missing Meteologica credentials. Copy .env.example to .env and fill it in."
            )
        return cls(username=username, password=password, base_url=base_url.rstrip("/"))


def get_settings() -> Settings:
    return Settings.from_env()
