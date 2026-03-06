"""Custom exceptions for flow-py."""
from __future__ import annotations


class FlowError(Exception):
    """Base exception for all flow-py errors."""
    pass


class AuthError(FlowError):
    """Authentication failed, expired, or not performed yet.
    Run `flow login` to fix."""
    pass


class NotLoggedInError(AuthError):
    """No saved session found. Run `flow login` first."""
    pass


class GenerationError(FlowError):
    """Content generation failed (server-side error)."""
    pass


class InvalidArgumentError(GenerationError):
    """Server returned 400 INVALID_ARGUMENT.
    Usually means a field value is wrong (wrong media UUID, bad model key, etc.)."""
    def __init__(self, message: str, status: int = 400):
        self.http_status = status
        super().__init__(message)


class NotFoundError(GenerationError):
    """Server returned 404 — endpoint or resource not found.
    Some features (e.g. video upscale) may be deprecated or unavailable."""
    def __init__(self, message: str):
        self.http_status = 404
        super().__init__(message)


class FeatureUnavailableError(FlowError):
    """A Flow feature is known to be unavailable via direct API.
    May require the UI or a different approach."""
    pass


class PolicyError(FlowError):
    """Prompt was rejected by Google's content policy."""

    def __init__(self, prompt: str):
        self.prompt = prompt
        super().__init__(f"Prompt rejected by content policy: {prompt[:80]}...")


class GenerationTimeout(FlowError):
    """Generation did not complete within the timeout window."""

    def __init__(self, message: str | int = 0):
        if isinstance(message, (int, float)) and message > 0:
            self.timeout_s = int(message)
            super().__init__(f"Generation timed out after {message}s")
        else:
            self.timeout_s = 0
            super().__init__(str(message) if message else "Generation timed out")


class DownloadError(FlowError):
    """Failed to download a generated artifact."""
    pass


class ProjectError(FlowError):
    """Error related to Flow project management."""
    pass


class NoProjectError(ProjectError):
    """No active project is set. Run `flow projects create` or `flow projects use <id>`."""
    pass


class UIError(FlowError):
    """Unexpected UI state — the Flow page layout may have changed."""

    def __init__(self, message: str, selector: str | None = None):
        self.selector = selector
        super().__init__(message + (f" (selector: {selector})" if selector else ""))
