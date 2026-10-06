"""Unit tests for the non-blocking PyPI update check (no network)."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest import mock

import pytest

from agents_memory import updates as u


PKG = "agents-memory"
CUR = "1.0.0"


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTS_HOME", str(tmp_path / "agents"))
    for key in ("AGENTS_NO_UPDATE_CHECK", "CI", "GITHUB_ACTIONS", "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)
    u._mcp_checked.clear()
    yield


def _cache_path() -> Path:
    return u._cache_file(PKG)


def _write_cache(latest: str, last_checked: float | None = None) -> None:
    import time

    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_checked": int(time.time() if last_checked is None else last_checked),
                "latest_version": latest,
            }
        ),
        encoding="utf-8",
    )


def test_newer_prints_stderr(monkeypatch):
    _write_cache("1.2.0")
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)
    with mock.patch.object(u.urllib.request, "urlopen") as urlopen:
        u.check_for_updates(PKG, CUR)
        urlopen.assert_not_called()
    assert buf.getvalue() == f"{PKG} 1.2.0 available (you have {CUR}): uv tool upgrade {PKG}\n"


def test_same_version_silent(monkeypatch):
    _write_cache(CUR)
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)
    u.check_for_updates(PKG, CUR)
    assert buf.getvalue() == ""


def test_offline_silent(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)

    def boom(*a, **k):
        raise OSError("offline")

    with mock.patch.object(u.urllib.request, "urlopen", side_effect=boom):
        u.check_for_updates(PKG, CUR)
    assert buf.getvalue() == ""
    assert not _cache_path().exists()


def test_disabled_env(monkeypatch):
    monkeypatch.setenv("AGENTS_NO_UPDATE_CHECK", "1")
    _write_cache("9.9.9")
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)
    u.check_for_updates(PKG, CUR)
    assert buf.getvalue() == ""


def test_ci_env_silent(monkeypatch):
    monkeypatch.setenv("CI", "true")
    _write_cache("9.9.9")
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)
    u.check_for_updates(PKG, CUR)
    assert buf.getvalue() == ""


def test_fetches_and_caches(monkeypatch):
    payload = json.dumps({"info": {"version": "2.0.0"}}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    buf = io.StringIO()
    monkeypatch.setattr(u.sys, "stderr", buf)
    with mock.patch.object(u.urllib.request, "urlopen", return_value=resp) as urlopen:
        u.check_for_updates(PKG, CUR)
        urlopen.assert_called_once()
    assert "2.0.0 available" in buf.getvalue()
    cached = json.loads(_cache_path().read_text(encoding="utf-8"))
    assert cached["latest_version"] == "2.0.0"


def test_mcp_notice_once():
    _write_cache("3.0.0")
    first = u.mcp_update_notice(PKG, CUR)
    second = u.mcp_update_notice(PKG, CUR)
    assert first == f"{PKG} 3.0.0 available (you have {CUR}): uv tool upgrade {PKG}"
    assert second == ""


def test_stdout_untouched(monkeypatch):
    _write_cache("9.0.0")
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(u.sys, "stdout", out)
    monkeypatch.setattr(u.sys, "stderr", err)
    u.check_for_updates(PKG, CUR)
    assert out.getvalue() == ""
    assert err.getvalue()
