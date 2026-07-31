TAG_HEALTH = "Health"
TAG_COMMON = "Compliance Helpdesk"
TAG_QUERY = "Query"
TAG_COMPLAINT = "Complaint"
TAG_GIFT = "Gift Declaration"
TAG_SELF_DECLARATION = "Self Declaration"
TAG_ADMINS = "Admins"
TAG_ANNUAL = "Annual Declarations"
TAG_RECENT_ACTIVITY = "Recent Activity"

OPENAPI_TAGS = [
    {
        "name": TAG_HEALTH,
        "description": "Service health checks.",
    },
    {
        "name": TAG_COMMON,
        "description": (
            "Shared helpdesk APIs: dashboard, export, conversation, respond, close, "
            "and file downloads."
        ),
    },
    {
        "name": TAG_QUERY,
        "description": "Raise and view compliance queries.",
    },
    {
        "name": TAG_COMPLAINT,
        "description": "Raise complaints.",
    },
    {
        "name": TAG_GIFT,
        "description": "Raise gift declarations.",
    },
    {
        "name": TAG_SELF_DECLARATION,
        "description": "COBCE and COI self-declarations.",
    },
    {
        "name": TAG_ADMINS,
        "description": "List compliance leads and assign admins to records.",
    },
    {
        "name": TAG_ANNUAL,
        "description": "Annual declaration cycles and user submissions.",
    },
    {
        "name": TAG_RECENT_ACTIVITY,
        "description": (
            "Recently accessed compliance records for the home page, including "
            "queries, complaints, gift/self declarations, and annual declarations."
        ),
    },
]
