import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "compliance-helpdesk")

SECURITY_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'",
}

POSTGRES_DB = os.getenv("POSTGRES_DB", "auth-flow")
