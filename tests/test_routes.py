"""features/oauth/routes.py の HTTP エンドポイント統合テスト。

TestClient は Starlette の ASGI テストクライアント。
外部依存はすべて monkeypatch / mocker で差し替える。
"""

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import TEST_REDIRECT_URI
from features.oauth import routes as oauth_routes
from features.oauth.state import create_state, verify_state


# ---------------------------------------------------------------------------
# /.well-known/oauth-protected-resource
# ---------------------------------------------------------------------------


def test_protected_resource_returns_200(client):
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200


def test_protected_resource_json_keys(client):
    body = client.get("/.well-known/oauth-protected-resource").json()
    assert "resource" in body
    assert "authorization_servers" in body


def test_protected_resource_authorization_servers_is_list(client):
    body = client.get("/.well-known/oauth-protected-resource").json()
    assert isinstance(body["authorization_servers"], list)


def test_protected_resource_uses_service_host(client):
    oauth_routes.SERVICE_HOST = "prod.example.com"
    body = client.get("/.well-known/oauth-protected-resource").json()
    assert body["resource"] == "https://prod.example.com"
    assert body["authorization_servers"] == ["https://prod.example.com"]


def test_protected_resource_uses_forwarded_proto(client):
    r = client.get(
        "/.well-known/oauth-protected-resource",
        headers={"X-Forwarded-Proto": "https"},
    )
    body = r.json()
    assert body["resource"].startswith("https://")


# ---------------------------------------------------------------------------
# /.well-known/oauth-authorization-server
# ---------------------------------------------------------------------------


def test_well_known_returns_200(client):
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200


def test_well_known_required_fields(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert key in body, f"missing key: {key}"


def test_well_known_s256_in_code_challenge_methods(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert "S256" in body["code_challenge_methods_supported"]


def test_well_known_authorization_code_in_grant_types(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert "authorization_code" in body["grant_types_supported"]


def test_well_known_endpoints_contain_base_url(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------


def test_register_returns_201(client):
    r = client.post("/register", json={})
    assert r.status_code == 201


def test_register_issues_client_id(client):
    body = client.post("/register", json={}).json()
    assert "client_id" in body
    assert isinstance(body["client_id"], str)
    assert len(body["client_id"]) > 0


def test_register_client_id_is_unique(client):
    id1 = client.post("/register", json={}).json()["client_id"]
    id2 = client.post("/register", json={}).json()["client_id"]
    assert id1 != id2


def test_register_token_endpoint_auth_method_is_none(client):
    body = client.post("/register", json={}).json()
    assert body["token_endpoint_auth_method"] == "none"


def test_register_default_grant_types(client):
    body = client.post("/register", json={}).json()
    assert "authorization_code" in body["grant_types"]
    assert "refresh_token" in body["grant_types"]


def test_register_default_response_types(client):
    body = client.post("/register", json={}).json()
    assert "code" in body["response_types"]


def test_register_echoes_redirect_uris(client):
    uris = ["https://example.com/callback"]
    body = client.post("/register", json={"redirect_uris": uris}).json()
    assert body["redirect_uris"] == uris


def test_register_echoes_client_name(client):
    body = client.post("/register", json={"client_name": "My App"}).json()
    assert body["client_name"] == "My App"


def test_register_echoes_scope(client):
    body = client.post("/register", json={"scope": "openid email"}).json()
    assert body["scope"] == "openid email"


def test_register_no_client_secret_in_response(client):
    body = client.post("/register", json={}).json()
    assert "client_secret" not in body


def test_register_invalid_json_returns_400(client):
    r = client.post(
        "/register",
        content=b"{bad json}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# GET /authorize
# ---------------------------------------------------------------------------

_VALID_AUTHORIZE_PARAMS = {
    "response_type": "code",
    "client_id": "client-123",
    "redirect_uri": TEST_REDIRECT_URI,
    "code_challenge": "abc123",
    "code_challenge_method": "S256",
    "state": "my-state",
}


def test_authorize_redirects_to_google(client, mocker):
    mocker.patch.object(
        oauth_routes,
        "build_google_auth_url",
        return_value="https://accounts.google.com/auth?state=x",
    )
    r = client.get("/authorize", params=_VALID_AUTHORIZE_PARAMS)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]


def test_authorize_build_google_auth_url_called(client, mocker):
    mock_build = mocker.patch.object(
        oauth_routes,
        "build_google_auth_url",
        return_value="https://accounts.google.com/auth?state=x",
    )
    client.get("/authorize", params=_VALID_AUTHORIZE_PARAMS)
    mock_build.assert_called_once()


def test_authorize_missing_response_type_returns_400(client):
    params = {k: v for k, v in _VALID_AUTHORIZE_PARAMS.items() if k != "response_type"}
    r = client.get("/authorize", params=params)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_authorize_missing_client_id_returns_400(client):
    params = {k: v for k, v in _VALID_AUTHORIZE_PARAMS.items() if k != "client_id"}
    assert client.get("/authorize", params=params).status_code == 400


def test_authorize_missing_redirect_uri_returns_400(client):
    params = {k: v for k, v in _VALID_AUTHORIZE_PARAMS.items() if k != "redirect_uri"}
    assert client.get("/authorize", params=params).status_code == 400


def test_authorize_missing_code_challenge_returns_400(client):
    params = {k: v for k, v in _VALID_AUTHORIZE_PARAMS.items() if k != "code_challenge"}
    assert client.get("/authorize", params=params).status_code == 400


def test_authorize_non_s256_method_returns_400(client):
    params = {**_VALID_AUTHORIZE_PARAMS, "code_challenge_method": "plain"}
    r = client.get("/authorize", params=params)
    assert r.status_code == 400
    assert "S256" in r.json()["error_description"]


def test_authorize_unauthorized_redirect_uri_returns_400(client):
    params = {**_VALID_AUTHORIZE_PARAMS, "redirect_uri": "http://evil.com/steal"}
    r = client.get("/authorize", params=params)
    assert r.status_code == 400
    assert "redirect_uri" in r.json()["error_description"]


def test_authorize_default_s256_method_accepted(client, mocker):
    mocker.patch.object(
        oauth_routes,
        "build_google_auth_url",
        return_value="https://accounts.google.com/auth?state=x",
    )
    params = {k: v for k, v in _VALID_AUTHORIZE_PARAMS.items() if k != "code_challenge_method"}
    r = client.get("/authorize", params=params)
    assert r.status_code == 302


# ---------------------------------------------------------------------------
# GET /callback
# ---------------------------------------------------------------------------


def _mock_exchange_tokens(mocker, token_response: dict | None = None):
    resp = token_response or {
        "access_token": "google-access-token",
        "refresh_token": "google-refresh-token",
        "expires_in": 3600,
    }
    return mocker.patch.object(
        oauth_routes,
        "exchange_code_for_tokens",
        new=AsyncMock(return_value=resp),
    )


def test_callback_missing_code_returns_400(client, valid_google_state):
    r = client.get(f"/callback?state={valid_google_state}")
    assert r.status_code == 400


def test_callback_missing_state_returns_400(client):
    r = client.get("/callback?code=google-code")
    assert r.status_code == 400


def test_callback_error_param_returns_400(client):
    r = client.get("/callback?error=access_denied")
    assert r.status_code == 400
    assert "access_denied" in r.text


def test_callback_invalid_state_returns_400(client):
    r = client.get("/callback?code=google-code&state=garbage-state")
    assert r.status_code == 400


def test_callback_successful_flow_redirects(client, mocker, valid_google_state):
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker)
    r = client.get(f"/callback?code=google-code&state={valid_google_state}")
    assert r.status_code == 302


def test_callback_redirect_contains_mcp_code(client, mocker, valid_google_state):
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker)
    r = client.get(f"/callback?code=google-code&state={valid_google_state}")
    location = r.headers["location"]
    assert "code=" in location


def test_callback_redirect_preserves_mcp_state(client, mocker, valid_google_state):
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker)
    r = client.get(f"/callback?code=google-code&state={valid_google_state}")
    location = r.headers["location"]
    assert "state=original-mcp-state" in location


def test_callback_mcp_state_omitted_when_empty(client, mocker, pkce_pair):
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker)
    state_token = create_state(
        {
            "mcp_redirect_uri": TEST_REDIRECT_URI,
            "mcp_client_id": "client-123",
            "mcp_state": "",
            "code_challenge": pkce_pair["challenge"],
        }
    )
    r = client.get(f"/callback?code=google-code&state={state_token}")
    assert r.status_code == 302
    assert "&state=" not in r.headers["location"]


def test_callback_calls_save_tokens(client, mocker, valid_google_state):
    mock_save = mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker)
    client.get(f"/callback?code=google-code&state={valid_google_state}")
    mock_save.assert_called_once()


def test_callback_token_exchange_failure_returns_500(client, mocker, valid_google_state):
    import httpx

    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    mocker.patch.object(
        oauth_routes,
        "exchange_code_for_tokens",
        new=AsyncMock(
            side_effect=httpx.HTTPStatusError("fail", request=MagicMock(), response=MagicMock())
        ),
    )
    r = client.get(f"/callback?code=google-code&state={valid_google_state}")
    assert r.status_code == 500


def test_callback_domain_restriction_allowed_domain(client, mocker, pkce_pair, make_jwt):
    oauth_routes.ALLOWED_GOOGLE_DOMAINS = frozenset({"example.com"})
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    id_token = make_jwt("user@example.com")
    _mock_exchange_tokens(
        mocker,
        {"access_token": "gat", "refresh_token": "grt", "expires_in": 3600, "id_token": id_token},
    )
    state_token = create_state(
        {
            "mcp_redirect_uri": TEST_REDIRECT_URI,
            "mcp_client_id": "client-123",
            "mcp_state": "",
            "code_challenge": pkce_pair["challenge"],
        }
    )
    r = client.get(f"/callback?code=google-code&state={state_token}")
    assert r.status_code == 302


def test_callback_domain_restriction_blocked_domain(client, mocker, pkce_pair, make_jwt):
    oauth_routes.ALLOWED_GOOGLE_DOMAINS = frozenset({"example.com"})
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    id_token = make_jwt("user@other.com")
    _mock_exchange_tokens(
        mocker,
        {"access_token": "gat", "refresh_token": "grt", "expires_in": 3600, "id_token": id_token},
    )
    state_token = create_state(
        {
            "mcp_redirect_uri": TEST_REDIRECT_URI,
            "mcp_client_id": "client-123",
            "mcp_state": "",
            "code_challenge": pkce_pair["challenge"],
        }
    )
    r = client.get(f"/callback?code=google-code&state={state_token}")
    assert r.status_code == 403


def test_callback_domain_restriction_no_id_token_returns_403(client, mocker, pkce_pair):
    oauth_routes.ALLOWED_GOOGLE_DOMAINS = frozenset({"example.com"})
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(
        mocker,
        {"access_token": "gat", "refresh_token": "grt", "expires_in": 3600},
    )
    state_token = create_state(
        {
            "mcp_redirect_uri": TEST_REDIRECT_URI,
            "mcp_client_id": "client-123",
            "mcp_state": "",
            "code_challenge": pkce_pair["challenge"],
        }
    )
    r = client.get(f"/callback?code=google-code&state={state_token}")
    assert r.status_code == 403


def test_callback_no_domain_restriction_skips_id_token_check(client, mocker, valid_google_state):
    # ALLOWED_GOOGLE_DOMAINS が空（デフォルト）ならドメインチェックしない
    mocker.patch.object(oauth_routes, "save_tokens", MagicMock())
    _mock_exchange_tokens(mocker, {"access_token": "gat", "expires_in": 3600})
    r = client.get(f"/callback?code=google-code&state={valid_google_state}")
    assert r.status_code == 302


def test_callback_user_id_is_deterministic(client, mocker, pkce_pair):
    """同じ code_challenge から生成される user_id は一定。"""
    saved_calls = []

    def capture_save(user_id, tokens):
        saved_calls.append(user_id)

    mocker.patch.object(oauth_routes, "save_tokens", side_effect=capture_save)
    _mock_exchange_tokens(mocker)

    for _ in range(2):
        state_token = create_state(
            {
                "mcp_redirect_uri": TEST_REDIRECT_URI,
                "mcp_client_id": "client-123",
                "mcp_state": "",
                "code_challenge": pkce_pair["challenge"],
            }
        )
        client.get(f"/callback?code=google-code&state={state_token}")

    assert saved_calls[0] == saved_calls[1]


# ---------------------------------------------------------------------------
# GET /token
# ---------------------------------------------------------------------------


def test_token_get_returns_200(client):
    assert client.get("/token").status_code == 200


def test_token_get_health_check_response(client):
    assert client.get("/token").json() == {"token_endpoint": "ready"}


# ---------------------------------------------------------------------------
# POST /token — authorization_code グラント
# ---------------------------------------------------------------------------


def _make_mcp_code(pkce_pair: dict, user_id: str = "user-abc") -> str:
    return create_state({"user_id": user_id, "code_challenge": pkce_pair["challenge"]})


def test_token_auth_code_success_form(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair)
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": mcp_code,
            "code_verifier": pkce_pair["verifier"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600


def test_token_auth_code_token_type_is_bearer(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair)
    body = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": mcp_code,
            "code_verifier": pkce_pair["verifier"],
        },
    ).json()
    assert body["token_type"] == "Bearer"


def test_token_auth_code_access_token_contains_user_id(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair, user_id="test-user-999")
    body = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": mcp_code,
            "code_verifier": pkce_pair["verifier"],
        },
    ).json()
    token_data = verify_state(body["access_token"], max_age=3600)
    assert token_data is not None
    assert token_data["user_id"] == "test-user-999"


def test_token_auth_code_success_json_body(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair)
    r = client.post(
        "/token",
        json={
            "grant_type": "authorization_code",
            "code": mcp_code,
            "code_verifier": pkce_pair["verifier"],
        },
    )
    assert r.status_code == 200


def test_token_auth_code_missing_code_returns_400(client, pkce_pair):
    r = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code_verifier": pkce_pair["verifier"]},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_token_auth_code_missing_verifier_returns_400(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair)
    r = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": mcp_code},
    )
    assert r.status_code == 400


def test_token_auth_code_invalid_code_returns_400(client, pkce_pair):
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": "garbage-invalid-code",
            "code_verifier": pkce_pair["verifier"],
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_token_auth_code_wrong_verifier_returns_400(client, pkce_pair):
    mcp_code = _make_mcp_code(pkce_pair)
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": mcp_code,
            "code_verifier": "wrong-verifier-string",
        },
    )
    assert r.status_code == 400
    assert "PKCE" in r.json()["error_description"]


def test_token_invalid_json_body_returns_400(client):
    r = client.post(
        "/token",
        content=b"{bad json}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /token — refresh_token グラント
# ---------------------------------------------------------------------------


def _make_refresh_token(user_id: str = "user-abc") -> str:
    import time

    return create_state({"user_id": user_id, "issued_at": time.time()})


def test_token_refresh_success(client):
    refresh = _make_refresh_token()
    r = client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "Bearer"


def test_token_refresh_new_token_contains_same_user_id(client):
    refresh = _make_refresh_token(user_id="user-xyz")
    body = client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh},
    ).json()
    token_data = verify_state(body["access_token"], max_age=3600)
    assert token_data["user_id"] == "user-xyz"


def test_token_refresh_missing_token_returns_400(client):
    r = client.post("/token", data={"grant_type": "refresh_token"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_token_refresh_invalid_token_returns_400(client):
    r = client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": "garbage"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# POST /token — 未対応の grant_type
# ---------------------------------------------------------------------------


def test_token_unsupported_grant_type_returns_400(client):
    r = client.post("/token", data={"grant_type": "client_credentials"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_token_missing_grant_type_returns_400(client):
    r = client.post("/token", data={"code": "abc"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"
