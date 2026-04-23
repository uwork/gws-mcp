"""features/oauth/google.py の単体テスト。

HTTP 呼び出しはすべて unittest.mock で差し替える。
非同期関数は pytest-anyio ではなく anyio.pytest_plugin の @pytest.mark.anyio を使う。
"""

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from features.oauth import google as google_module
from features.oauth.google import (
    build_google_auth_url,
    exchange_code_for_tokens,
    extract_email_from_id_token,
    get_valid_access_token,
    refresh_access_token,
)


# ---------------------------------------------------------------------------
# extract_email_from_id_token — 純粋関数
# ---------------------------------------------------------------------------


def _make_id_token(email: str, email_verified: bool = True, extra: dict | None = None) -> str:
    payload = {"email": email, "email_verified": email_verified, **(extra or {})}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{b64}.fakesig"


def test_extract_email_valid():
    token = _make_id_token("user@example.com")
    assert extract_email_from_id_token(token) == "user@example.com"


def test_extract_email_unverified_returns_none():
    token = _make_id_token("user@example.com", email_verified=False)
    assert extract_email_from_id_token(token) is None


def test_extract_email_missing_verified_flag_returns_none():
    payload = {"email": "user@example.com"}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    token = f"header.{b64}.sig"
    assert extract_email_from_id_token(token) is None


def test_extract_email_missing_email_field_returns_none():
    payload = {"email_verified": True}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    token = f"header.{b64}.sig"
    assert extract_email_from_id_token(token) is None


def test_extract_email_malformed_jwt_returns_none():
    assert extract_email_from_id_token("not-a-jwt") is None


def test_extract_email_invalid_base64_returns_none():
    assert extract_email_from_id_token("hdr.!!!invalid!!!.sig") is None


def test_extract_email_non_json_payload_returns_none():
    b64 = base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode()
    assert extract_email_from_id_token(f"hdr.{b64}.sig") is None


# ---------------------------------------------------------------------------
# build_google_auth_url
# ---------------------------------------------------------------------------


def _mock_get_secret(name: str) -> str:
    return "test-client-id" if "client-id" in name else "test-client-secret"


def test_build_google_auth_url_contains_client_id(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    url = build_google_auth_url("my-state")
    assert "test-client-id" in url


def test_build_google_auth_url_contains_state(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    url = build_google_auth_url("my-state")
    assert "my-state" in url


def test_build_google_auth_url_has_offline_access(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    url = build_google_auth_url("s")
    assert "access_type=offline" in url


def test_build_google_auth_url_single_domain_adds_hd(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch.object(google_module, "ALLOWED_GOOGLE_DOMAINS", frozenset({"corp.com"}))
    url = build_google_auth_url("s")
    assert "hd=corp.com" in url


def test_build_google_auth_url_multi_domain_adds_wildcard_hd(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch.object(
        google_module, "ALLOWED_GOOGLE_DOMAINS", frozenset({"a.com", "b.com"})
    )
    url = build_google_auth_url("s")
    assert "hd=*" in url


def test_build_google_auth_url_no_domain_restriction_omits_hd(mocker):
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch.object(google_module, "ALLOWED_GOOGLE_DOMAINS", frozenset())
    url = build_google_auth_url("s")
    assert "hd=" not in url


# ---------------------------------------------------------------------------
# exchange_code_for_tokens — 非同期
# ---------------------------------------------------------------------------


def _make_httpx_mock(response_json: dict) -> MagicMock:
    """httpx.AsyncClient のコンテキストマネージャモックを生成する。"""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.anyio
async def test_exchange_code_for_tokens_returns_dict(mocker):
    expected = {"access_token": "gat", "refresh_token": "grt", "expires_in": 3600}
    mock_client = _make_httpx_mock(expected)
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await exchange_code_for_tokens("auth-code")
    assert result == expected


@pytest.mark.anyio
async def test_exchange_code_for_tokens_posts_to_google(mocker):
    mock_client = _make_httpx_mock({"access_token": "t"})
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await exchange_code_for_tokens("my-code")
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args
    posted_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
    assert "my-code" in str(posted_data) or any("my-code" in str(v) for v in posted_data.values())


@pytest.mark.anyio
async def test_exchange_code_for_tokens_raises_on_http_error(mocker):
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "error", request=MagicMock(), response=MagicMock()
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code_for_tokens("code")


# ---------------------------------------------------------------------------
# refresh_access_token — 非同期
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_access_token_returns_new_token(mocker):
    expected = {"access_token": "new-gat", "expires_in": 3600}
    mock_client = _make_httpx_mock(expected)
    mocker.patch.object(google_module, "get_secret", side_effect=_mock_get_secret)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await refresh_access_token("old-refresh-token")
    assert result == expected


# ---------------------------------------------------------------------------
# get_valid_access_token — 非同期
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_valid_access_token_returns_none_when_no_tokens(mocker):
    mocker.patch.object(google_module, "load_tokens", return_value=None)
    assert await get_valid_access_token("user-x") is None


@pytest.mark.anyio
async def test_get_valid_access_token_returns_cached_fresh_token(mocker):
    tokens = {
        "access_token": "fresh-token",
        "refresh_token": "rt",
        "expiry": time.time() + 3600,
    }
    mocker.patch.object(google_module, "load_tokens", return_value=tokens)
    result = await get_valid_access_token("user-x")
    assert result == "fresh-token"


@pytest.mark.anyio
async def test_get_valid_access_token_does_not_refresh_when_fresh(mocker):
    tokens = {"access_token": "fresh", "refresh_token": "rt", "expiry": time.time() + 3600}
    mocker.patch.object(google_module, "load_tokens", return_value=tokens)
    mock_refresh = mocker.patch.object(
        google_module, "refresh_access_token", new=AsyncMock()
    )
    await get_valid_access_token("user-x")
    mock_refresh.assert_not_awaited()


@pytest.mark.anyio
async def test_get_valid_access_token_refreshes_when_expired(mocker):
    tokens = {
        "access_token": "old-token",
        "refresh_token": "rt",
        "expiry": time.time() - 100,  # 期限切れ
    }
    refreshed = {"access_token": "new-token", "expires_in": 3600}
    mocker.patch.object(google_module, "load_tokens", return_value=tokens)
    mocker.patch.object(
        google_module, "refresh_access_token", new=AsyncMock(return_value=refreshed)
    )
    mock_save = mocker.patch.object(google_module, "save_tokens", MagicMock())
    result = await get_valid_access_token("user-x")
    assert result == "new-token"
    mock_save.assert_called_once()


@pytest.mark.anyio
async def test_get_valid_access_token_returns_none_when_no_refresh_token(mocker):
    tokens = {
        "access_token": "old-token",
        "expiry": time.time() - 100,
    }
    mocker.patch.object(google_module, "load_tokens", return_value=tokens)
    assert await get_valid_access_token("user-x") is None


@pytest.mark.anyio
async def test_get_valid_access_token_saves_new_refresh_token(mocker):
    tokens = {
        "access_token": "old",
        "refresh_token": "old-rt",
        "expiry": time.time() - 100,
    }
    refreshed = {"access_token": "new", "refresh_token": "new-rt", "expires_in": 3600}
    mocker.patch.object(google_module, "load_tokens", return_value=tokens)
    mocker.patch.object(
        google_module, "refresh_access_token", new=AsyncMock(return_value=refreshed)
    )
    mock_save = mocker.patch.object(google_module, "save_tokens", MagicMock())
    await get_valid_access_token("user-x")
    saved_tokens = mock_save.call_args[0][1]
    assert saved_tokens["refresh_token"] == "new-rt"
