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


class PolicyError(FlowError):
    """Prompt was rejected by Google's content policy."""

    def __init__(self, prompt: str):
        self.prompt = prompt
        super().__init__(f"Prompt rejected by content policy: {prompt[:80]}...")


class GenerationTimeout(FlowError):
    """Generation did not complete within the timeout window."""

    def __init__(self, timeout_s: int):
        self.timeout_s = timeout_s
        super().__init__(f"Generation timed out after {timeout_s}s")


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
