"""Google Cloud Secret Manager へのアクセス。"""

from google.cloud import secretmanager

from config import PROJECT_ID

_cache: dict[str, str] = {}


def get_secret(secret_name: str) -> str:
    """Secret Manager からシークレットを取得する。結果はメモリにキャッシュ。"""
    if secret_name in _cache:
        return _cache[secret_name]
    client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": resource})
    value = response.payload.data.decode("utf-8").strip()
    _cache[secret_name] = value
    return value
