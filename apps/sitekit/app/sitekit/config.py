"""Per-site settings come from environment variables (ConfigMap + SealedSecret)."""
import json, os
from dataclasses import dataclass, field

DEFAULT_FORMS = {
    "contact": {"title": "Contact us", "fields": [["name", "Your name", True], ["email", "Email", True], ["message", "Message", True]]}
}


@dataclass
class Settings:
    site_name: str = "Site"
    color: str = "#0b6bcb"
    site_root: str = "/git/current"
    secret_key: str = "dev-only-change-me"
    admin_email: str = ""
    admin_password: str = ""
    roles: list = field(default_factory=lambda: ["admin", "staff", "client"])
    forms: dict = field(default_factory=lambda: DEFAULT_FORMS)
    launcher: list = field(default_factory=list)
    secure_cookies: bool = True
    session_hours: int = 12
    modules: list = field(default_factory=list)
    staff_roles: list = field(default_factory=lambda: ["admin", "staff"])
    require_2fa_roles: list = field(default_factory=lambda: ["admin"])
    self_signup: bool = False
    signup_role: str = "member"
    module_config: dict = field(default_factory=dict)


def from_env() -> Settings:
    e = os.environ.get
    return Settings(
        site_name=e("SITE_NAME", "Site"),
        color=e("SITE_COLOR", "#0b6bcb"),
        site_root=e("SITE_ROOT", "/git/current"),
        secret_key=e("SECRET_KEY", "dev-only-change-me"),
        admin_email=e("ADMIN_EMAIL", "").strip().lower(),
        admin_password=e("ADMIN_PASSWORD", ""),
        roles=json.loads(e("ROLES", '["admin","staff","client"]')),
        forms=json.loads(e("FORMS", json.dumps(DEFAULT_FORMS))),
        launcher=json.loads(e("LAUNCHER", "[]")),
        secure_cookies=e("SECURE_COOKIES", "true").lower() == "true",
        session_hours=int(e("SESSION_HOURS", "12")),
        modules=[m.strip() for m in e("MODULES", "").split(",") if m.strip()],
        staff_roles=json.loads(e("STAFF_ROLES", '["admin","staff"]')),
        require_2fa_roles=json.loads(e("REQUIRE_2FA_ROLES", '["admin"]')),
        self_signup=e("SELF_SIGNUP", "false").lower() == "true",
        signup_role=e("SIGNUP_ROLE", "member"),
        module_config=json.loads(e("MODULE_CONFIG", "{}")),
    )
