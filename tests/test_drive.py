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
    drive_move_file,
    drive_rename_file,
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
