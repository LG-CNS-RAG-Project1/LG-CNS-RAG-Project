#!/usr/bin/env python3
"""IdeaLens 팀원용 통합 실행 도구. 표준 라이브러리만 쓰며 Windows·macOS의 Python 3.9 이상에서 동작한다.

사용 예:
    python3 scripts/idealens.py doctor          # 실행 환경 점검(키 값은 출력하지 않음)
    python3 scripts/idealens.py setup           # .env 준비(없을 때만)와 이미지 빌드
    python3 scripts/idealens.py ui              # Streamlit 화면 실행 후 브라우저 열기
    python3 scripts/idealens.py data market     # 시장 뉴스 수집·정제·색인(API 비용 발생)
    python3 scripts/idealens.py data patents --field-id SF-02   # 특허 수집·색인(API 비용 발생)
    python3 scripts/idealens.py test | logs | stop
Windows에서는 python3 대신 py 또는 python을 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
IMAGE = "lg-cns-rag-app:dev"
MIN_COMPOSE = (2, 24, 0)
HEALTH_WAIT_SECONDS = 90
DEFAULT_PATENT_FIELDS = ["SF-02", "SF-05"]
SECRET_NAMES = [
    "OPENAI_API_KEY",
    "KIPRIS_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NAVER_TREND_CLIENT_ID",
    "NAVER_TREND_CLIENT_SECRET",
    "DART_API_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "CHROMA_API_KEY",
]
COMMAND_KEYS = {
    "ui(실제 분석)": ["OPENAI_API_KEY", "KIPRIS_API_KEY"],
    "data market": ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "OPENAI_API_KEY"],
    "data patents": ["KIPRIS_API_KEY", "OPENAI_API_KEY"],
}
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b((?:access|service)key=)[^&\s'\"]+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]+"), r"\1***"),
]


class Report:
    """점검 결과를 [OK]/[주의]/[실패]로 출력하고 실패 여부를 모은다."""

    def __init__(self) -> None:
        self.failed = False
        self.lines: list[str] = []

    def emit(self, level: str, message: str) -> None:
        if level == "실패":
            self.failed = True
        line = f"[{level}] {message}"
        self.lines.append(line)
        print(line)

    def ok(self, message: str) -> None:
        self.emit("OK", message)

    def warn(self, message: str) -> None:
        self.emit("주의", message)

    def fail(self, message: str) -> None:
        self.emit("실패", message)


def ui_port() -> int:
    return int(os.getenv("IDEALENS_UI_PORT", "8505"))


def read_env(path: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """.env를 읽어 (이름→값, 형식 경고)를 돌려준다. 값은 화면에 쓰지 않는다."""
    path = path or ENV_PATH
    if not path.exists():
        return {}, []
    raw = path.read_bytes()
    warnings = []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:200]:
        return {}, [
            ".env가 UTF-16으로 저장되어 읽을 수 없습니다. UTF-8로 다시 저장하세요."
        ]
    if raw.startswith(b"\xef\xbb\xbf"):
        warnings.append(
            ".env에 BOM이 있습니다. 첫 키 이름이 다르게 읽힐 수 있으니 BOM 없는 UTF-8로 저장하세요."
        )
    text = raw.decode("utf-8-sig", errors="replace")
    if "\r\n" in text:
        warnings.append(".env 줄바꿈이 CRLF입니다. 대부분 동작하지만 LF를 권장합니다.")
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        values[name] = value.strip().strip("'\"")
    return values, warnings


def mask(text: str, env: dict[str, str] | None = None) -> str:
    """출력에서 .env 키 값과 키가 담긴 URL 인자·인증 헤더를 가린다."""
    env = env if env is not None else read_env()[0]
    for name in SECRET_NAMES:
        value = (env.get(name) or os.getenv(name) or "").strip()
        if len(value) >= 6:
            text = text.replace(value, "***")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def run(cmd: list[str], *, capture: bool = True, timeout: float | None = None):
    """명령을 저장소 루트에서 실행한다. 인자는 목록으로 넘겨 경로의 공백에 안전하다.

    표준입력은 넘기지 않는다(하위 명령이 확인 질문의 입력을 가로채지 않게 한다).
    """
    try:
        return subprocess.run(
            cmd,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            cmd, 127, "", f"{cmd[0]}: 명령을 찾을 수 없음"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "시간 초과")


def stream(cmd: list[str], env: dict[str, str]) -> int:
    """명령 출력을 줄 단위로 가려서 보여 주고 종료 코드를 돌려준다."""
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(mask(line.rstrip("\n"), env))
    return process.wait()


def parse_version(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", text)
    return tuple(int(n) for n in numbers[:3]) if numbers else (0,)


def docker_ready(report: Report) -> bool:
    result = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    if result.returncode != 0:
        report.fail("Docker 엔진에 연결할 수 없습니다. Docker Desktop을 실행하세요.")
        return False
    report.ok(f"Docker 엔진 {result.stdout.strip()}")
    version = run(["docker", "compose", "version", "--short"], timeout=20)
    found = parse_version(version.stdout)
    if version.returncode != 0 or found < MIN_COMPOSE:
        report.fail(
            f"Docker Compose {'.'.join(map(str, MIN_COMPOSE))} 이상이 필요합니다(현재 {version.stdout.strip() or '없음'})."
        )
        return False
    report.ok(f"Docker Compose {version.stdout.strip()}")
    return True


def image_exists() -> bool:
    return run(["docker", "image", "inspect", IMAGE], timeout=30).returncode == 0


def required_version(package: str) -> str | None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    match = re.search(rf"^{package}==([\w.]+)", text, re.M)
    return match.group(1) if match else None


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def ui_running() -> bool:
    result = run(
        ["docker", "compose", "ps", "--status", "running", "--services"], timeout=30
    )
    return result.returncode == 0 and "ui" in result.stdout.split()


def chroma_checks(env: dict[str, str], report: Report) -> None:
    host = env.get("CHROMA_HOST", "").strip()
    if not host:
        report.ok("Chroma: 로컬 색인 사용(CHROMA_HOST 없음)")
        return
    key = env.get("CHROMA_API_KEY", "").strip()
    ssl = env.get("CHROMA_SSL", "false").strip().lower() == "true"
    port = env.get("CHROMA_PORT", "8000").strip() or "8000"
    if host in ("127.0.0.1", "localhost"):
        report.warn(
            "CHROMA_HOST가 127.0.0.1입니다. 컨테이너 안에서는 호스트의 IAP 터널에 닿지 않습니다."
        )
    if key and (not ssl or port != "443"):
        report.fail(
            "CHROMA_API_KEY를 쓰려면 CHROMA_SSL=true, CHROMA_PORT=443이어야 합니다."
        )
        return
    url = f"{'https' if ssl else 'http'}://{host}:{port}/api/v2/heartbeat"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}"} if key else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            report.ok(f"공용 Chroma 응답(HTTP {response.status})")
    except urllib.error.HTTPError as exc:
        hint = " 키를 확인하세요." if exc.code in (401, 403) else ""
        report.fail(f"공용 Chroma 오류(HTTP {exc.code}).{hint}")
    except (urllib.error.URLError, OSError) as exc:
        report.fail(f"공용 Chroma에 연결할 수 없습니다({type(exc).__name__}).")


def count_text(count) -> str:
    return "없음" if count is None else f"{count}건"


def pipeline_status(report: Report) -> dict | None:
    """컨테이너에서 색인 준비 상태를 읽는다. 표준 출력의 JSON만 해석한다."""
    result = run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "app",
            "python",
            "-m",
            "src.pipeline",
            "status",
            "--json",
        ],
        timeout=180,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        report.warn("색인 상태를 읽지 못했습니다(이미지·코드 확인 필요).")
        return None


def cmd_doctor(args) -> int:
    report = Report()
    env, env_warnings = read_env()
    if not ENV_PATH.exists():
        report.fail(".env가 없습니다. `setup`으로 예시를 복사한 뒤 키를 채우세요.")
    for warning in env_warnings:
        report.warn(warning)
    for name in SECRET_NAMES:
        state = "설정됨" if env.get(name, "").strip() else "비어 있음"
        print(f"  - {name}: {state}")
    for command, names in COMMAND_KEYS.items():
        missing = [n for n in names if not env.get(n, "").strip()]
        if missing:
            report.warn(f"{command}에 필요한 키 없음: {', '.join(missing)}")
    if docker_ready(report):
        if image_exists():
            report.ok(f"이미지 {IMAGE}")
            wanted = required_version("streamlit")
            found = run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "app",
                    "python",
                    "-c",
                    "import streamlit; print(streamlit.__version__)",
                ],
                timeout=120,
            ).stdout.strip()
            if wanted and found != wanted:
                report.warn(
                    f"이미지의 streamlit {found or '확인 불가'} ≠ 요구 {wanted}. `setup`으로 다시 빌드하세요."
                )
            status = pipeline_status(report)
            if status:
                market = status["market_index"]
                patent = status["patent_index"]
                report.ok(
                    f"색인({'공용' if status['chroma'] == 'remote' else '로컬'}):"
                    f" 시장 {count_text(market['count'])}, 특허 {count_text(patent['count'])}"
                    + (f" {patent['area_counts']}" if patent["area_counts"] else "")
                )
                for reason in status.get("reasons", []):
                    report.warn(reason)
        else:
            report.warn("이미지가 없습니다. `setup`을 먼저 실행하세요.")
    chroma_checks(env, report)
    port = ui_port()
    if port_in_use(port):
        if ui_running():
            report.ok(f"포트 {port}: ui 컨테이너가 사용 중")
        else:
            report.fail(
                f"포트 {port}를 다른 프로그램이 사용 중입니다. 종료하거나 IDEALENS_UI_PORT를 바꾸세요."
            )
    else:
        report.ok(f"포트 {port} 사용 가능")
    if args.host:
        try:
            from importlib.metadata import version

            found = version("streamlit")
        except Exception:
            found = None
        wanted = required_version("streamlit")
        if found != wanted:
            report.warn(
                f"호스트 streamlit {found or '없음'} ≠ 요구 {wanted}. 호스트 실행은 README의 고정 버전 가상환경을 쓰세요."
            )
        else:
            report.ok(f"호스트 streamlit {found}")
    return 1 if report.failed else 0


def cmd_setup(args) -> int:
    example = ROOT / ".env.example"
    if ENV_PATH.exists():
        print("[OK] .env가 이미 있어 그대로 둡니다.")
    else:
        ENV_PATH.write_bytes(example.read_bytes())
        print("[OK] .env.example을 .env로 복사했습니다. 키를 채워 주세요.")
    report = Report()
    if not docker_ready(report):
        return 1
    return stream(["docker", "compose", "build"], read_env()[0])


def wait_health(port: int, seconds: int = HEALTH_WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + seconds
    url = f"http://127.0.0.1:{port}/_stcore/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def cmd_ui(args) -> int:
    report = Report()
    if not docker_ready(report):
        return 1
    if not image_exists():
        report.fail("이미지가 없습니다. 먼저 `setup`을 실행하세요.")
        return 1
    port = ui_port()
    if port_in_use(port) and not ui_running():
        report.fail(f"포트 {port}를 다른 프로그램이 사용 중입니다.")
        return 1
    cmd = ["docker", "compose", "up", "-d"]
    if args.recreate:
        cmd.append("--force-recreate")
    if stream(cmd + ["ui"], read_env()[0]) != 0:
        return 1
    if not wait_health(port):
        report.fail("화면이 준비되지 않았습니다. `logs`로 확인하세요.")
        return 1
    url = f"http://localhost:{port}"
    report.ok(f"화면 준비 완료: {url}")
    if not args.no_browser:
        webbrowser.open(url)
    return 0


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def compose_app(*args: str) -> list[str]:
    return ["docker", "compose", "run", "--rm", "-T", "app", *args]


def market_keyword_ids() -> list[str]:
    result = run(
        compose_app(
            "python",
            "-c",
            "import json; from src.ingestion.news_client import load_keyword_config;"
            " print(json.dumps([k['id'] for k in load_keyword_config()['keywords']]))",
        ),
        timeout=180,
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return []


def cmd_data(args) -> int:
    report = Report()
    env, _ = read_env()
    if not docker_ready(report) or not image_exists():
        report.fail("Docker 엔진과 이미지가 필요합니다(`setup`).")
        return 1
    shared = bool(env.get("CHROMA_HOST", "").strip())
    target = "팀 공용 Chroma" if shared else "로컬 Chroma"
    if args.kind == "market":
        ids = market_keyword_ids()
        if not ids:
            report.fail("시장 키워드를 읽지 못했습니다.")
            return 1
        today = date.today().strftime("%Y%m%d")
        todo = [
            i
            for i in ids
            if not (
                ROOT / "data" / "market" / "raw" / f"news_{i}_{today}.json"
            ).exists()
        ]
        print(
            f"시장 수집: 키워드 {len(ids)}개 중 오늘 미수집 {len(todo)}개 · NAVER {len(todo)}~{len(todo) * 10}회"
            f" · 임베딩 최대 {len(ids) * 100}건 · 적재 위치: {target}"
        )
        if shared:
            print(
                "공용 서버에 씁니다. 다른 팀원의 색인 작업과 겹치지 않게 공지한 뒤 진행하세요."
            )
        if not confirm("진행할까요?", args.yes and not shared):
            print("취소했습니다.")
            return 0
        for keyword_id in todo:
            code = stream(
                compose_app(
                    "python",
                    "-m",
                    "src.ingestion.news_client",
                    "--keyword-id",
                    keyword_id,
                ),
                env,
            )
            if code != 0:
                report.fail(
                    f"{keyword_id} 수집 실패. 같은 명령을 다시 실행하면 실패한 키워드만 이어서 수집합니다."
                )
                return 1
        steps = [
            ["python", "-m", "src.ingestion.market_processor"],
            ["python", "-m", "src.retrieval.market_search", "build"],
        ]
    else:
        fields = args.field_id or DEFAULT_PATENT_FIELDS
        print(
            f"특허 수집: 분야 {', '.join(fields)} · 분야 검색어당 최대 {args.limit}건"
            + (" · 청구항 조회 포함(문헌당 1회 추가)" if args.include_claims else "")
            + f" · KIPRIS·임베딩 호출 발생 · 적재 위치: {target}"
        )
        if not confirm("진행할까요?", args.yes and not shared):
            print("취소했습니다.")
            return 0
        steps = []
        for field in fields:
            step = [
                "python",
                "-m",
                "src.ingestion.patent_processor",
                "--field-id",
                field,
            ]
            step += ["--limit", str(args.limit)]
            if args.include_claims:
                step.append("--include-claims")
            steps.append(step)
    for step in steps:
        if stream(compose_app(*step), env) != 0:
            report.fail(f"실패: {' '.join(step[2:])}")
            return 1
    report.ok("완료. `doctor`로 색인 건수를 확인하세요.")
    return 0


def cmd_test(args) -> int:
    code = stream(compose_app("python", "-m", "pytest", "-q"), read_env()[0])
    return 0 if code == 5 else code


def cmd_logs(args) -> int:
    return run(["docker", "compose", "logs", "-f", "ui"], capture=False).returncode


def cmd_stop(args) -> int:
    return run(["docker", "compose", "down"], capture=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IdeaLens 통합 실행 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="실행 환경 점검(키 값 미출력)")
    doctor.add_argument(
        "--host", action="store_true", help="호스트 streamlit 버전도 점검"
    )
    doctor.set_defaults(func=cmd_doctor)
    sub.add_parser("setup", help=".env 준비(없을 때만)와 이미지 빌드").set_defaults(
        func=cmd_setup
    )
    ui = sub.add_parser("ui", help="Streamlit 화면 실행")
    ui.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")
    ui.add_argument(
        "--recreate", action="store_true", help=".env를 바꾼 뒤 컨테이너 재생성"
    )
    ui.set_defaults(func=cmd_ui)
    data = sub.add_parser("data", help="수집·색인(API 비용 발생, 실행 전 확인)")
    data.add_argument("kind", choices=["market", "patents"])
    data.add_argument(
        "--field-id", action="append", help="특허 분야 ID(여러 번 지정 가능)"
    )
    data.add_argument(
        "--limit", type=int, default=10, help="특허 분야 검색어당 최대 건수"
    )
    data.add_argument(
        "--include-claims", action="store_true", help="특허 청구항 원문도 조회"
    )
    data.add_argument(
        "--yes", action="store_true", help="확인 생략(공용 서버 적재는 생략 불가)"
    )
    data.set_defaults(func=cmd_data)
    sub.add_parser("test", help="컨테이너에서 테스트").set_defaults(func=cmd_test)
    sub.add_parser("logs", help="ui 로그 보기").set_defaults(func=cmd_logs)
    sub.add_parser("stop", help="컨테이너 종료").set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream_ in (sys.stdout, sys.stderr):
        if hasattr(stream_, "reconfigure"):
            stream_.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
