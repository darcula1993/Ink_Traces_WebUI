"""Shared request value normalization."""


def positive_id(value):
    """Parse an ID without truncating floats or treating booleans as IDs."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('ID must be a positive integer')
    parsed = int(value)
    if parsed <= 0:
        raise ValueError('ID must be a positive integer')
    return parsed


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in ('true', '1', 'yes', 'on'):
        return True
    if normalized in ('false', '0', 'no', 'off', ''):
        return False
    return default


def normalize_newlines(value):
    """Unify CRLF / lone CR to LF; multipart form fields arrive as CRLF."""
    if not isinstance(value, str):
        return value
    return value.replace('\r\n', '\n').replace('\r', '\n')
