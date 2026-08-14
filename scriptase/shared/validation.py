"""Shared request validation decorator using Pydantic v2."""

from functools import wraps

from flask import request, jsonify
from pydantic import BaseModel, ValidationError


def validate_json(schema: type[BaseModel]):
    """Decorator that validates the request JSON body against a Pydantic model.

    On success, passes the validated model as the first argument to the route.
    On failure, returns 400 with structured error details.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            raw = request.get_json(silent=True)
            if raw is None:
                return jsonify({"error": "Request body must be JSON"}), 400
            try:
                validated = schema.model_validate(raw)
            except ValidationError as e:
                errors = e.errors(include_url=False, include_context=False)
                return jsonify({"error": "Validation failed", "details": errors}), 400
            return f(validated, *args, **kwargs)
        return wrapper
    return decorator
