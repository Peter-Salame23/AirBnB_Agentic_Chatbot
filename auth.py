# auth.py
import os
from datetime import timedelta
from typing import Tuple, Optional, Dict, Any

import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

# -----------------------------
# Credential sources (priority):
# 1) .streamlit/secrets.toml -> [auth] section
# 2) auth.yaml file next to the app
# 3) In-code demo fallback (for local testing)
# -----------------------------

def _from_secrets() -> Optional[Dict[str, Any]]:
    try:
        auth_block = st.secrets.get("auth")
        if not auth_block:
            return None
        # Expecting:
        # [auth]
        # cookie_name="vacation_auth"
        # cookie_key="some_random_key"
        # cookie_expiry_days=1
        # [auth.credentials.usernames.USERNAME]
        # name="Full Name"
        # email="email@domain.com"
        # password_hash="$2b$12$..."
        cfg = {
            "credentials": {"usernames": {}},
            "cookie": {
                "name": auth_block.get("cookie_name", "vacation_auth"),
                "key": auth_block.get("cookie_key", "vacation_auth_key"),
                "expiry_days": int(auth_block.get("cookie_expiry_days", 1)),
            },
        }
        # Collect users
        users = auth_block.get("credentials", {}).get("usernames", {})
        if users:
            cfg["credentials"]["usernames"] = users
        return cfg if users else None
    except Exception:
        return None

def _from_yaml(path: str = "auth.yaml") -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = yaml.load(f, Loader=SafeLoader) or {}
    # Expected YAML structure mirrors streamlit-authenticator’s recommended format
    # credentials:
    #   usernames:
    #     moussa:
    #       email: "abc@example.com"
    #       name: "Peter Parker"
    #       password_hash: "1234"
    # cookie:
    #   name: "vacation_auth"
    #   key: "vacation_auth_key"
    #   expiry_days: 1
    return data if data.get("credentials", {}).get("usernames") else None

def _demo_fallback() -> Dict[str, Any]:
    # For local/dev only — replace with secrets or YAML in production.
    # Passwords hashed on import. Example plaintexts: test123 / demo123
    demo_hashes = stauth.Hasher(["test123", "demo123"]).generate()
    return {
        "credentials": {
            "usernames": {
                "moussa": {
                    "email": "moussa@example.com",
                    "name": "Moussa Salameh",
                    "password": demo_hashes[0],   # streamlit-authenticator supports both 'password' (hash) and 'password_hash'
                },
                "demo": {
                    "email": "demo@example.com",
                    "name": "Demo User",
                    "password": demo_hashes[1],
                },
            }
        },
        "cookie": {"name": "vacation_auth", "key": "vacation_auth_key", "expiry_days": 1},
    }

def _load_auth_config() -> Dict[str, Any]:
    return _from_secrets() or _from_yaml() or _demo_fallback()

def build_authenticator() -> stauth.Authenticate:
    cfg = _load_auth_config()
    creds = cfg["credentials"]
    cookie = cfg["cookie"]
    authenticator = stauth.Authenticate(
        credentials=creds,
        cookie_name=cookie.get("name", "vacation_auth"),
        key=cookie.get("key", "vacation_auth_key"),
        cookie_expiry_days=int(cookie.get("expiry_days", 1)),
    )
    return authenticator

def login_ui(location: str = "sidebar") -> Tuple[Optional[stauth.Authenticate], Optional[bool], Optional[str], Optional[str]]:
    """
    Renders the login widget.
    Returns: (authenticator, auth_status, username, display_name)
    """
    authenticator = build_authenticator()
    name, auth_status, username = authenticator.login("Login", location)

    if auth_status:
        # Minimal session bootstrapping for downstream use
        if "user_id" not in st.session_state:
            st.session_state.user_id = username
        if "preferences_history" not in st.session_state:
            st.session_state.preferences_history = []
        if "_last_active" not in st.session_state:
            st.session_state["_last_active"] = None
        st.session_state["_session_timeout"] = timedelta(hours=4)
        return authenticator, True, username, name

    elif auth_status is False:
        if location == "sidebar":
            st.sidebar.error("Invalid username or password.")
        else:
            st.error("Invalid username or password.")
        return None, False, None, None

    # auth_status is None (no attempt yet)
    return None, None, None, None

def logout_ui(authenticator: stauth.Authenticate, location: str = "sidebar"):
    if location == "sidebar":
        with st.sidebar:
            authenticator.logout("Logout")
    else:
        authenticator.logout("Logout")
