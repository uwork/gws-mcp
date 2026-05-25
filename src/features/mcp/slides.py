"""Google Slides API クライアントおよび MCP ツール定義。

各ツールは AI が扱いやすいフラットな dict を返す。
Google API のネスト構造・camelCase キーを整形して返す。
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from features.mcp.auth import get_current_user_id
from features.mcp.instance import mcp
from features.oauth.google import get_valid_access_token

logger = logging.getLogger(__name__)

_SLIDES_BASE = "https://slides.googleapis.com/v1/presentations"
_DRIVE_BASE = "https://www.googleapis.com/drive/v3"


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


async def _slides_get(path: str, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_SLIDES_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _slides_post(path: str, body: dict) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_SLIDES_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _drive_get_json(path: str, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DRIVE_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _drive_post(path: str, body: dict) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_DRIVE_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# AI フレンドリー変換ヘルパー
# ---------------------------------------------------------------------------


def _extract_text_content(text_content: dict) -> str:
    """textContent オブジェクトからプレーンテキストを抽出する。"""
    parts: list[str] = []
    for elem in text_content.get("textElements", []):
        run = elem.get("textRun", {})
        if run:
            parts.append(run.get("content", ""))
    return "".join(parts).strip()


def _format_dimension(d: dict) -> dict[str, Any] | None:
    if not d:
        return None
    return {"magnitude": d.get("magnitude"), "unit": d.get("unit", "")}


def _format_size(size: dict) -> dict[str, Any]:
    return {
        "width": _format_dimension(size.get("width", {})),
        "height": _format_dimension(size.get("height", {})),
    }


def _format_transform(t: dict) -> dict[str, Any]:
    return {
        "scale_x": t.get("scaleX", 1.0),
        "scale_y": t.get("scaleY", 1.0),
        "translate_x": t.get("translateX", 0.0),
        "translate_y": t.get("translateY", 0.0),
        "unit": t.get("unit", ""),
    }


def _format_page_element(elem: dict) -> dict[str, Any]:
    result: dict[str, Any] = {
        "object_id": elem.get("objectId", ""),
        "size": _format_size(elem.get("size", {})),
        "transform": _format_transform(elem.get("transform", {})),
        "title": elem.get("title"),
        "description": elem.get("description"),
    }

    if "shape" in elem:
        shape = elem["shape"]
        result["type"] = "shape"
        result["shape_type"] = shape.get("shapeType", "")
        result["placeholder"] = shape.get("placeholder", {}).get("type")
        if "text" in shape:
            result["text"] = _extract_text_content(shape["text"])
    elif "image" in elem:
        image = elem["image"]
        result["type"] = "image"
        result["source_url"] = image.get("sourceUrl", "")
        result["content_url"] = image.get("contentUrl", "")
    elif "video" in elem:
        video = elem["video"]
        result["type"] = "video"
        result["video_id"] = video.get("id", "")
        result["video_source"] = video.get("source", "")
        result["url"] = video.get("url", "")
    elif "line" in elem:
        result["type"] = "line"
        result["line_type"] = elem["line"].get("lineType", "")
        result["line_category"] = elem["line"].get("lineCategory", "")
    elif "table" in elem:
        table = elem["table"]
        result["type"] = "table"
        result["rows"] = table.get("rows", 0)
        result["columns"] = table.get("columns", 0)
        cell_values: list[list[str]] = []
        for row in table.get("tableRows", []):
            row_cells = [
                _extract_text_content(cell.get("text", {})) for cell in row.get("tableCells", [])
            ]
            cell_values.append(row_cells)
        result["cell_values"] = cell_values
    elif "wordArt" in elem:
        result["type"] = "word_art"
        result["text"] = elem["wordArt"].get("renderedText", "")
    elif "sheetsChart" in elem:
        chart = elem["sheetsChart"]
        result["type"] = "sheets_chart"
        result["spreadsheet_id"] = chart.get("spreadsheetId", "")
        result["chart_id"] = chart.get("chartId", 0)
    elif "elementGroup" in elem:
        result["type"] = "group"
        result["children"] = [
            _format_page_element(child) for child in elem["elementGroup"].get("children", [])
        ]
    elif "speakerSpotlight" in elem:
        result["type"] = "speaker_spotlight"
    else:
        result["type"] = "unknown"

    return result


def _extract_slide_notes_text(slide: dict) -> str:
    """スライドのスピーカーノートテキストを抽出する。"""
    notes_page = slide.get("slideProperties", {}).get("notesPage", {})
    for elem in notes_page.get("pageElements", []):
        shape = elem.get("shape", {})
        placeholder = shape.get("placeholder", {})
        if placeholder.get("type") == "BODY" and "text" in shape:
            return _extract_text_content(shape["text"])
    return ""


def _format_presentation_summary(raw: dict) -> dict[str, Any]:
    page_size = raw.get("pageSize", {})
    slides_raw = raw.get("slides", [])

    slides = []
    for i, slide in enumerate(slides_raw):
        info: dict[str, Any] = {
            "object_id": slide.get("objectId", ""),
            "index": i,
            "element_count": len(slide.get("pageElements", [])),
        }
        notes = _extract_slide_notes_text(slide)
        if notes:
            info["speaker_notes"] = notes
        # 各要素のテキストをサマリとして含める
        texts = []
        for elem in slide.get("pageElements", []):
            shape = elem.get("shape", {})
            if "text" in shape:
                t = _extract_text_content(shape["text"])
                if t:
                    texts.append(t)
        if texts:
            info["text_summary"] = texts
        slides.append(info)

    return {
        "presentation_id": raw.get("presentationId", ""),
        "title": raw.get("title", ""),
        "locale": raw.get("locale", ""),
        "revision_id": raw.get("revisionId", ""),
        "page_size": _format_size(page_size),
        "slide_count": len(slides_raw),
        "slides": slides,
    }


def _format_page(raw: dict) -> dict[str, Any]:
    return {
        "object_id": raw.get("objectId", ""),
        "page_type": raw.get("pageType", "SLIDE"),
        "revision_id": raw.get("revisionId", ""),
        "element_count": len(raw.get("pageElements", [])),
        "page_elements": [_format_page_element(e) for e in raw.get("pageElements", [])],
    }


def _format_comment(c: dict) -> dict[str, Any]:
    author = c.get("author", {})
    replies = []
    for r in c.get("replies", []):
        r_author = r.get("author", {})
        replies.append(
            {
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "created_time": r.get("createdTime", ""),
                "author_name": r_author.get("displayName", ""),
                "author_email": r_author.get("emailAddress", ""),
                "action": r.get("action"),
                "deleted": r.get("deleted", False),
            }
        )
    return {
        "id": c.get("id", ""),
        "content": c.get("content", ""),
        "created_time": c.get("createdTime", ""),
        "modified_time": c.get("modifiedTime", ""),
        "author_name": author.get("displayName", ""),
        "author_email": author.get("emailAddress", ""),
        "resolved": c.get("resolved", False),
        "deleted": c.get("deleted", False),
        "reply_count": len(replies),
        "replies": replies,
    }


# ---------------------------------------------------------------------------
# MCP ツール定義
# ---------------------------------------------------------------------------


@mcp.tool()
async def slides_get_presentation(presentation_id: str) -> dict:
    """プレゼンテーションの概要を取得する（スライド一覧・テキストサマリ）。

    Args:
        presentation_id: プレゼンテーション ID（URL の /d/<ID>/ 部分）

    Returns:
        {
            presentation_id, title, locale, revision_id,
            page_size: { width: {magnitude, unit}, height: {magnitude, unit} },
            slide_count,
            slides: [{
                object_id, index, element_count,
                text_summary: [...],   # 各要素のテキスト
                speaker_notes?         # スピーカーノートがある場合のみ
            }, ...]
        }
    """
    raw = await _slides_get(f"/{presentation_id}")
    return _format_presentation_summary(raw)


@mcp.tool()
async def slides_get_page(presentation_id: str, page_object_id: str) -> dict:
    """特定スライド（ページ）の全要素詳細を取得する。

    スライドの object_id は slides_get_presentation の slides[].object_id で確認できる。

    Args:
        presentation_id: プレゼンテーション ID
        page_object_id: ページの object_id

    Returns:
        {
            object_id, page_type, revision_id, element_count,
            page_elements: [{
                object_id, type, size, transform,
                text?,          # shape の場合
                shape_type?,    # shape の場合
                placeholder?,   # shape の場合（TITLE / BODY / SLIDE_NUMBER など）
                source_url?,    # image の場合
                cell_values?,   # table の場合
                ...
            }, ...]
        }
    """
    raw = await _slides_get(f"/{presentation_id}/pages/{page_object_id}")
    return _format_page(raw)


@mcp.tool()
async def slides_batch_update(
    presentation_id: str,
    requests: list[dict],
) -> dict:
    """プレゼンテーションに一括更新を適用する（presentations.batchUpdate）。

    requests リストに更新操作オブジェクトを列挙して送信する。
    使用可能な request 種別は slides_batch_update_help() を参照。

    Args:
        presentation_id: プレゼンテーション ID
        requests: 更新操作のリスト。
            例: [{"replaceAllText": {"containsText": {"text": "旧"}, "replaceText": "新"}}]

    Returns:
        {
            presentation_id,
            replies: [...]   # 各 request への応答（操作によっては空 {}）
        }
    """
    raw = await _slides_post(
        f"/{presentation_id}:batchUpdate",
        {"requests": requests},
    )
    return {
        "presentation_id": raw.get("presentationId", ""),
        "replies": raw.get("replies", []),
    }


@mcp.tool()
def slides_batch_update_help() -> dict:
    """slides_batch_update で使用できる request 種別とフィールド指定の完全リファレンスを返す。

    slides_batch_update の requests を組み立てる前に参照する。
    """
    return {
        "overview": (
            "requests は操作オブジェクトのリスト。"
            "各オブジェクトはキーが操作名、値が操作の詳細。"
            "object_id は slides_get_presentation / slides_get_page で確認する。"
        ),
        "text_operations": {
            "replaceAllText": {
                "desc": "プレゼンテーション全体のテキストを一括置換する",
                "example": {
                    "replaceAllText": {
                        "containsText": {"text": "置換前", "matchCase": True},
                        "replaceText": "置換後",
                    }
                },
            },
            "insertText": {
                "desc": "テキストボックスにテキストを挿入する",
                "example": {
                    "insertText": {
                        "objectId": "<shape_object_id>",
                        "insertionIndex": 0,
                        "text": "挿入するテキスト",
                    }
                },
            },
            "deleteText": {
                "desc": "テキストの範囲を削除する",
                "example": {
                    "deleteText": {
                        "objectId": "<shape_object_id>",
                        "textRange": {"type": "ALL"},
                    }
                },
            },
            "updateTextStyle": {
                "desc": "テキストのスタイル（フォント・色・太字など）を更新する",
                "fields": (
                    "bold | italic | underline | strikethrough"
                    " | fontSize | foregroundColor | fontFamily | link | baselineOffset"
                ),
                "example": {
                    "updateTextStyle": {
                        "objectId": "<shape_object_id>",
                        "textRange": {"type": "ALL"},
                        "style": {"bold": True},
                        "fields": "bold",
                    }
                },
            },
            "updateParagraphStyle": {
                "desc": "段落スタイル（配置・行間・インデントなど）を更新する",
                "fields": (
                    "alignment | lineSpacing | spaceAbove | spaceBelow"
                    " | indentStart | indentEnd | indentFirstLine | direction | spacingMode"
                ),
                "alignment_values": "START | CENTER | END | JUSTIFIED",
            },
            "createParagraphBullets": {
                "desc": "テキストに箇条書きを追加する",
                "example": {
                    "createParagraphBullets": {
                        "objectId": "<shape_object_id>",
                        "textRange": {"type": "ALL"},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                },
            },
            "deleteParagraphBullets": {
                "desc": "箇条書きを削除する",
                "example": {
                    "deleteParagraphBullets": {
                        "objectId": "<shape_object_id>",
                        "textRange": {"type": "ALL"},
                    }
                },
            },
        },
        "slide_operations": {
            "createSlide": {
                "desc": "新しいスライドを追加する",
                "example": {
                    "createSlide": {
                        "insertionIndex": 1,
                        "slideLayoutReference": {"predefinedLayout": "BLANK"},
                    }
                },
                "predefined_layouts": (
                    "BLANK | CAPTION_ONLY | TITLE | TITLE_AND_BODY"
                    " | TITLE_AND_TWO_COLUMNS | TITLE_ONLY | SECTION_HEADER"
                    " | SECTION_TITLE_AND_DESCRIPTION | ONE_COLUMN_TEXT"
                    " | MAIN_POINT | BIG_NUMBER"
                ),
            },
            "deleteObject": {
                "desc": "スライドまたは要素を削除する",
                "example": {"deleteObject": {"objectId": "<object_id>"}},
            },
            "duplicateObject": {
                "desc": "スライドまたは要素を複製する",
                "example": {"duplicateObject": {"objectId": "<object_id>"}},
            },
            "updateSlidesPosition": {
                "desc": "スライドの順序を変更する",
                "example": {
                    "updateSlidesPosition": {
                        "slideObjectIds": ["<slide_id_1>", "<slide_id_2>"],
                        "insertionIndex": 0,
                    }
                },
            },
            "updateSlideProperties": {
                "desc": "スライドのプロパティを更新する（レイアウト・非表示など）",
                "fields": "layoutObjectId | masterObjectId | isSkipped | notesPage",
                "example": {
                    "updateSlideProperties": {
                        "objectId": "<slide_object_id>",
                        "slideProperties": {"isSkipped": True},
                        "fields": "isSkipped",
                    }
                },
            },
            "updatePageProperties": {
                "desc": "ページの背景・カラーテーマを更新する",
                "fields": "pageBackgroundFill | colorScheme",
            },
        },
        "shape_operations": {
            "createShape": {
                "desc": "図形を作成する",
                "example": {
                    "createShape": {
                        "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": "<slide_object_id>",
                            "size": {
                                "width": {"magnitude": 300, "unit": "PT"},
                                "height": {"magnitude": 100, "unit": "PT"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 100,
                                "translateY": 100,
                                "unit": "PT",
                            },
                        },
                    }
                },
            },
            "updateShapeProperties": {
                "desc": "図形のプロパティ（塗りつぶし・枠線・影など）を更新する",
                "fields": "shapeBackgroundFill | outline | shadow | link | contentAlignment | autofit",  # noqa: E501
            },
            "updatePageElementsZOrder": {
                "desc": "要素の重なり順を変更する",
                "operation": "BRING_TO_FRONT | BRING_FORWARD | SEND_BACKWARD | SEND_TO_BACK",
                "example": {
                    "updatePageElementsZOrder": {
                        "pageElementObjectIds": ["<object_id>"],
                        "operation": "BRING_TO_FRONT",
                    }
                },
            },
            "updatePageElementTransform": {
                "desc": "要素の位置・サイズ・回転を更新する",
                "example": {
                    "updatePageElementTransform": {
                        "objectId": "<object_id>",
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 50,
                            "translateY": 50,
                            "unit": "PT",
                        },
                        "applyMode": "ABSOLUTE",
                    }
                },
            },
            "updatePageElementAltText": {
                "desc": "要素の代替テキストを更新する",
                "example": {
                    "updatePageElementAltText": {
                        "objectId": "<object_id>",
                        "title": "タイトル",
                        "description": "説明文",
                    }
                },
            },
        },
        "image_operations": {
            "createImage": {
                "desc": "画像を追加する",
                "example": {
                    "createImage": {
                        "url": "https://example.com/image.png",
                        "elementProperties": {
                            "pageObjectId": "<slide_object_id>",
                            "size": {
                                "width": {"magnitude": 200, "unit": "PT"},
                                "height": {"magnitude": 150, "unit": "PT"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 100,
                                "translateY": 100,
                                "unit": "PT",
                            },
                        },
                    }
                },
            },
            "updateImageProperties": {
                "desc": "画像プロパティ（明度・コントラスト・切り取りなど）を更新する",
                "fields": (
                    "cropProperties | transparency | brightness | contrast"
                    " | recolor | outline | shadow | link"
                ),
            },
            "replaceAllShapesWithImage": {
                "desc": "指定テキストを含む図形を画像に一括置換する",
                "example": {
                    "replaceAllShapesWithImage": {
                        "containsText": {"text": "{{IMAGE}}"},
                        "imageUrl": "https://example.com/image.png",
                        "replaceMethod": "CENTER_INSIDE",
                    }
                },
            },
        },
        "table_operations": {
            "createTable": {
                "desc": "表を作成する",
                "example": {
                    "createTable": {
                        "rows": 3,
                        "columns": 4,
                        "elementProperties": {
                            "pageObjectId": "<slide_object_id>",
                            "size": {
                                "width": {"magnitude": 400, "unit": "PT"},
                                "height": {"magnitude": 200, "unit": "PT"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 50,
                                "translateY": 100,
                                "unit": "PT",
                            },
                        },
                    }
                },
            },
            "insertTableRows": {
                "desc": "表に行を挿入する",
                "example": {
                    "insertTableRows": {
                        "tableObjectId": "<table_object_id>",
                        "cellLocation": {"rowIndex": 1, "columnIndex": 0},
                        "insertBelow": True,
                        "number": 2,
                    }
                },
            },
            "insertTableColumns": {
                "desc": "表に列を挿入する",
                "example": {
                    "insertTableColumns": {
                        "tableObjectId": "<table_object_id>",
                        "cellLocation": {"rowIndex": 0, "columnIndex": 1},
                        "insertRight": True,
                        "number": 1,
                    }
                },
            },
            "deleteTableRow": {
                "desc": "表の行を削除する",
                "example": {
                    "deleteTableRow": {
                        "tableObjectId": "<table_object_id>",
                        "cellLocation": {"rowIndex": 2, "columnIndex": 0},
                    }
                },
            },
            "deleteTableColumn": {
                "desc": "表の列を削除する",
                "example": {
                    "deleteTableColumn": {
                        "tableObjectId": "<table_object_id>",
                        "cellLocation": {"rowIndex": 0, "columnIndex": 2},
                    }
                },
            },
            "updateTableCellProperties": {
                "desc": "セルの背景色・枠線を更新する",
                "fields": "tableCellBackgroundFill | contentAlignment",
            },
            "mergeTableCells": {
                "desc": "表のセルを結合する",
                "example": {
                    "mergeTableCells": {
                        "tableObjectId": "<table_object_id>",
                        "tableRange": {
                            "location": {"rowIndex": 0, "columnIndex": 0},
                            "rowSpan": 1,
                            "columnSpan": 3,
                        },
                    }
                },
            },
            "unmergeTableCells": {
                "desc": "結合されたセルを解除する",
                "example": {
                    "unmergeTableCells": {
                        "tableObjectId": "<table_object_id>",
                        "tableRange": {
                            "location": {"rowIndex": 0, "columnIndex": 0},
                            "rowSpan": 1,
                            "columnSpan": 3,
                        },
                    }
                },
            },
        },
        "group_operations": {
            "groupObjects": {
                "desc": "複数の要素をグループ化する",
                "example": {
                    "groupObjects": {
                        "childrenObjectIds": ["<object_id_1>", "<object_id_2>"],
                    }
                },
            },
            "ungroupObjects": {
                "desc": "グループを解除する",
                "example": {"ungroupObjects": {"objectIds": ["<group_object_id>"]}},
            },
        },
        "text_range_types": {
            "desc": "textRange の type フィールドの値",
            "values": {
                "ALL": "テキスト全体",
                "FROM_START_INDEX": "startIndex から末尾まで",
                "FIXED_RANGE": (
                    "startIndex から startIndex+endIndex まで"
                    "（endIndex は長さではなく終端インデックス）"
                ),
            },
        },
    }


@mcp.tool()
async def slides_export(
    presentation_id: str,
    mime_type: str = "application/pdf",
) -> dict:
    """プレゼンテーションを指定形式でエクスポートする（Drive API）。

    Args:
        presentation_id: プレゼンテーション ID
        mime_type: エクスポート形式
            "application/pdf" — PDF（デフォルト）
            "application/vnd.openxmlformats-officedocument.presentationml.presentation" — PPTX
            "text/plain" — テキスト（各スライドのテキストを抽出）

    Returns:
        text/plain の場合: { mime_type, content, size_bytes }
        バイナリの場合: { mime_type, content_base64, size_bytes }

    Note:
        大きなプレゼンテーションの PDF/PPTX エクスポートはサイズが大きくなる場合がある。
        スライド画像が必要な場合は slides_get_thumbnail を使用する。
    """
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DRIVE_BASE}/files/{presentation_id}/export",
            headers=_auth_headers(token),
            params={"mimeType": mime_type},
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.content

    size_bytes = len(content)

    if mime_type == "text/plain":
        return {
            "mime_type": mime_type,
            "content": content.decode("utf-8", errors="replace"),
            "size_bytes": size_bytes,
        }

    return {
        "mime_type": mime_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "size_bytes": size_bytes,
    }


@mcp.tool()
async def slides_get_thumbnail(
    presentation_id: str,
    page_object_id: str,
    thumbnail_size: str = "LARGE",
    mime_type: str = "PNG",
) -> dict:
    """スライドのサムネイル画像 URL を取得する。

    スライドの object_id は slides_get_presentation の slides[].object_id で確認できる。

    Args:
        presentation_id: プレゼンテーション ID
        page_object_id: ページの object_id
        thumbnail_size: "LARGE"（デフォルト、1600px）または "MEDIUM"（800px）または "SMALL"（200px）
        mime_type: "PNG"（デフォルト）または "JPEG"

    Returns:
        {
            content_url,  # サムネイル画像の URL（一時的な署名付き URL）
            width,        # 幅（ピクセル）
            height        # 高さ（ピクセル）
        }
    """
    raw = await _slides_get(
        f"/{presentation_id}/pages/{page_object_id}/thumbnail",
        params={
            "thumbnailProperties.thumbnailSize": thumbnail_size,
            "thumbnailProperties.mimeType": mime_type,
        },
    )
    return {
        "content_url": raw.get("contentUrl", ""),
        "width": raw.get("width", 0),
        "height": raw.get("height", 0),
    }


@mcp.tool()
async def slides_list_comments(
    presentation_id: str,
    include_deleted: bool = False,
) -> dict:
    """プレゼンテーションのコメント一覧を取得する（Drive API）。

    Args:
        presentation_id: プレゼンテーション ID
        include_deleted: 削除済みコメントを含める場合は True

    Returns:
        {
            presentation_id,
            comment_count,
            comments: [{
                id, content, created_time, modified_time,
                author_name, author_email, resolved, deleted,
                reply_count,
                replies: [{ id, content, created_time, author_name, author_email, action,
                            deleted }, ...]
            }, ...]
        }

    Note:
        コメントは Drive API 経由で取得する。スライド上の特定要素ではなく
        ファイルレベルのコメントが返る（要素への紐付けは Drive API 非対応）。
    """
    raw = await _drive_get_json(
        f"/files/{presentation_id}/comments",
        params={
            "fields": "*",
            "includeDeleted": str(include_deleted).lower(),
            "pageSize": 100,
        },
    )
    comments = [_format_comment(c) for c in raw.get("comments", [])]
    return {
        "presentation_id": presentation_id,
        "comment_count": len(comments),
        "comments": comments,
    }


@mcp.tool()
async def slides_add_comment(
    presentation_id: str,
    content: str,
) -> dict:
    """プレゼンテーションにコメントを追加する（Drive API）。

    Args:
        presentation_id: プレゼンテーション ID
        content: コメント本文

    Returns:
        {
            id, content, created_time, modified_time,
            author_name, author_email, resolved
        }

    Note:
        Drive API の制約により、コメントはファイルレベルで追加される。
        特定スライドや要素への紐付けは API では非対応。
    """
    raw = await _drive_post(
        f"/files/{presentation_id}/comments",
        {"content": content},
    )
    return _format_comment(raw)
