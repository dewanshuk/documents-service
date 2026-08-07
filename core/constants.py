import os

ENV = os.getenv("ENV", "local")
KV_URL = os.getenv("AZURE_KEY_VAULT_URL", "")
BASE_URL = os.getenv("BASE_URL", "https://compliance.com")

SELF_DECL_DUE_DAYS = 7
RESPONSE_DUE_DAYS = 2  # working days (Mon-Fri)
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
    "Pending At",
    "Closed At",
    "Closed By",
]

RECORD_TYPE_LEAD_MAP = {
    "gift declaration": "is_cobce_coi_gift_lead",
    "complaint": "is_complaint_lead",
    "query": "is_query_lead",
    "annual declaration": "is_knowledge_hub_admin",
    "self declaration": "is_cobce_coi_gift_lead",
}
