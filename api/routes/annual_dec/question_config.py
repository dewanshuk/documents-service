"""
Static question configuration for each declaration type.
Questions are fixed — stored here rather than in a DB table.
"""

CONFLICT_RESPONSES = {"option_b", "disagree"}


COBCE_COI_QUESTIONS = {

    "COBCE_Q1": {
        "type": "radio",
        "options": ["option_a", "option_b"],
        "required": True,
        "detail_on": ["option_b"],
        "detail_fields": ["nature_of_violation", "person_responsible"],
    },

    "COI_PREFACE": {"type": "checkbox", "required": True},
    "COI_Q1": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "OUTSIDE_ACTIVITY",
        "detail_fields": [
            "company_name", "address", "type_of_activity", "remarks",
        ],
        "form_field_map": {
            "company_name": "companyName",
            "address": "address",
            "type_of_activity": "activityType",
            "remarks": "remarks",
        },
    },
    "COI_Q2": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "DIRECTORSHIP",
        "detail_fields": [
            "company_name", "address", "type_of_directorship", "remarks",
        ],
        "form_field_map": {
            "company_name": "companyName",
            "address": "address",
            "type_of_directorship": "typeOfDirectorship",
            "remarks": "remarks",
        },
    },
    "COI_Q3": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "FINANCIAL_INTEREST",
        "detail_fields": [
            "company_name", "address", "details_of_financial_interest", "remarks",
        ],
        "form_field_map": {
            "company_name": "companyName",
            "address": "address",
            "details_of_financial_interest": "financialInterestDetails",
            "remarks": "remarks",
        },
    },
    "COI_Q4": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "REPORTING_CONFLICT",
        "detail_fields": [
            "employee_name", "name_of_relative",
            "relative_relationship", "nature_of_conflict", "remarks",
        ],
        "form_field_map": {
            "employee_name": "employeeName",
            "name_of_relative": "relativeName",
            "relative_relationship": "relationship",
            "nature_of_conflict": "natureOfConflict",
            "remarks": "remarks",
        },
    },
    "COI_Q5": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "GIFT",
        "detail_fields": [
            "dealer_supplier", "address", "details_of_gift",
            "date_received", "remarks", "employee_name",
        ],
        "form_field_map": {
            "dealer_supplier": "dealerSupplier",
            "address": "address",
            "details_of_gift": "giftDetails",
            "date_received": "dateReceived",
            "employee_name": "employeeName",
            "remarks": "remarks",
        },
    },
    "COI_Q6": {
        "type": "radio",
        "options": ["agree", "disagree"],
        "required": True,
        "detail_on": ["disagree"],
        "sub_type": "PRICE_SENSITIVE_INFO",
        "detail_fields": [
            "employee_name", "date_of_disclosure", "information_shared",
            "name_of_third_party", "address", "remarks",
        ],
        "form_field_map": {
            "employee_name": "employeeName",
            "date_of_disclosure": "dateOfDisclosure",
            "information_shared": "informationShared",
            "name_of_third_party": "thirdPartyName",
            "address": "address",
            "remarks": "remarks",
        },
    },
}


DECLARATION_CONFIGS: dict[str, dict] = {
    "COBCE/COI": COBCE_COI_QUESTIONS,
}


def get_question_config(declaration_name: str) -> dict:
    return DECLARATION_CONFIGS.get(declaration_name, {})


def get_required_question_ids(declaration_name: str) -> set[str]:
    config = get_question_config(declaration_name)
    return {qid for qid, q in config.items() if q.get("required")}


def check_has_conflict(responses: list[dict]) -> bool:
    return any(
        r.get("response") in CONFLICT_RESPONSES for r in responses
    )


def validate_submission_responses(
    responses: list[dict], declaration_name: str
) -> list[str]:
    """Validate all required questions on submit. Draft may omit or null answers."""
    config = get_question_config(declaration_name)
    errors: list[str] = []

    if not config:
        for resp in responses:
            if resp.get("response") in CONFLICT_RESPONSES:
                if not resp.get("declaration_details"):
                    errors.append(
                        f"{resp['question_id']}: At least one detail row required"
                    )
        return errors

    by_qid = {r["question_id"]: r for r in responses}
    required = get_required_question_ids(declaration_name)
    missing = {
        qid for qid in required
        if not by_qid.get(qid) or by_qid[qid].get("response") is None
    }
    if missing:
        errors.append(f"Missing required questions: {', '.join(sorted(missing))}")

    for resp in responses:
        qid = resp["question_id"]
        q_config = config.get(qid)
        if not q_config:
            continue

        response_val = resp.get("response")
        if response_val is None:
            continue

        if q_config["type"] == "radio":
            valid_opts = q_config.get("options", [])
            if response_val not in valid_opts:
                errors.append(
                    f"{qid}: Invalid response '{response_val}', "
                    f"expected one of {valid_opts}"
                )
            elif response_val in q_config.get("detail_on", []):
                details = resp.get("declaration_details")
                if not details:
                    errors.append(
                        f"{qid}: At least one detail row required "
                        f"when '{response_val}' is selected"
                    )

        elif q_config["type"] == "checkbox" and response_val != "checked":
            errors.append(f"{qid}: Must be 'checked'")

    return errors
