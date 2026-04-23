"""Google OAuth ヘルパー: 認可URL生成・トークン交換・リフレッシュ。"""

import base64
import json
import time

import httpx

from config import (
    ALLOWED_GOOGLE_DOMAINS,
    GOOGLE_AUTH_URL,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_URL,
    OAUTH_REDIRECT_URI,
    SECRET_NAME_CLIENT_ID,
    SECRET_NAME_CLIENT_SECRET,
)
from features.oauth.secret import get_secret
from features.oauth.storage import load_tokens, save_tokens


def build_google_auth_url(state: str) -> str:
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    params = {
        "client_id": client_id,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if ALLOWED_GOOGLE_DOMAINS:
        # 1ドメインの場合はそのドメインをヒントとして渡す（UI絞り込み）。
        # 複数の場合は "*" で任意のWorkspaceドメインを示す。
        params["hd"] = next(iter(ALLOWED_GOOGLE_DOMAINS)) if len(ALLOWED_GOOGLE_DOMAINS) == 1 else "*"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


def extract_email_from_id_token(id_token: str) -> str | None:
    """ID トークン（JWT）のペイロードからメールアドレスを取得する。
    Google のトークンエンドポイントから HTTPS で直接受け取るため署名検証は省略。
    """
    try:
        payload_b64 = id_token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("email")
    except Exception:
        return None


async def exchange_code_for_tokens(code: str) -> dict:
    """Google OAuth 認可コードをトークンと交換する。"""
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    client_secret = get_secret(SECRET_NAME_CLIENT_SECRET)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """リフレッシュトークンで新しいアクセストークンを取得する。"""
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    client_secret = get_secret(SECRET_NAME_CLIENT_SECRET)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_valid_access_token(user_id: str) -> str | None:
    """
    Firestore から有効なアクセストークンを返す。
    期限切れの場合はリフレッシュトークンで更新する。
    """
    tokens = load_tokens(user_id)
    if tokens is None:
        return None

    if tokens.get("expiry", 0) > time.time() + 60:
        return tokens["access_token"]

    if "refresh_token" not in tokens:
        return None
    refreshed = await refresh_access_token(tokens["refresh_token"])
    updated = {
        **tokens,
        "access_token": refreshed["access_token"],
        "expiry": time.time() + refreshed.get("expires_in", 3600),
    }
    if "refresh_token" in refreshed:
        updated["refresh_token"] = refreshed["refresh_token"]
    save_tokens(user_id, updated)
    return updated["access_token"]
