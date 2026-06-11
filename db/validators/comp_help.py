from datetime import datetime
from typing import List, Optional, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, StringConstraints
from pydantic import BaseModel, Field
from enum import Enum
from fastapi.responses import JSONResponse

class QueryType(str, Enum):
    COBCE = "COBCE"
    COI = "COI"
    ComplyShield = "ComplyShield"
    Gift = "Gift"
    R518 = "R5.18"
    Other = "Other"


class RaiseQueryRequest(BaseModel):
    queryType: QueryType
    title: str = Field(...)
    description: str = Field(...)


class RespondRequest(BaseModel):
    message: str = Field(...)


def validate_coi_form(subType, formData):
    def check(field, limit, required=True):
        if required and field not in formData:
            return JSONResponse(content={"error": f"{field} is required"}, status_code=400)

        if field in formData:
            if len(str(formData[field]).split()) > limit:
                return JSONResponse(content={"error": f"{field} exceeds {limit} words"}, status_code=400)

    if subType == "OUTSIDE_ACTIVITY":
        check("companyName", 50)
        check("address", 50)
        check("activityType", 50)
        check("remarks", 100)

    elif subType == "DIRECTORSHIP":
        check("companyName", 50)
        check("address", 50)
        check("typeOfDirectorship", 50)
        check("remarks", 100)

    elif subType == "FINANCIAL_INTEREST":
        check("companyName", 50)
        check("address", 50)
        check("financialInterestDetails", 50)
        check("remarks", 100)

    elif subType == "REPORTING_CONFLICT":
        check("employeeName", 25)
        check("relativeName", 25)
        check("relationship", 25)
        check("natureOfConflict", 50)
        check("remarks", 100)

    elif subType == "GIFT":
        check("dealerSupplier", 50)
        check("address", 50)
        check("giftDetails", 50)
        check("dateReceived", 10)
        check("employeeName", 25)
        check("remarks", 100)

    elif subType == "PRICE_SENSITIVE_INFO":
        check("employeeName", 25)
        check("dateOfDisclosure", 10)
        check("informationShared", 50)
        check("thirdPartyName", 50)
        check("address", 50)
        check("remarks", 100)

    elif subType == "OTHERS":
        check("description", 200)

