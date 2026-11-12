"""Authentication gate for web-facing deployments.

The project deliberately does not implement a password database.  Production
deployments must terminate authentication in a trusted reverse proxy and pass an
identity header, or run in development mode with the local identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.config import Settings, get_settings
from core.errors import AuthenticationError

PRODUCTION_ENVIRONMENTS = {"production", "prod"}


@dataclass(frozen=True)
class Identity:
    """The authenticated identity for one request."""

    user_id: str
    mode: str


def require_identity(
    settings: Settings | None = None,
    headers: Mapping[str, str] | None = None,
) -> Identity:
    """Return the request identity or raise :class:`AuthenticationError`."""
    cfg = settings or get_settings()
    mode = cfg.auth_mode.strip().lower()

    if mode == "none":
        if cfg.environment.strip().lower() in PRODUCTION_ENVIRONMENTS:
            raise AuthenticationError(
                "Authentication is required in production; configure a trusted reverse proxy"
            )
        return Identity(user_id="local", mode="none")

    if mode == "proxy":
        header = cfg.trusted_user_header
        value = None
        if headers:
            value = next(
                (
                    candidate
                    for name, candidate in headers.items()
                    if name.lower() == header.lower()
                ),
                None,
            )
        if not value or not value.strip():
            raise AuthenticationError(f"Missing trusted identity header: {header}")
        user_id = value.strip()
        if len(user_id) > 256 or any(ord(char) < 32 for char in user_id):
            raise AuthenticationError("Invalid trusted identity header value")
        return Identity(user_id=user_id, mode="proxy")

    raise AuthenticationError(f"Unsupported authentication mode: {mode!r}")
