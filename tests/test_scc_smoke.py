"""SCC 배포 스모크 검사의 화면 상태 판정을 검증한다(브라우저 없이 판정 함수만)."""

import pytest

from scripts.scc_smoke import Observation, classify, failure_message

SHA = "abc1234def5678abc1234def5678abc1234def56"


def obs(text="", password=False, app=False, wake=False):
    return Observation(text, password, app, wake)


@pytest.mark.parametrize(
    ("observation", "expected_sha", "state"),
    [
        (obs("IdeaLens 버전 abc1234", password=True, app=True), SHA, "ready"),
        (obs("IdeaLens 버전 abc1234", password=True, app=True), "", "ready"),
        (obs("IdeaLens 버전 0000000", password=True, app=True), SHA, "stale"),
        (obs("IdeaLens", password=True, app=True), SHA, "ready_unversioned"),
        (obs("돋보기로 조사 시작", app=True), SHA, "no_gate"),
        (obs("Your app is in the oven"), SHA, "loading"),
        (obs("Zzzz", wake=True), SHA, "sleeping"),
        (obs("This app has encountered an error.", app=True), SHA, "error"),
        (obs("Oh no. Error running app."), SHA, "error"),
        (obs("ModuleNotFoundError: No module named 'x'", app=True), SHA, "error"),
    ],
)
def test_classify(observation, expected_sha, state):
    assert classify(observation, expected_sha) == state


def test_error_wins_over_password_screen():
    observation = obs("Traceback (most recent call last)", password=True, app=True)
    assert classify(observation, SHA) == "error"


def test_failure_messages_point_to_next_action():
    assert "IDEALENS_APP_PASSWORD" in failure_message("no_gate", None, SHA)
    stale = obs("버전 0000000", password=True, app=True)
    assert "화면 0000000, 기대 abc1234" in failure_message("stale", stale, SHA)
    error = obs("Error installing requirements")
    assert "Manage app" in failure_message("error", error, SHA)
