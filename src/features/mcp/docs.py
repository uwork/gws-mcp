"""Google Docs API クライアントおよび MCP ツール定義。

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

_DOCS_BASE = "https://docs.googleapis.com/v1/documents"
_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_EXPORT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


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


async def _docs_get(path: str, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DOCS_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        if not resp.is_success:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {resp.reason_phrase}: {detail}",
                request=resp.request,
                response=resp,
            )
        return resp.json()


async def _docs_post(path: str, body: dict) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_DOCS_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if not resp.is_success:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {resp.reason_phrase}: {detail}",
                request=resp.request,
                response=resp,
            )
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
        if not resp.is_success:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {resp.reason_phrase}: {detail}",
                request=resp.request,
                response=resp,
            )
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
        if not resp.is_success:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {resp.reason_phrase}: {detail}",
                request=resp.request,
                response=resp,
            )
        return resp.json()


# ---------------------------------------------------------------------------
# AI フレンドリー変換ヘルパー
# ---------------------------------------------------------------------------


def _extract_paragraph_text(paragraph: dict) -> str:
    """段落要素からプレーンテキストを抽出する。"""
    parts: list[str] = []
    for elem in paragraph.get("elements", []):
        text_run = elem.get("textRun", {})
        if text_run:
            parts.append(text_run.get("content", ""))
        elif "footnoteReference" in elem:
            parts.append("[注]")
        elif "inlineObjectElement" in elem:
            parts.append("[画像]")
    return "".join(parts)


def _format_structural_element(elem: dict) -> dict[str, Any] | None:
    """StructuralElement を AI フレンドリーな dict に変換する。"""
    if "paragraph" in elem:
        p = elem["paragraph"]
        text = _extract_paragraph_text(p)
        style = p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        result: dict[str, Any] = {
            "type": "paragraph",
            "style": style,
            "text": text,
        }
        bullet = p.get("bullet")
        if bullet:
            result["list_id"] = bullet.get("listId", "")
            result["nesting_level"] = bullet.get("nestingLevel", 0)
        return result
    elif "table" in elem:
        table = elem["table"]
        rows_data: list[list[str]] = []
        for row in table.get("tableRows", []):
            cells_data: list[str] = []
            for cell in row.get("tableCells", []):
                cell_text_parts: list[str] = []
                for cell_elem in cell.get("content", []):
                    formatted = _format_structural_element(cell_elem)
                    if formatted:
                        t = formatted.get("text", "")
                        if t:
                            cell_text_parts.append(t.strip())
                cells_data.append(" ".join(cell_text_parts))
            rows_data.append(cells_data)
        return {
            "type": "table",
            "rows": table.get("rows", 0),
            "columns": table.get("columns", 0),
            "cell_values": rows_data,
        }
    elif "sectionBreak" in elem:
        return {"type": "section_break"}
    elif "tableOfContents" in elem:
        return {"type": "table_of_contents"}
    return None


def _format_tab(tab: dict, include_elements: bool) -> dict[str, Any]:
    """単一 Tab オブジェクトを AI フレンドリーな dict に変換する。"""
    props = tab.get("tabProperties", {})
    body_content = tab.get("documentTab", {}).get("body", {}).get("content", [])
    elements: list[dict[str, Any]] = []
    plain_text_parts: list[str] = []

    for struct_elem in body_content:
        formatted = _format_structural_element(struct_elem)
        if formatted is None:
            continue
        t = formatted.get("text", "")
        if t:
            plain_text_parts.append(t)
        if include_elements:
            elements.append(formatted)

    if include_elements:
        element_count = len(elements)
    else:
        element_count = sum(1 for e in body_content if _format_structural_element(e) is not None)

    child_tabs = _collect_tabs_recursive(tab.get("childTabs", []), include_elements)

    # child_tabs のテキスト・要素数を再帰的に集計する
    child_plain_texts = [ct["plain_text"] for ct in child_tabs if ct["plain_text"]]
    child_element_count = sum(ct["element_count"] for ct in child_tabs)

    all_plain_text_parts = plain_text_parts + child_plain_texts
    total_element_count = element_count + child_element_count

    result: dict[str, Any] = {
        "tab_id": props.get("tabId", ""),
        "title": props.get("title", ""),
        "index": props.get("index", 0),
        "nesting_level": props.get("nestingLevel", 0),
        "plain_text": "\n".join(all_plain_text_parts),
        "element_count": total_element_count,
    }
    if include_elements:
        result["elements"] = elements
    parent_tab_id = props.get("parentTabId")
    if parent_tab_id:
        result["parent_tab_id"] = parent_tab_id
    if child_tabs:
        result["child_tabs"] = child_tabs
    return result


def _collect_tabs_recursive(tabs: list[dict], include_elements: bool) -> list[dict[str, Any]]:
    """Tab リストを再帰的にフォーマットする（ネストされた childTabs も含む）。"""
    return [_format_tab(t, include_elements) for t in tabs]


def _parse_named_ranges(named_ranges: dict) -> list[dict[str, Any]]:
    """namedRanges map<string, NamedRanges> を [{name, named_range_id}] に変換する。"""
    result = []
    for name, named_ranges_obj in named_ranges.items():
        for nr in named_ranges_obj.get("namedRanges", []):
            result.append({"name": name, "named_range_id": nr.get("namedRangeId", "")})
    return result


def _collect_inline_objects_from_tabs(tabs: list[dict]) -> list[dict[str, Any]]:
    """タブリスト（childTabs 含む）から inlineObjects を収集する。"""
    result = []
    for tab in tabs:
        doc_tab = tab.get("documentTab", {})
        for obj_id, obj in doc_tab.get("inlineObjects", {}).items():
            props = obj.get("inlineObjectProperties", {}).get("embeddedObject", {})
            result.append(
                {
                    "object_id": obj_id,
                    "title": props.get("title", ""),
                    "description": props.get("description", ""),
                }
            )
        result.extend(_collect_inline_objects_from_tabs(tab.get("childTabs", [])))
    return result


def _collect_named_ranges_from_tabs(tabs: list[dict]) -> list[dict[str, Any]]:
    """タブリスト（childTabs 含む）から namedRanges を収集する。"""
    result = []
    for tab in tabs:
        doc_tab = tab.get("documentTab", {})
        named_ranges = doc_tab.get("namedRanges", {})
        if named_ranges:
            result.extend(_parse_named_ranges(named_ranges))
        result.extend(_collect_named_ranges_from_tabs(tab.get("childTabs", [])))
    return result


def _format_document(
    raw: dict, include_elements: bool = True, include_tabs: bool = True
) -> dict[str, Any]:
    """Google Docs Document を AI フレンドリーな dict に変換する。"""
    raw_tabs = raw.get("tabs", []) if include_tabs else []

    if raw_tabs:
        tabs_formatted = _collect_tabs_recursive(raw_tabs, include_elements)
        plain_text = "\n".join(t["plain_text"] for t in tabs_formatted if t["plain_text"])
        element_count = sum(t["element_count"] for t in tabs_formatted)
        result: dict[str, Any] = {
            "document_id": raw.get("documentId", ""),
            "title": raw.get("title", ""),
            "revision_id": raw.get("revisionId", ""),
            "locale": raw.get("locale", ""),
            "plain_text": plain_text,
            "element_count": element_count,
            "tab_count": len(tabs_formatted),
            "tabs": tabs_formatted,
        }

        # タブモード時は inlineObjects / namedRanges が各タブの documentTab 内にある
        inline_obj_list = _collect_inline_objects_from_tabs(raw_tabs)
        if inline_obj_list:
            result["inline_objects"] = inline_obj_list

        named_range_list = _collect_named_ranges_from_tabs(raw_tabs)
        if named_range_list:
            result["named_ranges"] = named_range_list
    else:
        body_content = raw.get("body", {}).get("content", [])
        elements: list[dict[str, Any]] = []
        plain_text_parts: list[str] = []

        for struct_elem in body_content:
            formatted = _format_structural_element(struct_elem)
            if formatted is None:
                continue
            t = formatted.get("text", "")
            if t:
                plain_text_parts.append(t)
            if include_elements:
                elements.append(formatted)

        formatted_count = (
            len(elements)
            if include_elements
            else sum(1 for e in body_content if _format_structural_element(e) is not None)
        )

        result = {
            "document_id": raw.get("documentId", ""),
            "title": raw.get("title", ""),
            "revision_id": raw.get("revisionId", ""),
            "locale": raw.get("locale", ""),
            "plain_text": "".join(plain_text_parts),
            "element_count": formatted_count,
        }
        if include_elements:
            result["elements"] = elements

        # レガシーモード時は inlineObjects / namedRanges がドキュメントルートにある
        inline_objects = raw.get("inlineObjects", {})
        inline_obj_list = []
        for obj_id, obj in inline_objects.items():
            props = obj.get("inlineObjectProperties", {}).get("embeddedObject", {})
            inline_obj_list.append(
                {
                    "object_id": obj_id,
                    "title": props.get("title", ""),
                    "description": props.get("description", ""),
                }
            )
        if inline_obj_list:
            result["inline_objects"] = inline_obj_list

        named_ranges = raw.get("namedRanges", {})
        if named_ranges:
            result["named_ranges"] = _parse_named_ranges(named_ranges)

    return result


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
async def docs_get_document(
    document_id: str,
    include_elements: bool = True,
    include_tabs: bool = True,
) -> dict:
    """ドキュメントのコンテンツとメタデータを取得する。

    Args:
        document_id: ドキュメント ID（URL の /d/<ID>/ 部分）
        include_elements: True（デフォルト）の場合、段落・表などの構造要素を含む。
            ドキュメントが非常に大きい場合は False にしてプレーンテキストのみ取得する。
        include_tabs: True（デフォルト）の場合、タブ構造を含む（includeTabsContent=true）。
            タブがある場合は tabs フィールドにタブごとのコンテンツが入る。
            False にすると旧来の elements 形式（先頭タブのみ）を返す。

    Returns:
        タブあり（include_tabs=True）の場合:
        {
            document_id, title, revision_id, locale,
            plain_text,        # 全タブのテキストを結合したもの
            element_count,     # 全タブの合計要素数
            tab_count,         # トップレベルのタブ数
            tabs: [{
                tab_id, title, index, nesting_level,
                parent_tab_id?,  # ネストされたタブの場合のみ
                plain_text,      # このタブのテキスト
                element_count,   # このタブの要素数
                elements?: [{    # include_elements=True の場合
                    type, style?, text?, list_id?, nesting_level?,
                    rows?, columns?, cell_values?
                }, ...],
                child_tabs?,     # ネストされた子タブがある場合のみ
            }, ...],
            inline_objects?: [{ object_id, title, description }],
            named_ranges?: [{ name, named_range_id }]
        }

        タブなし（include_tabs=False またはタブ未使用ドキュメント）の場合:
        {
            document_id, title, revision_id, locale,
            plain_text,        # ドキュメント全体のプレーンテキスト
            element_count,
            elements?: [{      # include_elements=True の場合
                type,          # "paragraph" | "table" | "section_break" | "table_of_contents"
                style?,        # 段落: "NORMAL_TEXT" | "HEADING_1"～"HEADING_6" | "TITLE" etc.
                text?,         # 段落のテキスト
                list_id?,      # リスト項目の場合
                nesting_level?,# リスト項目のネスト深度
                rows?,         # 表の行数
                columns?,      # 表の列数
                cell_values?,  # 表のセル値 [[str, ...], ...]
            }, ...],
            inline_objects?: [{ object_id, title, description }],
            named_ranges?: [{ name, named_range_id }]
        }
    """
    params = {"includeTabsContent": "true"} if include_tabs else {}
    raw = await _docs_get(f"/{document_id}", params=params or None)
    return _format_document(raw, include_elements, include_tabs)


@mcp.tool()
async def docs_create_document(title: str) -> dict:
    """新しい Google ドキュメントを作成する。

    Args:
        title: ドキュメントのタイトル

    Returns:
        {
            document_id, title, revision_id, locale,
            plain_text,    # 空文字（新規作成）
            element_count  # 0
        }

    Note:
        作成後に docs_batch_update でコンテンツを追加できる。
        ドライブの特定フォルダへの配置は Drive API で対応（このツール非対応）。
    """
    raw = await _docs_post("", {"title": title})
    return _format_document(raw, include_elements=False, include_tabs=False)


@mcp.tool()
async def docs_batch_update(
    document_id: str,
    requests: list[dict],
) -> dict:
    """ドキュメントに一括更新を適用する（documents.batchUpdate）。

    requests リストに更新操作オブジェクトを列挙して送信する。
    使用可能な request 種別は docs_batch_update_help() を参照。

    Args:
        document_id: ドキュメント ID
        requests: 更新操作のリスト。
            例: [{"insertText": {"location": {"index": 1}, "text": "Hello"}}]

    Returns:
        {
            document_id,
            replies  # 各 request への応答リスト（操作によっては空 {}）
        }

    Note:
        index は 1 から始まる。ドキュメント末尾への挿入は
        docs_get_document で plain_text の長さを確認してから指定する。
    """
    raw = await _docs_post(f"/{document_id}:batchUpdate", {"requests": requests})
    return {
        "document_id": raw.get("documentId", ""),
        "replies": raw.get("replies", []),
    }


@mcp.tool()
def docs_batch_update_help() -> dict:
    """docs_batch_update で使用できる request 種別とフィールド指定の完全リファレンスを返す。

    docs_batch_update の requests を組み立てる前に参照する。

    Returns:
        カテゴリ別の request 種別リファレンス dict
    """
    return {
        "overview": {
            "desc": "requests リストに操作オブジェクトを列挙して一括送信する",
            "index_rule": (
                "index は文書内の文字位置（1 始まり）。各段落末尾の \\n も 1 文字としてカウントする"
            ),
            "segmentId": '"" で本文を指す（ヘッダー・フッターは別 ID）',
            "tabId": (
                "location / range に tabId を指定すると特定タブを対象にする。"
                "省略時は先頭タブ。tabId は docs_get_document の tabs[].tab_id で確認する"
            ),
            "range": "{ startIndex: int, endIndex: int } で範囲指定",
            "index_tip": (
                "docs_get_document の plain_text でテキスト位置を推定できる。"
                "正確な index は要素テキストを累積してカウントする"
            ),
        },
        "text_operations": {
            "insertText": {
                "desc": "指定位置にテキストを挿入する",
                "example": {"insertText": {"location": {"index": 1}, "text": "Hello\n"}},
            },
            "deleteContentRange": {
                "desc": "指定範囲のコンテンツを削除する",
                "example": {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 5}}},
            },
            "replaceAllText": {
                "desc": "ドキュメント全体のテキストを一括置換する",
                "example": {
                    "replaceAllText": {
                        "containsText": {"text": "旧テキスト", "matchCase": True},
                        "replaceText": "新テキスト",
                    }
                },
            },
        },
        "style_operations": {
            "updateTextStyle": {
                "desc": (
                    "テキストのスタイルを更新する。"
                    "fields に変更するフィールド名をカンマ区切りで指定する"
                ),
                "fields": (
                    "bold | italic | underline | strikethrough | fontSize"
                    " | foregroundColor | fontFamily | link"
                    " | baselineOffset | weightedFontFamily"
                ),
                "example": {
                    "updateTextStyle": {
                        "range": {"startIndex": 1, "endIndex": 6},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                },
            },
            "updateParagraphStyle": {
                "desc": "段落スタイル（見出しレベル・配置・インデントなど）を更新する",
                "fields": (
                    "namedStyleType | alignment | lineSpacing"
                    " | spaceAbove | spaceBelow | indentFirstLine"
                    " | indentStart | indentEnd | direction | spacingMode"
                ),
                "namedStyleType_values": (
                    "NORMAL_TEXT | HEADING_1 | HEADING_2 | HEADING_3"
                    " | HEADING_4 | HEADING_5 | HEADING_6 | TITLE | SUBTITLE"
                ),
                "alignment_values": "START | CENTER | END | JUSTIFIED",
                "example": {
                    "updateParagraphStyle": {
                        "range": {"startIndex": 1, "endIndex": 10},
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "fields": "namedStyleType",
                    }
                },
            },
        },
        "list_operations": {
            "createParagraphBullets": {
                "desc": "段落に箇条書き／番号付きリストを追加する",
                "bulletPreset_values": (
                    "BULLET_DISC_CIRCLE_SQUARE | BULLET_DIAMONDX_ARROW3D_SQUARE"
                    " | BULLET_CHECKBOX | NUMBERED_DECIMAL_ALPHA_ROMAN"
                    " | NUMBERED_DECIMAL_NESTED | NUMBERED_UPPERALPHA_UPPERROMAN_ORDINAL"
                ),
                "example": {
                    "createParagraphBullets": {
                        "range": {"startIndex": 1, "endIndex": 20},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                },
            },
            "deleteParagraphBullets": {
                "desc": "段落の箇条書きを削除する",
                "example": {"deleteParagraphBullets": {"range": {"startIndex": 1, "endIndex": 20}}},
            },
        },
        "named_range_operations": {
            "createNamedRange": {
                "desc": "名前付き範囲を作成する（後で範囲を参照するために使用）",
                "example": {
                    "createNamedRange": {
                        "name": "MyRange",
                        "range": {"startIndex": 1, "endIndex": 10},
                    }
                },
            },
            "deleteNamedRange": {
                "desc": "名前付き範囲を削除する。name または namedRangeId で指定",
                "example": {"deleteNamedRange": {"name": "MyRange"}},
            },
        },
        "table_operations": {
            "insertTable": {
                "desc": "指定位置に表を挿入する",
                "example": {"insertTable": {"rows": 3, "columns": 4, "location": {"index": 1}}},
            },
            "insertTableRow": {
                "desc": "表に行を挿入する",
                "example": {
                    "insertTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": 10},
                            "rowIndex": 1,
                            "columnIndex": 0,
                        },
                        "insertBelow": True,
                    }
                },
            },
            "deleteTableRow": {
                "desc": "表の行を削除する",
                "example": {
                    "deleteTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": 10},
                            "rowIndex": 2,
                            "columnIndex": 0,
                        }
                    }
                },
            },
            "insertTableColumn": {
                "desc": "表に列を挿入する。insertRight=True で右側に挿入",
                "example": {
                    "insertTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": 10},
                            "rowIndex": 0,
                            "columnIndex": 1,
                        },
                        "insertRight": True,
                    }
                },
            },
            "deleteTableColumn": {
                "desc": "表の列を削除する",
                "example": {
                    "deleteTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": 10},
                            "rowIndex": 0,
                            "columnIndex": 1,
                        }
                    }
                },
            },
            "mergeTableCells": {
                "desc": "セルを結合する",
                "example": {
                    "mergeTableCells": {
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": 10},
                                "rowIndex": 0,
                                "columnIndex": 0,
                            },
                            "rowSpan": 1,
                            "columnSpan": 2,
                        }
                    }
                },
            },
            "updateTableCellStyle": {
                "desc": "セルのスタイル（背景色・境界線など）を更新する",
                "fields": (
                    "backgroundColor | borderLeft | borderRight"
                    " | borderTop | borderBottom | paddingLeft | paddingRight"
                    " | paddingTop | paddingBottom | contentAlignment"
                ),
                "contentAlignment_values": "TOP | MIDDLE | BOTTOM",
            },
            "updateTableRowStyle": {
                "desc": "行の最小高さを更新する",
                "fields": "minRowHeight",
                "example": {
                    "updateTableRowStyle": {
                        "tableStartLocation": {"index": 10},
                        "rowIndices": [0],
                        "tableRowStyle": {"minRowHeight": {"magnitude": 20, "unit": "PT"}},
                        "fields": "minRowHeight",
                    }
                },
            },
        },
        "image_operations": {
            "insertInlineImage": {
                "desc": "指定位置に画像を挿入する（公開 URL が必要）",
                "example": {
                    "insertInlineImage": {
                        "uri": "https://example.com/image.png",
                        "location": {"index": 1},
                        "objectSize": {
                            "height": {"magnitude": 100, "unit": "PT"},
                            "width": {"magnitude": 100, "unit": "PT"},
                        },
                    }
                },
            },
            "deletePositionedObject": {
                "desc": "配置済みオブジェクトを削除する",
                "example": {"deletePositionedObject": {"objectId": "<object_id>"}},
            },
        },
        "tab_operations": {
            "addDocumentTab": {
                "desc": "新しいタブを作成する",
                "example": {"addDocumentTab": {"tabProperties": {"title": "新しいタブ"}}},
            },
            "deleteTab": {
                "desc": "タブとその子タブをすべて削除する",
                "example": {"deleteTab": {"tabId": "<tab_id>"}},
            },
            "updateDocumentTabProperties": {
                "desc": "タブのプロパティ（タイトルなど）を更新する",
                "fields": "title | index",
                "example": {
                    "updateDocumentTabProperties": {
                        "tabProperties": {"title": "新しいタイトル"},
                        "fields": "title",
                    }
                },
            },
        },
        "location_guide": {
            "desc": "index の調べ方",
            "method": (
                "docs_get_document の plain_text を使ってテキスト位置を推定する。"
                "各段落の text フィールドを順に累積して index を計算する"
            ),
            "note": (
                "ドキュメント全体の index は 1 始まり。"
                "各段落末尾の \\n も 1 文字としてカウントする。"
                "新規ドキュメントへの先頭挿入は index=1 を使う。"
                "特定タブへの操作は location に tabId を追加する"
                '（例: {"index": 1, "tabId": "<tab_id>"}）'
            ),
            "endIndex_tip": "ドキュメント末尾の index は plain_text の文字数 + 1 が目安",
        },
    }


@mcp.tool()
async def docs_export(
    document_id: str,
    mime_type: str = "application/pdf",
) -> dict:
    """ドキュメントを指定形式でエクスポートする（Drive API）。

    Args:
        document_id: ドキュメント ID
        mime_type: エクスポート形式
            "application/pdf" — PDF（デフォルト）
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" — DOCX
            "text/plain" — プレーンテキスト
            "text/html" — HTML

    Returns:
        text/plain, text/html の場合: { mime_type, content, size_bytes }
        バイナリの場合: { mime_type, content_base64, size_bytes }

    Note:
        10 MB を超えるエクスポートはエラーになる。
        テキスト抽出だけなら docs_get_document の plain_text フィールドを使う方が効率的。
    """
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DRIVE_BASE}/files/{document_id}/export",
            headers=_auth_headers(token),
            params={"mimeType": mime_type},
            timeout=120,
        )
        if not resp.is_success:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {resp.reason_phrase}: {detail}",
                request=resp.request,
                response=resp,
            )
        content = resp.content

    size_bytes = len(content)
    if size_bytes > _EXPORT_MAX_BYTES:
        raise ValueError(
            f"エクスポートサイズが上限 ({_EXPORT_MAX_BYTES // (1024 * 1024)} MB) を超えています"
            f" ({size_bytes / (1024 * 1024):.1f} MB)。"
            " text/plain を使用するか"
            " docs_get_document の plain_text フィールドを使用してください。"
        )

    if mime_type in ("text/plain", "text/html"):
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
async def docs_list_comments(
    document_id: str,
    include_deleted: bool = False,
) -> dict:
    """ドキュメントのコメント一覧を取得する（Drive API）。

    Args:
        document_id: ドキュメント ID
        include_deleted: 削除済みコメントを含める場合は True

    Returns:
        {
            document_id,
            comment_count,
            comments: [{
                id, content, created_time, modified_time,
                author_name, author_email, resolved, deleted,
                reply_count,
                replies: [{ id, content, created_time, author_name, author_email, action,
                            deleted }, ...]
            }, ...]
        }
    """
    raw = await _drive_get_json(
        f"/files/{document_id}/comments",
        params={
            "fields": "*",
            "includeDeleted": str(include_deleted).lower(),
            "pageSize": 100,
        },
    )
    comments = [_format_comment(c) for c in raw.get("comments", [])]
    return {
        "document_id": document_id,
        "comment_count": len(comments),
        "comments": comments,
    }


@mcp.tool()
async def docs_add_comment(
    document_id: str,
    content: str,
) -> dict:
    """ドキュメントにコメントを追加する（Drive API）。

    Args:
        document_id: ドキュメント ID
        content: コメント本文

    Returns:
        { id, content, created_time, modified_time, author_name, author_email, resolved }
    """
    raw = await _drive_post(
        f"/files/{document_id}/comments",
        {"content": content},
        params={"fields": "*"},
    )
    return _format_comment(raw)
