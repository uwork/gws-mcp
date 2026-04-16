FROM python:3.12-slim

WORKDIR /app

# 依存関係ファイルをコピーしてインストール（キャッシュ効率化）
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# アプリケーションコードをコピー
COPY src/ ./src/
COPY src/static/ ./static/

# Cloud Run は PORT 環境変数でポートを指定する
ENV PORT=8080
EXPOSE 8080

CMD ["python", "src/main.py"]
