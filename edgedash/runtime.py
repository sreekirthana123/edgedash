"""Centralized runtime secret and environment resolution."""

import os
import re

from dotenv import load_dotenv


load_dotenv()


def get_runtime_value(name: str, default: str | None = None) -> str | None:
    """Resolve a value from local environment first, then Streamlit secrets."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or default


def redact_error(message: str | BaseException) -> str:
    """Return an error message safe to log or display, with credentials removed.

    Deliberately conservative: driver error messages (e.g. psycopg) frequently
    quote just a fragment of a connection string — the password/userinfo
    without the ``postgresql://`` scheme. So we also replace any token that
    contains ``userinfo@host`` even when no scheme is present. See rule 48.
    """
    text = str(message)
    text = re.sub(
        r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s'\"]+",
        "<redacted connection string>",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"[^\s'\"]+@[^\s'\"]+",
        "<redacted credential/host>",
        text,
    )
    text = re.sub(r"AIza[A-Za-z0-9_-]{10,}", "<redacted API key>", text)
    text = re.sub(r"sk-[A-Za-z0-9_]{16,}", "<redacted API key>", text)
    return text