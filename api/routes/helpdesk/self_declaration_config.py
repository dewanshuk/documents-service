"""
Form metadata for standalone self-declarations (frontend renders from this).
Annual declaration questions live in api/routes/annual_dec/question_config.py.
"""

COBCE_SELF_DECLARATION = {
    "declaration_type": "cobce",
    "allows_multiple_rows": True,
    "row_fields": [
        {"key": "nature_of_violation", "label": "Nature of violation", "required": True},
        {"key": "person_responsible", "label": "Person responsible", "required": True},
    ],
}

COI_SELF_DECLARATION_QUESTIONS = [
    {
        "question_id": "COI_Q1",
        "sub_type": "OUTSIDE_ACTIVITY",
        "label": "Outside activity",
        "fields": ["companyName", "address", "activityType", "remarks"],
    },
    {
        "question_id": "COI_Q2",
        "sub_type": "DIRECTORSHIP",
        "label": "Directorship",
        "fields": ["companyName", "address", "typeOfDirectorship", "remarks"],
    },
    {
        "question_id": "COI_Q3",
        "sub_type": "FINANCIAL_INTEREST",
        "label": "Financial interest",
        "fields": ["companyName", "address", "financialInterestDetails", "remarks"],
    },
    {
        "question_id": "COI_Q4",
        "sub_type": "REPORTING_CONFLICT",
        "label": "Reporting conflict",
        "fields": [
            "employeeName",
            "relativeName",
            "relationship",
            "natureOfConflict",
            "remarks",
        ],
    },
    {
        "question_id": "COI_Q5",
        "sub_type": "GIFT",
        "label": "Gift",
        "fields": [
            "dealerSupplier",
            "address",
            "giftDetails",
            "dateReceived",
            "employeeName",
            "remarks",
        ],
    },
    {
        "question_id": "COI_Q6",
        "sub_type": "PRICE_SENSITIVE_INFO",
        "label": "Price sensitive information",
        "fields": [
            "employeeName",
            "dateOfDisclosure",
            "informationShared",
            "thirdPartyName",
            "address",
            "remarks",
        ],
    },
]

COI_SELF_DECLARATION = {
    "declaration_type": "coi",
    "select_one_question": True,
    "questions": COI_SELF_DECLARATION_QUESTIONS,
}

SELF_DECLARATION_FORM_CONFIG = {
    "cobce": COBCE_SELF_DECLARATION,
    "coi": COI_SELF_DECLARATION,
}
