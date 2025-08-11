# auth.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple, Optional
import yaml
import streamlit as st
import streamlit_authenticator as stauth

# -------------------- Config path --------------------
_CONFIG_PATH = Path(__file__).parent / "auth_config.yaml"

# -------------------- Default (first-run) users --------------------
_DEFAULT_USERS = {
    "moussa": {
        "email": "moussa@example.com",
        "name": "Moussa Salameh",
        "password": "test123",  # will be hashed on first run
    },
    "demo": {
        "email": "demo@example.com",
        "name": "Demo User",
        "password": "demo123",  # will be hashed on first run
    },
}

_DEFAULT_COOKIE = {
    "name": "vacation_auth",
    "key": "super_secret_key_change_me",
    "expiry_days": 7,
}

# -------------------- YAML I/O --------------------
def _save_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# -------------------- Config management --------------------
def _make_first_run_config() -> dict:
    """Create a brand-new YAML with hashed default passwords (v0.4.x API)."""
    raw_passwords = [v["password"] for v in _DEFAULT_USERS.values()]
    hashed_pw = stauth.Hasher.hash_list(raw_passwords)  # ✅ v0.4.x class method

    credentials = {"usernames": {}}
    for (username, meta), hpw in zip(_DEFAULT_USERS.items(), hashed_pw):
        credentials["usernames"][username] = {
            "name": meta["name"],
            "email": meta["email"],
            "password": hpw,  # store bcrypt hash
        }

    return {
        "credentials": credentials,
        "cookie": _DEFAULT_COOKIE,
        "preauthorized": {"emails": []},
    }

def _ensure_config() -> dict:
    """Ensure YAML exists and is consistent; hash any stray plaintext passwords."""
    if not _CONFIG_PATH.exists():
        cfg = _make_first_run_config()
        _save_yaml(cfg, _CONFIG_PATH)
        return cfg

    cfg = _load_yaml(_CONFIG_PATH)
    cfg.setdefault("credentials", {}).setdefault("usernames", {})
    cfg.setdefault("cookie", _DEFAULT_COOKIE)
    cfg.setdefault("preauthorized", {"emails": []})

    # Re-hash any non-bcrypt entries using v0.4.x helpers
    for _, record in list(cfg["credentials"]["usernames"].items()):
        pw = str(record.get("password", "") or "")
        if pw and not stauth.Hasher.is_hash(pw):
            record["password"] = stauth.Hasher.hash(pw)

    _save_yaml(cfg, _CONFIG_PATH)
    return cfg

def _build_authenticator(cfg: dict) -> stauth.Authenticate:
    """
    IMPORTANT: Pass the *path* to the YAML (string), not the dict.
    In v0.4.x this enables the library to persist changes (registration, updates) to disk.
    """
    cookie = cfg.get("cookie", {})
    return stauth.Authenticate(
        credentials=str(_CONFIG_PATH),                 # ✅ pass path for persistence
        cookie_name=cookie.get("name", "vacation_auth"),
        cookie_key=cookie.get("key", "super_secret_key_change_me"),
        cookie_expiry_days=cookie.get("expiry_days", 7),
        auto_hash=True,
    )

# -------------------- Public API --------------------
def gate() -> Tuple[Optional[str], Optional[bool], Optional[str], stauth.Authenticate]:
    """
    Renders login/register/reset UI in the MAIN area and returns:
    (name, authentication_status, username, authenticator)

    Works with streamlit-authenticator v0.4.x (no Hasher.generate, session_state-based login).
    """
    st.markdown("### Sign in to continue")

    cfg = _ensure_config()
    authenticator = _build_authenticator(cfg)

    # --- Login widget (v0.4.x) ---
    authenticator.login(location="main", key="Login")  # renders the form

    # Read values from session_state (v0.4.x behavior)
    name = st.session_state.get("name")
    authentication_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

    # --- Registration ---
    with st.expander("Create a new account"):
        try:
            new_email, new_username, new_name = authenticator.register_user(
                location="main",
                pre_authorized=None,
                captcha=True,
                key="Register user",
            )
            if all([new_email, new_username, new_name]):
                st.success("Registration successful. You can now log in.")
        except Exception as e:
            st.error(f"Registration error: {e}")

    # --- Reset password (needs a username in v0.4.x) ---
    with st.expander("Reset your password"):
        try:
            if username:
                did_reset = authenticator.reset_password(
                    username=username, location="main", key="Reset password"
                )
                if did_reset:
                    st.success("Password reset successful.")
            else:
                st.info("Log in first to reset your password.")
        except Exception as e:
            st.error(f"Password reset error: {e}")

    # --- Update profile (needs a username in v0.4.x) ---
    with st.expander("Update your profile (name/email)"):
        try:
            if username:
                updated = authenticator.update_user_details(
                    username=username, location="main", key="Update user details"
                )
                if updated:
                    st.success("Details updated.")
            else:
                st.info("Log in first to update your details.")
        except Exception as e:
            st.error(f"Update error: {e}")

    # NOTE: We no longer render a logout button here.
    # The app (streamlit_app.py) owns the single logout button in the sidebar.

    return name, authentication_status, username, authenticator
