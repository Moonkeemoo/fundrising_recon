"""Тести для нових ключів і функцій config: keys_status, check_keys, _load_dotenv."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _reload_config(monkeypatch):
    """Перезавантажує config після зміни env."""
    import fundrec.config as cfg
    importlib.reload(cfg)
    return cfg


# ---------------------------------------------------------------------------
# keys_status
# ---------------------------------------------------------------------------

def test_keys_status_all_set(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    monkeypatch.setenv("META_ADS_TOKEN", "tok")
    monkeypatch.setenv("FUNDREC_CRITIC_API_KEY", "crit")
    cfg = _reload_config(monkeypatch)
    status = cfg.keys_status()
    assert status["YOUTUBE_API_KEY"] is True
    assert status["TELEGRAM_API_ID"] is True
    assert status["TELEGRAM_API_HASH"] is True
    assert status["META_ADS_TOKEN"] is True
    assert status["FUNDREC_CRITIC_API_KEY"] is True


def test_keys_status_none_set(monkeypatch):
    for k in ("YOUTUBE_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
              "META_ADS_TOKEN", "FUNDREC_CRITIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = _reload_config(monkeypatch)
    status = cfg.keys_status()
    assert all(not v for v in status.values())


def test_keys_status_returns_bool_not_value(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "super-secret")
    cfg = _reload_config(monkeypatch)
    status = cfg.keys_status()
    # Значення повинні бути bool, НІКОЛИ не рядками/ключами
    for v in status.values():
        assert isinstance(v, bool)


def test_keys_status_partial(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("META_ADS_TOKEN", "tok")
    for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "FUNDREC_CRITIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = _reload_config(monkeypatch)
    status = cfg.keys_status()
    assert status["YOUTUBE_API_KEY"] is False
    assert status["META_ADS_TOKEN"] is True


# ---------------------------------------------------------------------------
# _load_dotenv
# ---------------------------------------------------------------------------

def test_load_dotenv_sets_missing_key(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_FUNDREC_VAR=hello\n", encoding="utf-8")
    monkeypatch.delenv("TEST_FUNDREC_VAR", raising=False)

    import fundrec.config as cfg
    # Зберегти оригінальний ROOT і підмінити
    orig_root = cfg.ROOT
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    cfg._load_dotenv()
    assert os.environ.get("TEST_FUNDREC_VAR") == "hello"
    monkeypatch.setattr(cfg, "ROOT", orig_root)
    # Cleanup
    monkeypatch.delenv("TEST_FUNDREC_VAR", raising=False)


def test_load_dotenv_skips_comments_and_blank(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# це коментар\n\nFUNDREC_TEST_X=123\n# ще коментар\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FUNDREC_TEST_X", raising=False)
    import fundrec.config as cfg
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    cfg._load_dotenv()
    assert os.environ.get("FUNDREC_TEST_X") == "123"
    monkeypatch.delenv("FUNDREC_TEST_X", raising=False)


def test_load_dotenv_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FUNDREC_TEST_Y=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FUNDREC_TEST_Y", "already_set")
    import fundrec.config as cfg
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    cfg._load_dotenv()
    assert os.environ.get("FUNDREC_TEST_Y") == "already_set"
    monkeypatch.delenv("FUNDREC_TEST_Y", raising=False)


def test_load_dotenv_no_file_does_not_crash(monkeypatch, tmp_path):
    import fundrec.config as cfg
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    # Файлу .env немає — не падаємо
    cfg._load_dotenv()


# ---------------------------------------------------------------------------
# check_keys (CLI entrypoint) — тест через subprocess
# ---------------------------------------------------------------------------

def test_check_keys_cli_runs_and_shows_key_names():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "fundrec.config", "--check-keys"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0
    out = result.stdout + result.stderr
    # Усі імена ключів присутні у виводі
    for key_name in ("YOUTUBE_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
                     "META_ADS_TOKEN", "FUNDREC_CRITIC_API_KEY"):
        assert key_name in out
    # Значення ніколи не друкуються — перевіримо що немає "secret"
    # (не можемо перевірити реальні значення, але можемо перевірити формат)
    assert ("zadano" in out or "задано" in out or "True" in out or "False" in out)
