"""Streamlit Community Cloud(SCC)에 배포된 IdeaLens 앱이 실제로 떴는지 브라우저로 확인한다.

GitHub Actions의 SCC Smoke 워크플로가 main push 뒤와 수동 실행(시연 전 깨우기) 때 실행한다.
SCC 주소는 HTTP 요청만으로는 정적 화면을 돌려주므로 Playwright(Chromium)로 열어 확인한다.
비밀번호는 입력하지 않는다.

판정 규칙
- 비밀번호 입력란이 보이고 화면의 '버전 xxxxxxx'가 기대 커밋과 같으면 성공한다.
- 버전 표시가 없으면(.git 없는 배포) 경고와 함께 성공한다.
- 다음 경우는 실패한다.
  - 오류 문구가 보인다.
  - 앱은 떴지만 비밀번호 화면이 없다(IDEALENS_APP_PASSWORD 누락).
  - 제한 시간 안에 새 버전이 보이지 않는다.
- 잠든 앱은 깨우기 버튼을 누르고 계속 기다린다.

사용 예: python scripts/scc_smoke.py --url https://<앱>.streamlit.app --expect-sha <커밋>
playwright는 main() 안에서만 불러온다(판정 함수 테스트에는 필요 없다).
"""

import argparse
import re
import sys
import time
from dataclasses import dataclass

ERROR_MARKERS = (
    "This app has encountered an error",
    "Error running app",
    "Error installing requirements",
    "Oh no.",
    "ModuleNotFoundError",
    "Traceback",
)
WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
VERSION = re.compile(r"버전 ([0-9a-f]{7})\b")
SUCCESS = {"ready", "ready_unversioned"}


@dataclass
class Observation:
    """한 번 들여다본 화면에서 모은 사실(모든 frame 합산)."""

    text: str
    has_password_input: bool
    has_app: bool
    has_wake_button: bool


def classify(obs: Observation, expected_sha: str = "") -> str:
    """화면 상태를 판정한다.

    반환값: error, sleeping, ready, ready_unversioned, stale, no_gate, loading
    - stale: 비밀번호 화면은 있으나 버전이 기대 커밋과 다르다(아직 이전 배포).
    - no_gate: Streamlit 앱은 떴는데 비밀번호 입력란이 없다.
    - loading: 아직 앱이 그려지지 않았다(SCC 빌드·로딩 화면 포함).
    """
    if any(marker in obs.text for marker in ERROR_MARKERS):
        return "error"
    if obs.has_wake_button:
        return "sleeping"
    if obs.has_password_input:
        match = VERSION.search(obs.text)
        if not match:
            return "ready_unversioned"
        if expected_sha and match.group(1) != expected_sha[:7].lower():
            return "stale"
        return "ready"
    if obs.has_app:
        return "no_gate"
    return "loading"


def failure_message(state: str, obs: Observation | None, expected_sha: str) -> str:
    """실패 상태를 사람이 읽을 안내 문구로 바꾼다."""
    if state == "error":
        found = [m for m in ERROR_MARKERS if obs and m in obs.text]
        return f"앱 오류 화면이 보입니다({', '.join(found)}). SCC의 Manage app 로그를 확인하세요."
    if state == "no_gate":
        return "앱은 떴지만 비밀번호 화면이 없습니다. SCC Secrets의 IDEALENS_APP_PASSWORD를 확인하세요."
    if state == "stale":
        shown = VERSION.search(obs.text).group(1) if obs else "?"
        return (
            f"제한 시간 안에 새 커밋이 반영되지 않았습니다"
            f"(화면 {shown}, 기대 {expected_sha[:7]}). SCC 앱 상태를 확인하세요."
        )
    return f"제한 시간 안에 비밀번호 화면을 확인하지 못했습니다(마지막 상태: {state})."


def observe(page) -> Observation:
    """현재 페이지의 모든 frame을 훑어 판정에 필요한 사실을 모은다(SCC는 앱을 iframe에 넣는다)."""
    from playwright.sync_api import Error as PlaywrightError

    texts = []
    has_password = has_app = has_wake = False
    for frame in page.frames:
        try:
            texts.append(frame.locator("body").inner_text(timeout=5_000))
            has_password |= frame.locator('input[type="password"]').count() > 0
            has_app |= frame.locator('[data-testid="stApp"]').count() > 0
            has_wake |= frame.get_by_role("button", name=WAKE_BUTTON).count() > 0
        except PlaywrightError:
            continue
    return Observation("\n".join(texts), has_password, has_app, has_wake)


def click_wake_button(page) -> bool:
    """잠든 앱의 깨우기 버튼을 찾아 누른다."""
    for frame in page.frames:
        button = frame.get_by_role("button", name=WAKE_BUTTON)
        if button.count():
            button.first.click()
            return True
    return False


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SCC 배포 앱 기동 확인")
    parser.add_argument(
        "--url", required=True, help="앱 주소(https://<앱>.streamlit.app)"
    )
    parser.add_argument(
        "--expect-sha",
        default="",
        help="화면 버전과 맞춰 볼 커밋. 비우면 버전을 따지지 않는다",
    )
    parser.add_argument(
        "--initial-wait", type=int, default=0, help="첫 확인 전 대기(초)"
    )
    parser.add_argument("--timeout", type=int, default=900, help="전체 제한 시간(초)")
    parser.add_argument("--interval", type=int, default=20, help="새로 고침 간격(초)")
    parser.add_argument(
        "--no-gate-grace",
        type=int,
        default=40,
        help="비밀번호 화면 없음이 이어져야 하는 시간(초)",
    )
    parser.add_argument("--screenshot", default="", help="실패 시 화면을 저장할 경로")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    started = time.monotonic()
    deadline = started + args.initial_wait + args.timeout

    def log(message: str) -> None:
        print(f"[{int(time.monotonic() - started):>4}s] {message}", flush=True)

    if args.initial_wait:
        log(f"배포 반영을 {args.initial_wait}초 기다립니다.")
        time.sleep(args.initial_wait)

    state, obs, no_gate_since = "loading", None, None

    def gate_missing() -> bool:
        return bool(
            no_gate_since and time.monotonic() - no_gate_since >= args.no_gate_grace
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            while time.monotonic() < deadline:
                try:
                    page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
                except PlaywrightError as exc:
                    log(f"페이지를 열지 못했습니다: {str(exc).splitlines()[0]}")
                    page.wait_for_timeout(args.interval * 1_000)
                    continue
                cycle_end = min(deadline, time.monotonic() + args.interval)
                while time.monotonic() < cycle_end:
                    page.wait_for_timeout(2_000)
                    obs = observe(page)
                    state = classify(obs, args.expect_sha)
                    if state == "no_gate":
                        no_gate_since = no_gate_since or time.monotonic()
                    elif state != "loading":
                        no_gate_since = None
                    if state in SUCCESS | {"error", "sleeping"} or gate_missing():
                        break
                if gate_missing():
                    state = "no_gate"
                log(f"상태: {state}")
                if state == "ready":
                    log("비밀번호 화면과 배포 버전을 확인했습니다.")
                    return 0
                if state == "ready_unversioned":
                    print(
                        "::warning::비밀번호 화면은 떴지만 버전 표시가 없어 새 커밋 반영 여부는 확인하지 못했습니다."
                    )
                    return 0
                if state == "error" or gate_missing():
                    break
                if state == "sleeping" and click_wake_button(page):
                    log("잠든 앱의 깨우기 버튼을 눌렀습니다.")
                    page.wait_for_timeout(args.interval * 1_000)
            print(f"::error::{failure_message(state, obs, args.expect_sha)}")
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
