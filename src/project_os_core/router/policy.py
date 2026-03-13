from __future__ import annotations

from ..models import ProfileCapability


def default_profile_capabilities() -> dict[str, ProfileCapability]:
    return {
        "core": ProfileCapability(
            profile_name="core",
            capability_names=["planning", "memory", "runtime"],
            allowed_workers=["deterministic", "router"],
            required_secrets=[],
        ),
        "browser": ProfileCapability(
            profile_name="browser",
            capability_names=["web_navigation", "form_fill", "dom_actions"],
            allowed_workers=["browser", "deterministic"],
            required_secrets=["OPENAI_API_KEY"],
        ),
        "uefn": ProfileCapability(
            profile_name="uefn",
            capability_names=["desktop_windows", "editor_control", "screenshot_validation"],
            allowed_workers=["windows", "browser", "deterministic"],
            required_secrets=["OPENAI_API_KEY"],
        ),
    }
