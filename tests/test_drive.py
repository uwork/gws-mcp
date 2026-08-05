"""features/mcp/drive.py の単体テスト。

HTTP 呼び出しはすべて unittest.mock で差し替える。
非同期関数は pytest-anyio ではなく anyio.pytest_plugin の @pytest.mark.anyio を使う。
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from features.mcp import drive as drive_module
from features.mcp.drive import (
    drive_copy_file,
    drive_create_folder,
    drive_get_file,
    drive_list_files,
    drive_list_permissions,
    drive_move_file,
    drive_remove_permission,
    drive_rename_file,
    drive_share_file,
    drive_update_permission,
)


def _make_httpx_mock(response_json: dict, status_code: int = 200) -> MagicMock:
    """httpx.AsyncClient のコンテキストマネージャモックを生成する。"""
    mock_response = MagicMock()
    mock_response.is_success = 200 <= status_code < 300
    mock_response.status_code = status_code
    mock_response.reason_phrase = "OK" if mock_response.is_success else "Error"
    mock_response.json.return_value = response_json
    mock_response.text = str(response_json)
    mock_response.request = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.patch = AsyncMock(return_value=mock_response)
    mock_client.delete = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.fixture(autouse=True)
def _authenticated(mocker):
    """既定で認証済みユーザーとして振る舞う。"""
    mocker.patch.object(drive_module, "get_current_user_id", return_value="user-1")
    mocker.patch.object(drive_module, "get_valid_access_token", AsyncMock(return_value="token"))


_FOLDER_RAW = {
    "id": "folder-1",
    "name": "My Folder",
    "mimeType": "application/vnd.google-apps.folder",
    "parents": ["root"],
    "createdTime": "2026-01-01T00:00:00Z",
    "modifiedTime": "2026-01-02T00:00:00Z",
    "webViewLink": "https://drive.google.com/folder-1",
    "iconLink": "https://icon/folder",
    "trashed": False,
}

_FILE_RAW = {
    "id": "file-1",
    "name": "report.pdf",
    "mimeType": "application/pdf",
    "parents": ["folder-1"],
    "createdTime": "2026-01-01T00:00:00Z",
    "modifiedTime": "2026-01-02T00:00:00Z",
    "size": "12345",
    "webViewLink": "https://drive.google.com/file-1",
    "iconLink": "https://icon/pdf",
    "trashed": False,
}


# ---------------------------------------------------------------------------
# _format_file 経由の整形確認
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_get_file_formats_folder(mocker):
    mock_client = _make_httpx_mock(_FOLDER_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_get_file("folder-1")
    assert result["id"] == "folder-1"
    assert result["is_folder"] is True
    assert "size_bytes" not in result


@pytest.mark.anyio
async def test_drive_get_file_formats_file_with_size(mocker):
    mock_client = _make_httpx_mock(_FILE_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_get_file("file-1")
    assert result["is_folder"] is False
    assert result["size_bytes"] == 12345


# ---------------------------------------------------------------------------
# drive_list_files — q パラメータ組み立て
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_list_files_returns_formatted_files(mocker):
    mock_client = _make_httpx_mock({"files": [_FILE_RAW], "nextPageToken": "tok"})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_list_files()
    assert result["file_count"] == 1
    assert result["files"][0]["id"] == "file-1"
    assert result["next_page_token"] == "tok"


@pytest.mark.anyio
async def test_drive_list_files_omits_next_page_token_when_absent(mocker):
    mock_client = _make_httpx_mock({"files": []})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_list_files()
    assert "next_page_token" not in result


@pytest.mark.anyio
async def test_drive_list_files_builds_folder_query(mocker):
    mock_client = _make_httpx_mock({"files": []})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_list_files(folder_id="folder-1")
    call_kwargs = mock_client.get.call_args
    q = call_kwargs[1]["params"]["q"]
    assert "'folder-1' in parents" in q
    assert "trashed = false" in q


@pytest.mark.anyio
async def test_drive_list_files_builds_name_query(mocker):
    mock_client = _make_httpx_mock({"files": []})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_list_files(query="budget")
    q = mock_client.get.call_args[1]["params"]["q"]
    assert "name contains 'budget'" in q


@pytest.mark.anyio
async def test_drive_list_files_only_folders_filters_mime_type(mocker):
    mock_client = _make_httpx_mock({"files": []})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_list_files(only_folders=True)
    q = mock_client.get.call_args[1]["params"]["q"]
    assert "mimeType = 'application/vnd.google-apps.folder'" in q


@pytest.mark.anyio
async def test_drive_list_files_escapes_quotes_in_query(mocker):
    mock_client = _make_httpx_mock({"files": []})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_list_files(query="a'b")
    q = mock_client.get.call_args[1]["params"]["q"]
    assert "a\\'b" in q


# ---------------------------------------------------------------------------
# drive_create_folder
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_create_folder_posts_with_mime_type(mocker):
    mock_client = _make_httpx_mock(_FOLDER_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_create_folder("My Folder", parent_id="parent-1")
    body = mock_client.post.call_args[1]["json"]
    assert body["mimeType"] == "application/vnd.google-apps.folder"
    assert body["parents"] == ["parent-1"]
    assert result["is_folder"] is True


@pytest.mark.anyio
async def test_drive_create_folder_without_parent_omits_parents(mocker):
    mock_client = _make_httpx_mock(_FOLDER_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_create_folder("My Folder")
    body = mock_client.post.call_args[1]["json"]
    assert "parents" not in body


# ---------------------------------------------------------------------------
# drive_rename_file
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_rename_file_patches_name(mocker):
    renamed = {**_FILE_RAW, "name": "new-name.pdf"}
    mock_client = _make_httpx_mock(renamed)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_rename_file("file-1", "new-name.pdf")
    body = mock_client.patch.call_args[1]["json"]
    assert body == {"name": "new-name.pdf"}
    assert result["name"] == "new-name.pdf"


# ---------------------------------------------------------------------------
# drive_move_file
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_move_file_with_explicit_old_parent(mocker):
    mock_client = _make_httpx_mock(_FILE_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_move_file("file-1", "new-parent", old_parent_id="old-parent")
    mock_client.get.assert_not_called()
    params = mock_client.patch.call_args[1]["params"]
    assert params["addParents"] == "new-parent"
    assert params["removeParents"] == "old-parent"


@pytest.mark.anyio
async def test_drive_move_file_auto_fetches_current_parents(mocker):
    mock_client = _make_httpx_mock(_FILE_RAW)
    mock_client.get = AsyncMock(
        return_value=MagicMock(
            is_success=True,
            json=MagicMock(return_value={"parents": ["old-parent-a", "old-parent-b"]}),
        )
    )
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_move_file("file-1", "new-parent")
    mock_client.get.assert_awaited_once()
    params = mock_client.patch.call_args[1]["params"]
    assert params["removeParents"] == "old-parent-a,old-parent-b"


# ---------------------------------------------------------------------------
# drive_copy_file
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drive_copy_file_posts_name_and_parent(mocker):
    copied = {**_FILE_RAW, "id": "file-2", "name": "copy.pdf"}
    mock_client = _make_httpx_mock(copied)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_copy_file("file-1", new_name="copy.pdf", parent_id="parent-1")
    body = mock_client.post.call_args[1]["json"]
    assert body == {"name": "copy.pdf", "parents": ["parent-1"]}
    assert result["id"] == "file-2"


@pytest.mark.anyio
async def test_drive_copy_file_without_options_sends_empty_body(mocker):
    mock_client = _make_httpx_mock(_FILE_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_copy_file("file-1")
    body = mock_client.post.call_args[1]["json"]
    assert body == {}


# ---------------------------------------------------------------------------
# 認証・エラー処理
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_user_id_raises_permission_error(mocker):
    mocker.patch.object(drive_module, "get_current_user_id", return_value=None)
    with pytest.raises(PermissionError):
        await drive_get_file("file-1")


@pytest.mark.anyio
async def test_no_access_token_raises_permission_error(mocker):
    mocker.patch.object(drive_module, "get_valid_access_token", AsyncMock(return_value=None))
    with pytest.raises(PermissionError):
        await drive_get_file("file-1")


@pytest.mark.anyio
async def test_api_error_raises_http_status_error(mocker):
    mock_client = _make_httpx_mock({"error": {"message": "not found"}}, status_code=404)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    with pytest.raises(httpx.HTTPStatusError):
        await drive_get_file("missing-file")


# ---------------------------------------------------------------------------
# drive_list_permissions / drive_share_file / drive_update_permission /
# drive_remove_permission
# ---------------------------------------------------------------------------

_PERMISSION_RAW = {
    "id": "perm-1",
    "type": "user",
    "role": "writer",
    "emailAddress": "alice@example.com",
    "displayName": "Alice",
}


@pytest.mark.anyio
async def test_drive_list_permissions_returns_formatted_permissions(mocker):
    mock_client = _make_httpx_mock({"permissions": [_PERMISSION_RAW]})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_list_permissions("file-1")
    assert result["permission_count"] == 1
    assert result["permissions"][0]["email_address"] == "alice@example.com"
    assert result["permissions"][0]["display_name"] == "Alice"


@pytest.mark.anyio
async def test_drive_share_file_with_user_posts_email_and_role(mocker):
    mock_client = _make_httpx_mock(_PERMISSION_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_share_file(
        "file-1", role="writer", share_type="user", email_address="alice@example.com"
    )
    body = mock_client.post.call_args[1]["json"]
    assert body == {"type": "user", "role": "writer", "emailAddress": "alice@example.com"}
    assert result["role"] == "writer"


@pytest.mark.anyio
async def test_drive_share_file_anyone_omits_email(mocker):
    mock_client = _make_httpx_mock({**_PERMISSION_RAW, "type": "anyone", "emailAddress": None})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_share_file("file-1", role="reader", share_type="anyone")
    body = mock_client.post.call_args[1]["json"]
    assert body == {"type": "anyone", "role": "reader"}


@pytest.mark.anyio
async def test_drive_share_file_disables_notification_email(mocker):
    mock_client = _make_httpx_mock(_PERMISSION_RAW)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    await drive_share_file(
        "file-1",
        role="writer",
        share_type="user",
        email_address="alice@example.com",
        send_notification_email=False,
    )
    params = mock_client.post.call_args[1]["params"]
    assert params["sendNotificationEmail"] == "false"


@pytest.mark.anyio
async def test_drive_share_file_invalid_role_raises_value_error(mocker):
    with pytest.raises(ValueError):
        await drive_share_file(
            "file-1", role="bogus", share_type="user", email_address="alice@example.com"
        )


@pytest.mark.anyio
async def test_drive_share_file_invalid_type_raises_value_error(mocker):
    with pytest.raises(ValueError):
        await drive_share_file("file-1", role="writer", share_type="bogus")


@pytest.mark.anyio
async def test_drive_share_file_user_without_email_raises_value_error(mocker):
    with pytest.raises(ValueError):
        await drive_share_file("file-1", role="writer", share_type="user")


@pytest.mark.anyio
async def test_drive_share_file_domain_without_domain_raises_value_error(mocker):
    with pytest.raises(ValueError):
        await drive_share_file("file-1", role="reader", share_type="domain")


@pytest.mark.anyio
async def test_drive_update_permission_patches_role(mocker):
    updated = {**_PERMISSION_RAW, "role": "reader"}
    mock_client = _make_httpx_mock(updated)
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_update_permission("file-1", "perm-1", "reader")
    body = mock_client.patch.call_args[1]["json"]
    assert body == {"role": "reader"}
    assert result["role"] == "reader"


@pytest.mark.anyio
async def test_drive_update_permission_invalid_role_raises_value_error(mocker):
    with pytest.raises(ValueError):
        await drive_update_permission("file-1", "perm-1", "bogus")


@pytest.mark.anyio
async def test_drive_remove_permission_deletes_and_returns_success(mocker):
    mock_client = _make_httpx_mock({})
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    result = await drive_remove_permission("file-1", "perm-1")
    mock_client.delete.assert_awaited_once()
    assert result == {"success": True, "file_id": "file-1", "permission_id": "perm-1"}
