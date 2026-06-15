def _build(status, error, message, details=None, path=""):
    return {"status": status, "error": error, "message": message, "details": details or [], "path": path}


def validation(details, path):
    return _build(400, "VALIDATION_ERROR", "Invalid request data.", details, path)


def invalid_json(path):
    return _build(400, "INVALID_JSON", "Request body is not valid JSON.", [], path)


def invalid_id(path):
    return _build(400, "INVALID_ID", "ID must be a valid UUID.", [], path)


def unauthorized(path):
    return _build(401, "UNAUTHORIZED", "Authentication is required, or the session is invalid or expired.", [], path)


def forbidden(message, path):
    return _build(403, "FORBIDDEN", message or "You do not have permission to perform this operation.", [], path)


def not_found(resource, path):
    return _build(404, "NOT_FOUND", f"{resource} not found.", [], path)


def route_not_found(path):
    return _build(404, "ROUTE_NOT_FOUND", "No route matches this request.", [], path)


def method_not_allowed(allowed, path):
    return _build(405, "METHOD_NOT_ALLOWED", f"Method not allowed. Allowed: {', '.join(allowed)}.", [], path)


def precondition_failed(path):
    return _build(412, "PRECONDITION_FAILED", "ETag does not match current resource state.", [], path)


def payload_too_large(path):
    return _build(413, "PAYLOAD_TOO_LARGE", "Request body too large.", [], path)


def unsupported_media_type(path):
    return _build(415, "UNSUPPORTED_MEDIA_TYPE", "Request body must be application/json.", [], path)


def internal(path):
    return _build(500, "INTERNAL_ERROR", "Internal server error.", [], path)
