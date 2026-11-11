"""Typed exceptions used across the conversion pipeline.

Security exceptions intentionally derive from :class:`ValueError` as well as
``LmsConverterError``.  Callers that already treat unsafe archive/path/XML input
as invalid values keep working, while new callers can distinguish security
failures from ordinary parse errors.
"""

from __future__ import annotations


class LmsConverterError(Exception):
    """Base class for all application-specific failures."""


class SecurityError(LmsConverterError, ValueError):
    """Base class for untrusted-input security failures."""


class UnsafePathError(SecurityError):
    """A package-controlled path would escape its allowed root."""


class ArchiveSecurityError(SecurityError):
    """An archive violates extraction safety limits."""


class XmlSecurityError(SecurityError):
    """An XML document violates parser safety limits."""


class IntegrityError(LmsConverterError):
    """The canonical course graph violates referential integrity."""


class UnsupportedSourceError(LmsConverterError, ValueError):
    """The requested source LMS is not supported."""


class UnsupportedTargetError(LmsConverterError, ValueError):
    """The requested target LMS is not supported."""
