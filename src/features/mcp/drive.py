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


def _escape_query_value(value: str) -> str:
    """Drive API の q パラメータに埋め込む文字列をエスケープする。"""
    return value.replace("\\", "\\\\").replace("'", "\\'")


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
