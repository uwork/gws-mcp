"""Google Sheets API クライアントおよび MCP ツール定義。

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

_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


async def _get_token() -> str:
    """現在のユーザーの有効な Google アクセストークンを取得する。"""
    user_id = get_current_user_id()
    if user_id is None:
        raise PermissionError("認証が必要です。先に OAuth 認証を完了してください。")
    token = await get_valid_access_token(user_id)
    if token is None:
        raise PermissionError("アクセストークンの取得に失敗しました。再認証してください。")
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _api_get(path: str, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_SHEETS_BASE}{path}",
            headers=_auth_headers(token),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _api_post(path: str, body: dict) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_SHEETS_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _api_put(path: str, body: dict, params: dict | None = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{_SHEETS_BASE}{path}",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# AI フレンドリー変換ヘルパー
# ---------------------------------------------------------------------------


def _format_values_response(raw: dict) -> dict:
    """values.get / values.batchGet のレスポンスを整形する。"""
    values: list[list[Any]] = raw.get("values", [])
    row_count = len(values)
    col_count = max((len(r) for r in values), default=0)

    result: dict[str, Any] = {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "range": raw.get("range", ""),
        "major_dimension": raw.get("majorDimension", "ROWS"),
        "row_count": row_count,
        "column_count": col_count,
        "values": values,
    }

    # 1 行目がヘッダーらしければ records 形式も付ける
    if row_count >= 2:
        headers = [str(h) for h in values[0]]
        records = []
        for row in values[1:]:
            rec: dict[str, Any] = {}
            for i, h in enumerate(headers):
                rec[h] = row[i] if i < len(row) else ""
            records.append(rec)
        result["headers"] = headers
        result["records"] = records

    return result


def _format_sheet_properties(sp: dict) -> dict:
    """sheetProperties オブジェクトを整形する。"""
    grid = sp.get("gridProperties", {})
    return {
        "sheet_id": sp.get("sheetId", 0),
        "title": sp.get("title", ""),
        "index": sp.get("index", 0),
        "sheet_type": sp.get("sheetType", "GRID"),
        "hidden": sp.get("hidden", False),
        "tab_color_style": sp.get("tabColorStyle"),
        "row_count": grid.get("rowCount"),
        "column_count": grid.get("columnCount"),
        "frozen_row_count": grid.get("frozenRowCount", 0),
        "frozen_column_count": grid.get("frozenColumnCount", 0),
        "hide_gridlines": grid.get("hideGridlines", False),
    }


def _format_spreadsheet_metadata(raw: dict) -> dict:
    """spreadsheets.get のレスポンスを整形する。"""
    props = raw.get("spreadsheetProperties", {})
    sheets_raw = raw.get("sheets", [])
    named_ranges = [
        {
            "name": nr.get("name", ""),
            "named_range_id": nr.get("namedRangeId", ""),
            "range": _format_grid_range(nr.get("range", {})),
        }
        for nr in raw.get("namedRanges", [])
    ]

    sheets = []
    for s in sheets_raw:
        sp = _format_sheet_properties(s.get("properties", {}))
        # banded ranges: ID と範囲を返す（deleteBanding に必要）
        banded_ranges_raw = s.get("bandedRanges", [])
        sp["banded_ranges"] = [
            {
                "banded_range_id": br.get("bandedRangeId"),
                "range": _format_grid_range(br.get("range", {})),
            }
            for br in banded_ranges_raw
        ]
        sp["banded_ranges_count"] = len(banded_ranges_raw)
        sp["conditional_formats_count"] = len(s.get("conditionalFormats", []))
        sp["charts_count"] = len(s.get("charts", []))
        sp["merges_count"] = len(s.get("merges", []))
        sp["filter_views_count"] = len(s.get("filterViews", []))
        sheets.append(sp)

    return {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "spreadsheet_url": raw.get("spreadsheetUrl", ""),
        "title": props.get("title", ""),
        "locale": props.get("locale", ""),
        "time_zone": props.get("timeZone", ""),
        "auto_recalc": props.get("autoRecalc", ""),
        "default_format": _format_cell_format(props.get("defaultFormat", {})),
        "sheets": sheets,
        "named_ranges": named_ranges,
        "sheet_count": len(sheets),
    }


def _format_grid_range(gr: dict) -> dict:
    return {
        "sheet_id": gr.get("sheetId"),
        "start_row": gr.get("startRowIndex"),
        "end_row": gr.get("endRowIndex"),
        "start_column": gr.get("startColumnIndex"),
        "end_column": gr.get("endColumnIndex"),
    }


def _format_cell_format(cf: dict) -> dict:
    if not cf:
        return {}
    bg = cf.get("backgroundColor", {})
    borders = cf.get("borders", {})
    padding = cf.get("padding", {})
    tf = cf.get("textFormat", {})
    return {
        "background_color": bg if bg else None,
        "horizontal_alignment": cf.get("horizontalAlignment"),
        "vertical_alignment": cf.get("verticalAlignment"),
        "wrap_strategy": cf.get("wrapStrategy"),
        "text_direction": cf.get("textDirection"),
        "borders": borders if borders else None,
        "padding": padding if padding else None,
        "number_format": cf.get("numberFormat"),
        "text_format": {
            "bold": tf.get("bold"),
            "italic": tf.get("italic"),
            "underline": tf.get("underline"),
            "strikethrough": tf.get("strikethrough"),
            "font_size": tf.get("fontSize"),
            "font_family": tf.get("fontFamily"),
            "foreground_color": tf.get("foregroundColorStyle"),
        } if tf else None,
    }


# ---------------------------------------------------------------------------
# MCP ツール定義
# ---------------------------------------------------------------------------


@mcp.tool()
async def sheets_get_values(
    spreadsheet_id: str,
    range: str,
    major_dimension: str = "ROWS",
    value_render_option: str = "FORMATTED_VALUE",
    date_time_render_option: str = "FORMATTED_STRING",
) -> dict:
    """スプレッドシートの指定範囲のセル値を取得する。

    Args:
        spreadsheet_id: スプレッドシート ID（URL の /d/<ID>/ 部分）
        range: A1 記法の範囲。例: "Sheet1!A1:C10", "A:Z", "Sheet1"
        major_dimension: データの主軸 "ROWS"（デフォルト）または "COLUMNS"
        value_render_option: セル値の形式。
            "FORMATTED_VALUE"（表示値, デフォルト）
            "UNFORMATTED_VALUE"（生の値）
            "FORMULA"（数式）
        date_time_render_option: 日時の形式。
            "FORMATTED_STRING"（表示文字列, デフォルト）
            "SERIAL_NUMBER"（シリアル数値）

    Returns:
        {
            spreadsheet_id, range, major_dimension,
            row_count, column_count,
            values: [[...], ...],            # 生の 2D 配列
            headers: [...],                   # 1 行目がヘッダーの場合のみ
            records: [{header: value, ...}]   # ヘッダーあり時のレコード形式
        }
    """
    raw = await _api_get(
        f"/{spreadsheet_id}/values/{range}",
        params={
            "majorDimension": major_dimension,
            "valueRenderOption": value_render_option,
            "dateTimeRenderOption": date_time_render_option,
        },
    )
    return _format_values_response(raw)


@mcp.tool()
async def sheets_batch_get_values(
    spreadsheet_id: str,
    ranges: list[str],
    major_dimension: str = "ROWS",
    value_render_option: str = "FORMATTED_VALUE",
) -> dict:
    """複数範囲のセル値を一度のリクエストで取得する。

    Args:
        spreadsheet_id: スプレッドシート ID
        ranges: A1 記法の範囲リスト。例: ["Sheet1!A1:C10", "Sheet2!A:B"]
        major_dimension: "ROWS" または "COLUMNS"
        value_render_option: "FORMATTED_VALUE" / "UNFORMATTED_VALUE" / "FORMULA"

    Returns:
        {
            spreadsheet_id,
            value_ranges: [  # 各範囲の結果
                {range, row_count, column_count, values, headers?, records?},
                ...
            ]
        }
    """
    params: dict[str, Any] = {
        "majorDimension": major_dimension,
        "valueRenderOption": value_render_option,
    }
    # httpx では同名キー複数は params にリスト渡し
    params["ranges"] = ranges

    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_SHEETS_BASE}/{spreadsheet_id}/values:batchGet",
            headers=_auth_headers(token),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()

    return {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "value_ranges": [
            _format_values_response(vr) for vr in raw.get("valueRanges", [])
        ],
    }


@mcp.tool()
async def sheets_get_spreadsheet(
    spreadsheet_id: str,
    ranges: list[str] | None = None,
    include_grid_data: bool = False,
) -> dict:
    """スプレッドシートのメタデータ（シート一覧・プロパティ）を取得する。

    Args:
        spreadsheet_id: スプレッドシート ID
        ranges: グリッドデータを取得したい範囲のリスト（include_grid_data=True 時のみ意味を持つ）
        include_grid_data: True にするとセルの値・書式も含む（大きなシートは注意）

    Returns:
        {
            spreadsheet_id, spreadsheet_url, title, locale, time_zone,
            auto_recalc, default_format,
            sheet_count,
            sheets: [{
                sheet_id, title, index, sheet_type, hidden,
                row_count, column_count,
                frozen_row_count, frozen_column_count, hide_gridlines,
                tab_color_style,
                banded_ranges: [{banded_range_id, range}],  # deleteBanding に使う ID を含む
                banded_ranges_count, conditional_formats_count,
                charts_count, merges_count, filter_views_count
            }, ...],
            named_ranges: [{name, named_range_id, range}, ...]
        }
    """
    params: dict[str, Any] = {"includeGridData": str(include_grid_data).lower()}
    if ranges:
        params["ranges"] = ranges

    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_SHEETS_BASE}/{spreadsheet_id}",
            headers=_auth_headers(token),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()

    return _format_spreadsheet_metadata(raw)


@mcp.tool()
async def sheets_create_spreadsheet(
    title: str,
    sheet_titles: list[str] | None = None,
    locale: str = "ja_JP",
    time_zone: str = "Asia/Tokyo",
) -> dict:
    """新しいスプレッドシートを作成する。

    Args:
        title: スプレッドシートのタイトル
        sheet_titles: 作成するシートのタイトルリスト。省略時は "Sheet1" のみ作成
        locale: ロケール文字列（例: "ja_JP", "en_US"）
        time_zone: タイムゾーン（例: "Asia/Tokyo", "America/New_York"）

    Returns:
        {
            spreadsheet_id, spreadsheet_url, title,
            sheets: [{sheet_id, title, index, row_count, column_count}, ...]
        }
    """
    body: dict[str, Any] = {
        "properties": {
            "title": title,
            "locale": locale,
            "timeZone": time_zone,
        }
    }
    if sheet_titles:
        body["sheets"] = [
            {"properties": {"title": t, "index": i}} for i, t in enumerate(sheet_titles)
        ]

    raw = await _api_post("", body)
    result = _format_spreadsheet_metadata(raw)
    return result


@mcp.tool()
async def sheets_update_values(
    spreadsheet_id: str,
    range: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
    include_values_in_response: bool = False,
) -> dict:
    """指定範囲にセル値を書き込む（既存値を上書き）。

    Args:
        spreadsheet_id: スプレッドシート ID
        range: 書き込み先の A1 記法範囲。例: "Sheet1!A1:C3"
        values: 書き込む 2D 配列。例: [["Name","Age"], ["Alice",30]]
        value_input_option: 値の解釈方法。
            "USER_ENTERED"（ユーザー入力と同様に数式・型を解釈, デフォルト）
            "RAW"（文字列として格納）
        include_values_in_response: True にすると書き込み後の値をレスポンスに含む

    Returns:
        {
            spreadsheet_id, updated_range,
            updated_rows, updated_columns, updated_cells,
            updated_values?  # include_values_in_response=True 時のみ
        }
    """
    params = {
        "valueInputOption": value_input_option,
        "includeValuesInResponse": str(include_values_in_response).lower(),
    }
    body = {"range": range, "majorDimension": "ROWS", "values": values}
    raw = await _api_put(f"/{spreadsheet_id}/values/{range}", body, params)

    result: dict[str, Any] = {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "updated_range": raw.get("updatedRange", ""),
        "updated_rows": raw.get("updatedRows", 0),
        "updated_columns": raw.get("updatedColumns", 0),
        "updated_cells": raw.get("updatedCells", 0),
    }
    if include_values_in_response and "updatedData" in raw:
        result["updated_values"] = _format_values_response(raw["updatedData"])
    return result


@mcp.tool()
async def sheets_append_values(
    spreadsheet_id: str,
    range: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
    insert_data_option: str = "INSERT_ROWS",
) -> dict:
    """テーブルの末尾に行を追記する。

    指定範囲内のデータを検索し、最後の行の後ろに追記する。
    ヘッダー行の下から書き込みたい場合は range に "Sheet1!A1" などを指定する。

    Args:
        spreadsheet_id: スプレッドシート ID
        range: データ検索の基点となる範囲（A1 記法）
        values: 追記する 2D 配列
        value_input_option: "USER_ENTERED"（デフォルト）または "RAW"
        insert_data_option: "INSERT_ROWS"（新規行挿入, デフォルト）または "OVERWRITE"（上書き）

    Returns:
        {
            spreadsheet_id, table_range,
            updated_range, updated_rows, updated_columns, updated_cells
        }
    """
    params = {
        "valueInputOption": value_input_option,
        "insertDataOption": insert_data_option,
    }
    body = {"majorDimension": "ROWS", "values": values}
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_SHEETS_BASE}/{spreadsheet_id}/values/{range}:append",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()

    updates = raw.get("updates", {})
    return {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "table_range": raw.get("tableRange", ""),
        "updated_range": updates.get("updatedRange", ""),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_columns": updates.get("updatedColumns", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }


@mcp.tool()
async def sheets_clear_values(
    spreadsheet_id: str,
    range: str,
) -> dict:
    """指定範囲のセル値をクリアする（書式は保持）。

    Args:
        spreadsheet_id: スプレッドシート ID
        range: クリアする A1 記法範囲

    Returns:
        {spreadsheet_id, cleared_range}
    """
    token = await _get_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_SHEETS_BASE}/{spreadsheet_id}/values/{range}:clear",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()

    return {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "cleared_range": raw.get("clearedRange", ""),
    }


@mcp.tool()
async def sheets_batch_update(
    spreadsheet_id: str,
    requests: list[dict],
    include_spreadsheet_in_response: bool = False,
) -> dict:
    """スプレッドシートの構造・書式・シート操作を一括で更新する（spreadsheets.batchUpdate）。

    requests リストに更新操作オブジェクトを列挙して送信する。
    使用可能な request 種別・フィールド指定の書き方は sheets_batch_update_help() を参照。

    Args:
        spreadsheet_id: スプレッドシート ID
        requests: 更新操作のリスト。例: [{"addSheet": {"properties": {"title": "新シート"}}}]
        include_spreadsheet_in_response: True にするとレスポンスに更新後のメタデータを含む

    Returns:
        {
            spreadsheet_id,
            replies: [...],          # 各 request への応答（操作によっては空 {}）
            updated_spreadsheet?     # include_spreadsheet_in_response=True 時のみ
        }
    """
    body: dict[str, Any] = {
        "requests": requests,
        "includeSpreadsheetInResponse": include_spreadsheet_in_response,
    }
    raw = await _api_post(f"/{spreadsheet_id}:batchUpdate", body)

    result: dict[str, Any] = {
        "spreadsheet_id": raw.get("spreadsheetId", ""),
        "replies": raw.get("replies", []),
    }
    if include_spreadsheet_in_response and "updatedSpreadsheet" in raw:
        result["updated_spreadsheet"] = _format_spreadsheet_metadata(
            raw["updatedSpreadsheet"]
        )
    return result


@mcp.tool()
def sheets_batch_update_help() -> dict:
    """sheets_batch_update で使用できる request 種別とフィールド指定の完全リファレンスを返す。

    sheets_batch_update の requests を組み立てる前に参照する。
    """
    return {
        "overview": (
            "requests は操作オブジェクトのリスト。"
            "各オブジェクトはキーが操作名、値が操作の詳細。"
            "fields フィールドは FieldMask 形式で更新対象を限定する（省略すると全フィールド更新）。"
        ),
        "sheet_operations": {
            "addSheet": {
                "desc": "新しいシートを追加する",
                "example": {"addSheet": {"properties": {"title": "新シート名"}}},
            },
            "deleteSheet": {
                "desc": "シートを削除する",
                "example": {"deleteSheet": {"sheetId": 0}},
            },
            "duplicateSheet": {
                "desc": "シートを複製する",
                "example": {
                    "duplicateSheet": {
                        "sourceSheetId": 0,
                        "insertSheetIndex": 1,
                        "newSheetName": "コピー",
                    }
                },
            },
            "updateSheetProperties": {
                "desc": "シートのプロパティを更新する（タイトル・タブ色・非表示など）",
                "fields": (
                    "title | hidden | tabColorStyle"
                    " | gridProperties.frozenRowCount"
                    " | gridProperties.frozenColumnCount"
                    " | gridProperties.hideGridlines"
                ),
                "example": {
                    "updateSheetProperties": {
                        "properties": {"sheetId": 0, "title": "名前変更"},
                        "fields": "title",
                    }
                },
            },
            "updateSpreadsheetProperties": {
                "desc": "スプレッドシート全体のプロパティを更新する",
                "fields": "title | locale | timeZone | autoRecalc | defaultFormat",
                "example": {
                    "updateSpreadsheetProperties": {
                        "properties": {"title": "新タイトル"},
                        "fields": "title",
                    }
                },
            },
        },
        "dimension_operations": {
            "insertDimension": {
                "desc": "行または列を挿入する",
                "example": {
                    "insertDimension": {
                        "range": {
                            "sheetId": 0,
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": 3,
                        },
                        "inheritFromBefore": False,
                    }
                },
            },
            "deleteDimension": {
                "desc": "行または列を削除する",
                "example": {
                    "deleteDimension": {
                        "range": {
                            "sheetId": 0,
                            "dimension": "COLUMNS",
                            "startIndex": 2,
                            "endIndex": 4,
                        }
                    }
                },
            },
            "moveDimension": {
                "desc": "行または列を移動する",
                "example": {
                    "moveDimension": {
                        "source": {
                            "sheetId": 0,
                            "dimension": "ROWS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "destinationIndex": 5,
                    }
                },
            },
            "autoResizeDimensions": {
                "desc": "列幅または行高をコンテンツに合わせて自動調整する",
                "example": {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": 0,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 5,
                        }
                    }
                },
            },
            "updateDimensionProperties": {
                "desc": "列幅・行高・表示/非表示などのプロパティを更新する",
                "fields": "pixelSize | hiddenByUser | developerMetadata",
                "example": {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": 0,
                            "dimension": "ROWS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"pixelSize": 40},
                        "fields": "pixelSize",
                    }
                },
            },
        },
        "cell_operations": {
            "repeatCell": {
                "desc": "指定範囲のセルに同じ書式や値を一括適用する",
                "fields": "userEnteredValue | userEnteredFormat | note | dataValidation",
                "example": {
                    "repeatCell": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {
                                    "red": 0.9,
                                    "green": 0.9,
                                    "blue": 0.9,
                                },
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,backgroundColor)",
                    }
                },
            },
            "updateCells": {
                "desc": "セルの値・書式を低レベルで一括更新する（行 × 列の完全制御）",
                "note": "rows に CellData の配列を渡す。fields で更新する属性を限定する。",
            },
            "mergeCells": {
                "desc": "セルを結合する",
                "merge_types": "MERGE_ALL | MERGE_COLUMNS | MERGE_ROWS",
                "example": {
                    "mergeCells": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                },
            },
            "unmergeCells": {
                "desc": "セルの結合を解除する",
                "example": {
                    "unmergeCells": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        }
                    }
                },
            },
            "updateBorders": {
                "desc": "セル範囲の罫線を更新する",
                "border_style": (
                    "DOTTED | DASHED | SOLID | SOLID_MEDIUM | SOLID_THICK | DOUBLE | NONE"
                ),
                "example": {
                    "updateBorders": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 5,
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "bottom": {"style": "SOLID", "color": {"red": 0, "green": 0, "blue": 0}},
                    }
                },
            },
            "sortRange": {
                "desc": "指定範囲の行をソートする",
                "example": {
                    "sortRange": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 1,
                            "endRowIndex": 100,
                            "startColumnIndex": 0,
                            "endColumnIndex": 5,
                        },
                        "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}],
                    }
                },
            },
            "copyPaste": {
                "desc": "セル範囲をコピーして別の場所に貼り付ける",
                "paste_type": (
                    "PASTE_NORMAL | PASTE_VALUES | PASTE_FORMAT | PASTE_NO_BORDERS | PASTE_FORMULA"
                ),
            },
            "cutPaste": {
                "desc": "セル範囲を切り取って別の場所に貼り付ける",
                "paste_type": "PASTE_NORMAL | PASTE_VALUES | PASTE_FORMAT",
            },
        },
        "named_ranges": {
            "addNamedRange": {
                "desc": "名前付き範囲を追加する",
                "example": {
                    "addNamedRange": {
                        "namedRange": {
                            "name": "myRange",
                            "range": {
                                "sheetId": 0,
                                "startRowIndex": 0,
                                "endRowIndex": 10,
                                "startColumnIndex": 0,
                                "endColumnIndex": 3,
                            },
                        }
                    }
                },
            },
            "updateNamedRange": {"desc": "名前付き範囲を更新する", "fields": "name | range"},
            "deleteNamedRange": {
                "desc": "名前付き範囲を削除する",
                "example": {"deleteNamedRange": {"namedRangeId": "<namedRangeId>"}},
            },
        },
        "banding": {
            "addBanding": {
                "desc": "交互の背景色（banded range）を追加する",
                "example": {
                    "addBanding": {
                        "bandedRange": {
                            "range": {
                                "sheetId": 0,
                                "startRowIndex": 0,
                                "endRowIndex": 10,
                                "startColumnIndex": 0,
                                "endColumnIndex": 5,
                            },
                            "rowProperties": {
                                "headerColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                                "firstBandColor": {"red": 1, "green": 1, "blue": 1},
                                "secondBandColor": {"red": 0.9, "green": 0.95, "blue": 1},
                            },
                        }
                    }
                },
            },
            "updateBanding": {
                "desc": "既存の banded range を更新する",
                "fields": "range | rowProperties | columnProperties",
                "example": {
                    "updateBanding": {
                        "bandedRange": {"bandedRangeId": 0},
                        "fields": "rowProperties",
                    }
                },
            },
            "deleteBanding": {
                "desc": (
                    "交互の背景色（banded range）を削除する。"
                    "bandedRangeId は sheets_get_spreadsheet の"
                    " banded_ranges[].banded_range_id で取得する。"
                ),
                "example": {"deleteBanding": {"bandedRangeId": 0}},
            },
        },
        "conditional_format": {
            "addConditionalFormatRule": {"desc": "条件付き書式ルールを追加する"},
            "updateConditionalFormatRule": {"desc": "条件付き書式ルールを更新する"},
            "deleteConditionalFormatRule": {"desc": "条件付き書式ルールを削除する"},
        },
        "filter_and_protection": {
            "setBasicFilter": {"desc": "シートにオートフィルターを設定する"},
            "clearBasicFilter": {"desc": "オートフィルターを削除する"},
            "addProtectedRange": {"desc": "編集保護範囲を追加する"},
            "updateProtectedRange": {"desc": "編集保護範囲を更新する"},
            "deleteProtectedRange": {"desc": "編集保護範囲を削除する"},
        },
        "grid_range_format": {
            "desc": "範囲指定の共通形式",
            "fields": {
                "sheetId": "int — シート ID（sheets_get_spreadsheet で確認）",
                "startRowIndex": "int — 開始行（0 始まり、含む）",
                "endRowIndex": "int — 終了行（0 始まり、含まない）",
                "startColumnIndex": "int — 開始列（0 始まり、含む）",
                "endColumnIndex": "int — 終了列（0 始まり、含まない）",
            },
        },
    }
