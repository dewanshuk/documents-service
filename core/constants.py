import os

ENV = os.getenv("ENV", "local")
KV_URL = os.getenv("AZURE_KEY_VAULT_URL", "")
