"""Persistent storage: config and browser profile path management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ._models import FlowConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

STORAGE_ROOT = Path.home() / ".flow-py"
PROFILE_DIR   = STORAGE_ROOT / "browser-profile"   # Playwright persistent context
CONFIG_FILE   = STORAGE_ROOT / "config.json"
PROJECTS_FILE = STORAGE_ROOT / "projects.json"

def ensure_dirs() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> FlowConfig:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return FlowConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text())
        return FlowConfig(**{k: v for k, v in data.items()
                            if k in FlowConfig.__dataclass_fields__})
    except Exception:
        return FlowConfig()


def save_config(cfg: FlowConfig) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg.__dict__, indent=2))


# ---------------------------------------------------------------------------
# Project registry
# ---------------------------------------------------------------------------

def load_projects() -> dict[str, dict]:
    """Return { project_id: { name, url, active } }"""
    ensure_dirs()
    if not PROJECTS_FILE.exists():
        return {}
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except Exception:
        return {}


def save_projects(projects: dict[str, dict]) -> None:
    ensure_dirs()
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))


def add_project(project_id: str, name: str, url: str) -> None:
    projects = load_projects()
    projects[project_id] = {"name": name, "url": url}
    save_projects(projects)


def set_active_project(project_id: Optional[str], url: Optional[str] = None) -> None:
    cfg = load_config()
    cfg.active_project_id = project_id
    cfg.active_project_url = url
    save_config(cfg)


def get_active_project() -> tuple[Optional[str], Optional[str]]:
    """Returns (project_id, project_url)."""
    cfg = load_config()
    return cfg.active_project_id, cfg.active_project_url


# ---------------------------------------------------------------------------
# Auth status
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    """Quick heuristic: profile dir has Cookies file (Chromium stores here)."""
    cookies_path = PROFILE_DIR / "Default" / "Cookies"
    return cookies_path.exists() and cookies_path.stat().st_size > 0
