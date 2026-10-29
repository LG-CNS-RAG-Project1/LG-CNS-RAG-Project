"""호스팅 배포용 접속 비밀번호 화면을 검증한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.live import MAX_PASSWORD_FAILURES, password_matches

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def labels(app):
    return [b.label for b in app.button]


def submit(app, value):
    app.text_input(key="app_password").input(value)
    next(b for b in app.button if b.label == "들어가기").click().run()
    assert not app.exception
    return app


def test_password_gate_blocks_until_correct(monkeypatch):
    monkeypatch.setenv("IDEALENS_APP_PASSWORD", "FAKE_APP_PASSWORD")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert "돋보기로 조사 시작" not in labels(app)
    assert not any((button.key or "").startswith("rail_") for button in app.button)
    submit(app, "wrong")
    assert any("맞지 않습니다" in e.value for e in app.error)
    assert "돋보기로 조사 시작" not in labels(app)
    submit(app, "FAKE_APP_PASSWORD")
    assert app.session_state.authenticated
    assert "돋보기로 조사 시작" in labels(app)


def test_password_gate_locks_after_repeated_failures(monkeypatch):
    monkeypatch.setenv("IDEALENS_APP_PASSWORD", "FAKE_APP_PASSWORD")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    for _ in range(MAX_PASSWORD_FAILURES):
        submit(app, "wrong")
    app.run()
    assert any("잠시 후 다시" in e.value for e in app.error)
    assert "들어가기" not in labels(app)


def test_password_gate_shows_build_version(monkeypatch):
    monkeypatch.setenv("IDEALENS_APP_PASSWORD", "FAKE_APP_PASSWORD")
    monkeypatch.setattr("frontend.live.build_version", lambda root: "abc1234")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert "버전 abc1234" in [c.value for c in app.caption]


def test_password_gate_hides_unknown_build_version(monkeypatch):
    monkeypatch.setenv("IDEALENS_APP_PASSWORD", "FAKE_APP_PASSWORD")
    monkeypatch.setattr("frontend.live.build_version", lambda root: "")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not any(c.value.startswith("버전") for c in app.caption)


def test_no_password_means_no_gate():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert "돋보기로 조사 시작" in labels(app)


def test_password_matches_trims_input_only():
    assert password_matches(" FAKE_APP_PASSWORD ", "FAKE_APP_PASSWORD")
    assert not password_matches("FAKE_APP_PASSWOR", "FAKE_APP_PASSWORD")
