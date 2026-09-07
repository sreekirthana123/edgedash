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


def redact_error(error: BaseException) -> str:
    """Return an error message with connection strings and key-like values removed."""
    message = str(error)
    message = re.sub(r"(?:postgres(?:ql)?|mysql)://\S+", "<redacted connection string>", message, flags=re.I)
    message = re.sub(r"AQ\.[A-Za-z0-9_-]+", "<redacted API key>", message)
    message = re.sub(r"AIza[A-Za-z0-9_-]+", "<redacted API key>", message)
    return message