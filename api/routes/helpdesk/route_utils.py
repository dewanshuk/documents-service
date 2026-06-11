import json
from typing import Any, Optional
from fastapi.responses import JSONResponse
from utils.loggers import log_record


def log_and_json_response(
    staff_id: Optional[str],
    request_params: Any,
    endpoint: str,
    request_type: str,
    status_code: int,
    response_content: Any,
) -> JSONResponse:
    """Log the API call parameters and response, then return a JSONResponse."""
    try:
        response_body = (
            response_content
            if isinstance(response_content, (str, bytes))
            else json.dumps(response_content, default=str)
        )
    except Exception:
        response_body = str(response_content)

    try:
        log_record(staff_id, request_params, endpoint, request_type, status_code, response_body)
    except Exception:
        pass

    return JSONResponse(content=response_content, status_code=status_code)
