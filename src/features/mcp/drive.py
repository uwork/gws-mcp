"""Google Drive API クライアントおよび MCP ツール定義。

各ツールは AI が扱いやすいフラットな dict を返す。
Google API のネスト構造・camelCase キーを整形して返す。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from features.mcp.auth import get_current_user_id
from features.mcp.instance import mcp
from features.oauth.google import get_valid_access_token

logger = logging.getLogger(__name__)

_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_FILE_FIELDS = "id,name,mimeType,parents,createdTime,modifiedTime,size,webViewLink,iconLink,trashed"


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


async def _get_token() -> str:
    user_id = get_current_user_id()
    if user_id is None:
        raise PermissionError("認証が必要です。先に OAuth 認証を完了してください。")
    token = await get_valid_access_token(user_id)
    if token is None:
        raise PermissionError("アクセストークンの取得に失敗しました。再認証してください。")
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _raise_for_error(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    raise httpx.HTTPStatusError(
        f"{resp.status_code} {resp.reason_phrase}: {detail}",
        request=resp.request,
        response=resp,
    )


async def _drive_get_json(path: str, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DRIVE_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()


async def _drive_post(path: str, body: dict, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_DRIVE_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            params=params or {},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()


async def _drive_patch(path: str, body: dict | None = None, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_DRIVE_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body or {},
            params=params or {},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()


async def _drive_delete(path: str, params: dict | None = None) -> None:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{_DRIVE_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        _raise_for_error(resp)


def _escape_query_value(value: str) -> str:
    """Drive API の q パラメータに埋め込む文字列をエスケープする。"""
    return value.replace("\\", "\\\\").replace("'", "\\'")


_PERMISSION_FIELDS = (
    "id,type,role,emailAddress,domain,displayName,allowFileDiscovery,expirationTime,deleted"
)
_VALID_PERMISSION_TYPES = {"user", "group", "domain", "anyone"}
_VALID_PERMISSION_ROLES = {
    "owner",
    "organizer",
    "fileOrganizer",
    "writer",
    "commenter",
    "reader",
}


# ---------------------------------------------------------------------------
# AI フレンドリー変換ヘルパー
# ---------------------------------------------------------------------------


def _format_file(raw: dict) -> dict[str, Any]:
    """Drive API の File リソースを AI フレンドリーな dict に変換する。"""
    mime_type = raw.get("mimeType", "")
    result: dict[str, Any] = {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "mime_type": mime_type,
        "is_folder": mime_type == _FOLDER_MIME_TYPE,
        "parents": raw.get("parents", []),
        "created_time": raw.get("createdTime", ""),
        "modified_time": raw.get("modifiedTime", ""),
        "web_view_link": raw.get("webViewLink", ""),
        "icon_link": raw.get("iconLink", ""),
        "trashed": raw.get("trashed", False),
    }
    if "size" in raw:
        result["size_bytes"] = int(raw["size"])
    return result


def _format_permission(raw: dict) -> dict[str, Any]:
    """Drive API の Permission リソースを AI フレンドリーな dict に変換する。"""
    result: dict[str, Any] = {
        "id": raw.get("id", ""),
        "type": raw.get("type", ""),
        "role": raw.get("role", ""),
    }
    if "emailAddress" in raw:
        result["email_address"] = raw["emailAddress"]
    if "domain" in raw:
        result["domain"] = raw["domain"]
    if "displayName" in raw:
        result["display_name"] = raw["displayName"]
    if "allowFileDiscovery" in raw:
        result["allow_file_discovery"] = raw["allowFileDiscovery"]
    if "expirationTime" in raw:
        result["expiration_time"] = raw["expirationTime"]
    if "deleted" in raw:
        result["deleted"] = raw["deleted"]
    return result


# ---------------------------------------------------------------------------
# MCP ツール定義
# ---------------------------------------------------------------------------


@mcp.tool()
async def drive_list_files(
    folder_id: str | None = None,
    query: str | None = None,
    only_folders: bool = False,
    page_size: int = 100,
    page_token: str | None = None,
) -> dict:
    """Drive 内のファイル／フォルダを一覧・検索する。

    Args:
        folder_id: 指定した場合、このフォルダ直下のアイテムのみを返す
        query: 指定した場合、名前にこの文字列を含むアイテムのみを返す（部分一致）
        only_folders: True の場合、フォルダのみを返す
        page_size: 1 ページあたりの件数（デフォルト 100、最大 1000）
        page_token: 前回のレスポンスの next_page_token を渡すと続きを取得できる

    Returns:
        {
            files: [{
                id, name, mime_type, is_folder, parents,
                created_time, modified_time, size_bytes?,
                web_view_link, icon_link, trashed
            }, ...],
            file_count,
            next_page_token  # さらに結果がある場合のみ
        }

    Note:
        ゴミ箱に入っているアイテムは既定で除外される。
    """
    conditions = ["trashed = false"]
    if folder_id:
        conditions.append(f"'{_escape_query_value(folder_id)}' in parents")
    if query:
        conditions.append(f"name contains '{_escape_query_value(query)}'")
    if only_folders:
        conditions.append(f"mimeType = '{_FOLDER_MIME_TYPE}'")

    params: dict[str, Any] = {
        "q": " and ".join(conditions),
        "fields": f"nextPageToken, files({_FILE_FIELDS})",
        "pageSize": page_size,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if page_token:
        params["pageToken"] = page_token

    raw = await _drive_get_json("/files", params=params)
    files = [_format_file(f) for f in raw.get("files", [])]
    result: dict[str, Any] = {"files": files, "file_count": len(files)}
    next_page_token = raw.get("nextPageToken")
    if next_page_token:
        result["next_page_token"] = next_page_token
    return result


@mcp.tool()
async def drive_get_file(file_id: str) -> dict:
    """ファイル／フォルダのメタデータを取得する。

    Args:
        file_id: ファイル ID またはフォルダ ID

    Returns:
        { id, name, mime_type, is_folder, parents, created_time,
          modified_time, size_bytes?, web_view_link, icon_link, trashed }
    """
    raw = await _drive_get_json(
        f"/files/{file_id}",
        params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
    )
    return _format_file(raw)


@mcp.tool()
async def drive_create_folder(name: str, parent_id: str | None = None) -> dict:
    """新しいフォルダを作成する。

    Args:
        name: フォルダ名
        parent_id: 親フォルダ ID。省略時はマイドライブのルートに作成される

    Returns:
        { id, name, mime_type, is_folder, parents, created_time,
          modified_time, web_view_link, icon_link, trashed }
    """
    body: dict[str, Any] = {"name": name, "mimeType": _FOLDER_MIME_TYPE}
    if parent_id:
        body["parents"] = [parent_id]
    raw = await _drive_post(
        "/files",
        body,
        params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
    )
    return _format_file(raw)


@mcp.tool()
async def drive_rename_file(file_id: str, new_name: str) -> dict:
    """ファイル／フォルダの名前を変更する。

    Args:
        file_id: ファイル ID またはフォルダ ID
        new_name: 新しい名前

    Returns:
        { id, name, mime_type, is_folder, parents, created_time,
          modified_time, size_bytes?, web_view_link, icon_link, trashed }
    """
    raw = await _drive_patch(
        f"/files/{file_id}",
        {"name": new_name},
        params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
    )
    return _format_file(raw)


@mcp.tool()
async def drive_move_file(
    file_id: str,
    new_parent_id: str,
    old_parent_id: str | None = None,
) -> dict:
    """ファイル／フォルダを別のフォルダに移動する。

    Args:
        file_id: 移動するファイル ID またはフォルダ ID
        new_parent_id: 移動先の親フォルダ ID
        old_parent_id: 現在の親フォルダ ID。省略時は現在の親をすべて自動的に取り除く

    Returns:
        { id, name, mime_type, is_folder, parents, created_time,
          modified_time, size_bytes?, web_view_link, icon_link, trashed }
    """
    if old_parent_id:
        remove_parents = old_parent_id
    else:
        current = await _drive_get_json(
            f"/files/{file_id}",
            params={"fields": "parents", "supportsAllDrives": "true"},
        )
        remove_parents = ",".join(current.get("parents", []))

    params: dict[str, Any] = {
        "addParents": new_parent_id,
        "fields": _FILE_FIELDS,
        "supportsAllDrives": "true",
    }
    if remove_parents:
        params["removeParents"] = remove_parents

    raw = await _drive_patch(f"/files/{file_id}", params=params)
    return _format_file(raw)


@mcp.tool()
async def drive_copy_file(
    file_id: str,
    new_name: str | None = None,
    parent_id: str | None = None,
) -> dict:
    """ファイルをコピーする。

    Args:
        file_id: コピー元のファイル ID
        new_name: コピー後の名前。省略時は Google が自動生成する名前になる
        parent_id: コピー先の親フォルダ ID。省略時は元のファイルと同じ場所にコピーされる

    Returns:
        { id, name, mime_type, is_folder, parents, created_time,
          modified_time, size_bytes?, web_view_link, icon_link, trashed }

    Note:
        Drive API はフォルダそのもののコピーをサポートしない。対象はファイルのみ。
    """
    body: dict[str, Any] = {}
    if new_name:
        body["name"] = new_name
    if parent_id:
        body["parents"] = [parent_id]
    raw = await _drive_post(
        f"/files/{file_id}/copy",
        body,
        params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
    )
    return _format_file(raw)


@mcp.tool()
async def drive_list_permissions(file_id: str) -> dict:
    """ファイル／フォルダの共有設定（権限一覧）を取得する。

    Args:
        file_id: ファイル ID またはフォルダ ID

    Returns:
        {
            permissions: [{
                id, type, role, email_address?, domain?,
                display_name?, allow_file_discovery?, expiration_time?, deleted?
            }, ...],
            permission_count
        }
    """
    raw = await _drive_get_json(
        f"/files/{file_id}/permissions",
        params={
            "fields": f"permissions({_PERMISSION_FIELDS})",
            "supportsAllDrives": "true",
        },
    )
    permissions = [_format_permission(p) for p in raw.get("permissions", [])]
    return {"permissions": permissions, "permission_count": len(permissions)}


@mcp.tool()
async def drive_share_file(
    file_id: str,
    role: str,
    share_type: str = "user",
    email_address: str | None = None,
    domain: str | None = None,
    allow_file_discovery: bool | None = None,
    send_notification_email: bool = True,
    message: str | None = None,
) -> dict:
    """ファイル／フォルダを共有する（新しい権限を追加する）。

    Args:
        role: 付与する権限。"owner" | "organizer" | "fileOrganizer" | "writer" |
            "commenter" | "reader"
        share_type: 共有対象の種類。"user"（既定）| "group" | "domain" | "anyone"
        email_address: share_type が "user" または "group" の場合に必須。共有先のメールアドレス
        domain: share_type が "domain" の場合に必須。共有先のドメイン名
        allow_file_discovery: share_type が "domain" または "anyone" の場合、検索での
            発見を許可するかどうか
        send_notification_email: share_type が "user"／"group" の場合に通知メールを送るかどうか
        message: 通知メールに含めるメッセージ（send_notification_email が True の場合のみ有効）

    Returns:
        { id, type, role, email_address?, domain?, display_name?,
          allow_file_discovery?, expiration_time?, deleted? }
    """
    if share_type not in _VALID_PERMISSION_TYPES:
        raise ValueError(
            f"無効な share_type です: {share_type!r}。有効な値: {sorted(_VALID_PERMISSION_TYPES)}"
        )
    if role not in _VALID_PERMISSION_ROLES:
        raise ValueError(f"無効な role です: {role!r}。有効な値: {sorted(_VALID_PERMISSION_ROLES)}")
    if share_type in ("user", "group") and not email_address:
        raise ValueError(f"share_type={share_type!r} の場合 email_address は必須です")
    if share_type == "domain" and not domain:
        raise ValueError("share_type='domain' の場合 domain は必須です")

    body: dict[str, Any] = {"type": share_type, "role": role}
    if email_address:
        body["emailAddress"] = email_address
    if domain:
        body["domain"] = domain
    if allow_file_discovery is not None:
        body["allowFileDiscovery"] = allow_file_discovery

    params: dict[str, Any] = {
        "fields": _PERMISSION_FIELDS,
        "supportsAllDrives": "true",
        "sendNotificationEmail": "true" if send_notification_email else "false",
    }
    if message and send_notification_email:
        params["emailMessage"] = message

    raw = await _drive_post(f"/files/{file_id}/permissions", body, params=params)
    return _format_permission(raw)


@mcp.tool()
async def drive_update_permission(file_id: str, permission_id: str, role: str) -> dict:
    """既存の共有権限のロールを変更する。

    Args:
        file_id: ファイル ID またはフォルダ ID
        permission_id: 変更対象の権限 ID（drive_list_permissions で取得できる）
        role: 新しい権限。"owner" | "organizer" | "fileOrganizer" | "writer" |
            "commenter" | "reader"

    Returns:
        { id, type, role, email_address?, domain?, display_name?,
          allow_file_discovery?, expiration_time?, deleted? }
    """
    if role not in _VALID_PERMISSION_ROLES:
        raise ValueError(f"無効な role です: {role!r}。有効な値: {sorted(_VALID_PERMISSION_ROLES)}")
    raw = await _drive_patch(
        f"/files/{file_id}/permissions/{permission_id}",
        {"role": role},
        params={"fields": _PERMISSION_FIELDS, "supportsAllDrives": "true"},
    )
    return _format_permission(raw)


@mcp.tool()
async def drive_remove_permission(file_id: str, permission_id: str) -> dict:
    """共有権限を削除し、アクセスを取り消す。

    Args:
        file_id: ファイル ID またはフォルダ ID
        permission_id: 削除対象の権限 ID（drive_list_permissions で取得できる）

    Returns:
        { success: true, file_id, permission_id }
    """
    await _drive_delete(
        f"/files/{file_id}/permissions/{permission_id}",
        params={"supportsAllDrives": "true"},
    )
    return {"success": True, "file_id": file_id, "permission_id": permission_id}
