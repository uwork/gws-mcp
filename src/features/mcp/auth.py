"""MCP ツール実行時のユーザーコンテキスト管理。

リクエストごとに ContextVar で user_id を保持する。
ASGI ミドルウェアが Bearer トークンを検証し set_user_id() を呼ぶ。
"""

from contextvars import ContextVar

_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def set_user_id(user_id: str) -> None:
    """リクエストスコープの user_id を設定する。"""
    _user_id_var.set(user_id)


def get_current_user_id() -> str | None:
    """現在のリクエストに紐付いた user_id を返す。未認証なら None。"""
    return _user_id_var.get()
