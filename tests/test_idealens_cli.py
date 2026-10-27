"""scripts/idealens.py의 .env 해석·키 미출력·확인 질문·포트 점검·명령 구성을 검증한다."""

import importlib.util
import socket
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "idealens.py"
spec = importlib.util.spec_from_file_location("idealens", SCRIPT)
idealens = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idealens)


def test_read_env_handles_bom_crlf_quotes_and_export(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(
        b"\xef\xbb\xbfOPENAI_API_KEY=sk-test-SECRET123\r\n"
        b"export KIPRIS_API_KEY='kipris-SECRET'\r\n# comment\r\nEMPTY=\r\n"
    )
    values, warnings = idealens.read_env(path)
    assert values["OPENAI_API_KEY"] == "sk-test-SECRET123"
    assert values["KIPRIS_API_KEY"] == "kipris-SECRET" and values["EMPTY"] == ""
    assert any("BOM" in w for w in warnings) and any("CRLF" in w for w in warnings)


def test_read_env_rejects_utf16(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=x\n", encoding="utf-16")
    values, warnings = idealens.read_env(path)
    assert values == {} and "UTF-16" in warnings[0]


def test_doctor_never_prints_key_values(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=sk-test-SECRET123\nKIPRIS_API_KEY=kipris-SECRET\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(idealens, "ENV_PATH", env)
    monkeypatch.setattr(idealens, "docker_ready", lambda report: False)
    monkeypatch.setattr(idealens, "port_in_use", lambda port: False)
    code = idealens.main(["doctor"])
    out = capsys.readouterr().out
    assert "sk-test-SECRET123" not in out and "kipris-SECRET" not in out
    assert "OPENAI_API_KEY: 설정됨" in out and "NAVER_CLIENT_ID: 비어 있음" in out
    assert code == 0


def test_mask_hides_env_values_and_url_keys():
    env = {"KIPRIS_API_KEY": "kipris-raw-7777"}
    text = "GET http://x?ServiceKey=kipris-raw-7777&a=1 Bearer abc.def sk-abcdefghijkl"
    masked = idealens.mask(text, env)
    assert "kipris-raw-7777" not in masked and "abc.def" not in masked
    assert "abcdefghijkl" not in masked


@pytest.mark.parametrize(
    "answer, expected", [("", False), ("n", False), ("y", True), ("YES", True)]
)
def test_confirm_defaults_to_no(monkeypatch, answer, expected):
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert idealens.confirm("진행할까요?", assume_yes=False) is expected


def test_data_cancel_runs_no_collection(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(idealens, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(idealens, "docker_ready", lambda report: True)
    monkeypatch.setattr(idealens, "image_exists", lambda: True)
    monkeypatch.setattr(idealens, "market_keyword_ids", lambda: ["k1", "k2"])
    monkeypatch.setattr(idealens, "stream", lambda cmd, env: calls.append(cmd) or 0)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert idealens.main(["data", "market"]) == 0
    assert calls == []


def test_shared_chroma_requires_confirmation_even_with_yes(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("CHROMA_HOST=chroma.example.test\n", encoding="utf-8")
    calls, prompts = [], []
    monkeypatch.setattr(idealens, "ENV_PATH", env)
    monkeypatch.setattr(idealens, "docker_ready", lambda report: True)
    monkeypatch.setattr(idealens, "image_exists", lambda: True)
    monkeypatch.setattr(idealens, "stream", lambda cmd, env: calls.append(cmd) or 0)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "n")
    assert idealens.main(["data", "patents", "--yes"]) == 0
    assert prompts and calls == []


def test_patent_commands_run_per_field(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(idealens, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(idealens, "docker_ready", lambda report: True)
    monkeypatch.setattr(idealens, "image_exists", lambda: True)
    monkeypatch.setattr(idealens, "stream", lambda cmd, env: calls.append(cmd) or 0)
    code = idealens.main(
        ["data", "patents", "--field-id", "SF-02", "--limit", "5", "--yes"]
    )
    assert code == 0
    assert calls == [
        idealens.compose_app(
            "python",
            "-m",
            "src.ingestion.patent_processor",
            "--field-id",
            "SF-02",
            "--limit",
            "5",
        )
    ]


def test_port_in_use_detects_listener():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert idealens.port_in_use(port)
    assert not idealens.port_in_use(port)


def test_run_handles_missing_command_and_space_in_args():
    result = idealens.run(["definitely-not-a-command-xyz"])
    assert result.returncode == 127
    echoed = idealens.run(["python", "-c", "import sys; print(sys.argv[1])", "a b"])
    assert echoed.stdout.strip() == "a b"


def test_parse_version_and_required_streamlit():
    assert idealens.parse_version("v5.6.0") >= idealens.MIN_COMPOSE
    assert idealens.parse_version("2.23.9") < idealens.MIN_COMPOSE
    assert idealens.required_version("streamlit")


def test_script_is_python39_compatible():
    import ast

    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 9))
    result = subprocess.run(
        ["python", str(SCRIPT), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "doctor" in result.stdout


def test_subprocesses_do_not_consume_stdin(monkeypatch):
    seen = []
    real_run = subprocess.run

    def spy(cmd, **kwargs):
        seen.append(kwargs.get("stdin"))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(idealens.subprocess, "run", spy)
    idealens.run(["python", "-c", "print(1)"])
    assert seen == [subprocess.DEVNULL]
    code = idealens.stream(
        ["python", "-c", "import sys; print(repr(sys.stdin.read()))"], {}
    )
    assert code == 0
