"""Tests for credential loading in src.config."""
from __future__ import annotations

from unittest import mock

import pytest

from src.config import Settings


def test_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METEOLOGICA_USERNAME", "u")
    monkeypatch.setenv("METEOLOGICA_PASSWORD", "p")
    monkeypatch.setenv("METEOLOGICA_BASE_URL", "https://example.com/")
    # Don't read the real .env file during the test.
    with mock.patch("src.config.load_dotenv"):
        s = Settings.from_env()
    assert s.username == "u"
    assert s.password == "p"
    assert s.base_url == "https://example.com"  # trailing slash stripped


def test_from_env_defaults_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METEOLOGICA_USERNAME", "u")
    monkeypatch.setenv("METEOLOGICA_PASSWORD", "p")
    monkeypatch.delenv("METEOLOGICA_BASE_URL", raising=False)
    with mock.patch("src.config.load_dotenv"):
        s = Settings.from_env()
    assert s.base_url == "https://api-markets.meteologica.com"


def test_from_env_missing_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METEOLOGICA_USERNAME", raising=False)
    monkeypatch.delenv("METEOLOGICA_PASSWORD", raising=False)
    with mock.patch("src.config.load_dotenv"):  # ensure the real .env can't fill them in
        with pytest.raises(RuntimeError, match="Missing Meteologica credentials"):
            Settings.from_env()
