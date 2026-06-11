import logging
import os

logging.basicConfig(level=logging.WARN)


def _secret_from_env(key: str) -> str | None:
    env_key = key.replace("-", "_").upper()
    return os.getenv(env_key)


def list_azure_secrets():
    return []


async def get_azure_secret(key: str):
    return _secret_from_env(key)


def get_secret_sync(key: str):
    return _secret_from_env(key)
