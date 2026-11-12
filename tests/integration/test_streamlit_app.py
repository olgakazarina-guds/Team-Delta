import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from core.config import reset_settings


def test_streamlit_app_renders_in_development():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert not app.exception
    assert any(title.value == "LMS Converter" for title in app.title)


def test_streamlit_app_fails_closed_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_CONVERTER_ENV", "production")
    monkeypatch.setenv("LMS_CONVERTER_AUTH_MODE", "none")
    reset_settings()

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert not app.exception
    assert [error.value for error in app.error] == ["Authentication is required."]
