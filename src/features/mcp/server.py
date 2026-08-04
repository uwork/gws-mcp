"""FastMCP ツール定義（ping）および全ツールモジュールの登録。"""

from features.mcp.instance import mcp  # noqa: F401  (再エクスポート用)


@mcp.tool()
def ping() -> str:
    """サーバーの疎通確認を行う。正常稼働中なら 'pong' を返す。"""
    return "pong"


# 各サービスのツールを登録（インポートにより @mcp.tool() デコレータが実行される）
import features.mcp.docs  # noqa: E402, F401
import features.mcp.drive  # noqa: E402, F401
import features.mcp.sheets  # noqa: E402, F401
import features.mcp.slides  # noqa: E402, F401
