"""Validation for untrusted AgentCore Gateway tool input."""

MAX_QUERY_LENGTH = 2000
_ALLOWED_CONTROL_CHARACTERS = "\t\n\r"


def validate_query(query: object) -> str:
    """Return a valid query without changing its content."""
    if not isinstance(query, str):
        raise ValueError("Query must be a string.")
    if not query.strip():
        raise ValueError("Query must not be empty.")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"Query must be {MAX_QUERY_LENGTH} characters or fewer."
        )
    if any(
        (ord(character) < 32 or ord(character) == 127)
        and character not in _ALLOWED_CONTROL_CHARACTERS
        for character in query
    ):
        raise ValueError("Query contains unsupported control characters.")
    return query
