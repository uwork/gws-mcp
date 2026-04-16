FROM python:3.12-slim

WORKDIR /app

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依存関係ファイルをコピーしてインストール（キャッシュ効率化）
COPY pyproject.toml .
RUN uv pip install --system -e . --no-cache

# アプリケーションコードをコピー
COPY src/ ./src/
COPY src/static/ ./static/

# Cloud Run は PORT 環境変数でポートを指定する
ENV PORT=8080
EXPOSE 8080

CMD ["python", "src/main.py"]
