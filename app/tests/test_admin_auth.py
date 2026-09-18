"""admin_auth 의 토큰 비교 순수 로직만 본다 (Streamlit 화면은 test_ui_apptest.py 쪽)."""
import streamlit as st

import admin_auth


def test_is_authorized_true_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(admin_auth, "required_token", lambda: "")
    st.session_state.pop(admin_auth.SESSION_KEY, None)
    assert admin_auth.is_authorized() is True


def test_is_authorized_false_until_session_flag_set(monkeypatch):
    monkeypatch.setattr(admin_auth, "required_token", lambda: "s3cret")
    st.session_state.pop(admin_auth.SESSION_KEY, None)
    assert admin_auth.is_authorized() is False

    st.session_state[admin_auth.SESSION_KEY] = True
    assert admin_auth.is_authorized() is True


def test_required_token_reads_and_strips_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "  s3cret  ")
    assert admin_auth.required_token() == "s3cret"

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert admin_auth.required_token() == ""
