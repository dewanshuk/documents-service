import os

ENV = os.getenv("ENV", "local")
KV_URL = os.getenv("AZURE_KEY_VAULT_URL", "")

SELF_DECL_DUE_DAYS = 7
DEFAULT_PAGE_SIZE = 10

TYPE_FILTER_MAP = {
    "annual_declarations": "Annual Declaration",
    "self_declarations": "Self Declaration",
    "query": "Query",
    "gift": "Gift Declaration",
    "complaint": "Complaint",
}

EXPORT_COLUMNS = [
    "Request ID",
    "Type",
    "Sub Type",
    "Response Status",
    "Overall Status",
    "Updated On",
    "Response Due Date",
    "Updated By",
]
