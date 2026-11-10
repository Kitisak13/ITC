import pandas as pd
import pytest

from comtrade_pipeline import api_utils, config
from comtrade_pipeline.api_utils import chunk_list, safe_api_call, warn_if_truncated
from comtrade_pipeline.tariffline import parse_country_args


def test_chunk_list():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert chunk_list([], 3) == []
    with pytest.raises(ValueError):
        chunk_list([1], 0)


def test_parse_country_args():
    assert parse_country_args("USA:842, Russia:643") == {"USA": "842", "Russia": "643"}
    assert parse_country_args("842,,643") == {"Country_842": "842", "Country_643": "643"}


def test_get_api_key_priority(monkeypatch):
    monkeypatch.setenv("COMTRADE_API_KEY", "envkey")
    assert config.get_api_key("explicit") == "explicit"
    assert config.get_api_key() == "envkey"
    monkeypatch.setenv("COMTRADE_API_KEY", "your_subscription_key_here")
    with pytest.raises(config.ConfigError):
        config.get_api_key()
    monkeypatch.delenv("COMTRADE_API_KEY")
    with pytest.raises(config.ConfigError):
        config.get_api_key()


def test_mask_key():
    assert "secret" not in config.mask_key("secretsecretsecret")
    assert config.mask_key("abc") == "***"


def test_warn_if_truncated():
    assert warn_if_truncated(pd.DataFrame({"a": range(5)}), 5) is True
    assert warn_if_truncated(pd.DataFrame({"a": range(4)}), 5) is False
    assert warn_if_truncated(None, 5) is False


def test_safe_api_call_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(api_utils.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("network down")
        return "ok"

    assert safe_api_call(flaky) == "ok"
    assert calls["n"] == 3


def test_safe_api_call_fails_fast_on_401(monkeypatch):
    monkeypatch.setattr(api_utils.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def unauthorized():
        calls["n"] += 1
        raise RuntimeError("401 Unauthorized")

    with pytest.raises(RuntimeError):
        safe_api_call(unauthorized)
    assert calls["n"] == 1

