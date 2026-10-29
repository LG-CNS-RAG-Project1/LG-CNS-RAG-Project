"""사업기획 근거 자료집 실행 폴더의 저장·검증.

- 실행은 `data/market/runs/{area}/{idea_hash[:12]}/{run_id}/`에 한 번만 쓴다.
  `.staging-{run_id}`에 모두 쓴 뒤 이름을 바꿔 게시하므로 미완료 실행은 목록에 나오지 않는다.
- manifest.json에 게시 시점 파일의 SHA-256을 기록하고, 읽을 때 대조한다.
  `bodies/`·`raw_responses/`는 없어도 replay가 가능하며(선택 파일), 내용이 다르면 오류다.
- 검토·사용자 입력은 `revisions/{n}.json`과 `semantic/{n}.json`을 새 파일로만 추가한다.
"""

import hashlib
import json
import os
import shutil
import uuid
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from src.planner.schemas import RunManifest

ROOT_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT_DIR / "data" / "market" / "runs"
OPTIONAL_PREFIXES = ("bodies/", "raw_responses/")
REQUIRED_FILES = (
    "idea.json",
    "query_plan.json",
    "selection.json",
    "articles.jsonl",
    "extraction.jsonl",
    "anchors.jsonl",
    "revisions/0000.json",
    "semantic/0000.json",
)


class RunIntegrityError(RuntimeError):
    """실행 폴더의 파일이 manifest 기록과 다르거나 필수 파일이 없다."""


def _default(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def canonical_json(obj) -> bytes:
    """키 정렬·공백 없는 UTF-8 JSON. 해시와 저장에 같은 직렬화를 쓴다."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_default
    ).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def semantic_hash(result) -> str:
    """의미 결과의 SHA-256. 실행 ID·기준일·소요 시간은 결과에 넣지 않는다."""
    return sha256_hex(canonical_json(result))


def idea_hash(idea, area_id: str) -> str:
    """구조화 아이디어와 분야 ID의 정규 JSON 해시."""
    payload = {"idea": idea.model_dump(mode="json"), "area": area_id}
    return sha256_hex(canonical_json(payload))


def new_run_id(as_of: str) -> str:
    """기준일(YYYYMMDD)과 무작위 8자로 실행 ID를 만든다."""
    return f"{as_of}-{uuid.uuid4().hex[:8]}"


def run_dir(root: Path, area_id: str, idea_digest: str, run_id: str) -> Path:
    return Path(root) / area_id / idea_digest[:12] / run_id


def _write_new(path: Path, data: bytes) -> None:
    """파일을 새로 만든다. 이미 있으면 FileExistsError로 덮어쓰기를 막는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as f:
        f.write(data)


def _json_bytes(obj) -> bytes:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return (
        json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1, default=_default)
        + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows) -> bytes:
    return b"".join(canonical_json(row) + b"\n" for row in rows)


class Staging:
    """게시 전 실행 폴더. 모든 파일은 새로 만들기만 한다."""

    def __init__(self, root: Path, area_id: str, idea_digest: str, run_id: str):
        self.root = Path(root)
        self.final = run_dir(self.root, area_id, idea_digest, run_id)
        if self.final.exists():
            raise FileExistsError(f"run already exists: {self.final}")
        self.path = self.root / f".staging-{run_id}"
        self.path.mkdir(parents=True, exist_ok=False)

    def write_json(self, name: str, obj) -> None:
        _write_new(self.path / name, _json_bytes(obj))

    def write_jsonl(self, name: str, rows) -> None:
        _write_new(self.path / name, _jsonl_bytes(rows))

    def write_text(self, name: str, text: str) -> None:
        _write_new(self.path / name, text.encode("utf-8"))

    def publish(self, manifest: RunManifest) -> Path:
        """파일 해시를 manifest에 기록하고 최종 경로로 이름을 바꾼다."""
        files = {}
        for path in sorted(self.path.rglob("*")):
            if path.is_file():
                files[path.relative_to(self.path).as_posix()] = sha256_hex(
                    path.read_bytes()
                )
        manifest = manifest.model_copy(update={"files": files})
        _write_new(self.path / "manifest.json", _json_bytes(manifest))
        if self.final.exists():
            raise FileExistsError(f"run already exists: {self.final}")
        self.final.parent.mkdir(parents=True, exist_ok=True)
        os.rename(self.path, self.final)
        return self.final

    def discard(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def read_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def verify_run(path: Path) -> dict:
    """manifest의 파일 해시를 대조한다. 결과: {'missing_optional': [...]}.

    필수 파일이 없거나 어떤 파일이든 내용이 다르면 RunIntegrityError.
    """
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise RunIntegrityError(f"manifest.json 없음: {path}")
    manifest = RunManifest.model_validate(read_json(manifest_path))
    missing_optional, errors = [], []
    for name in REQUIRED_FILES:
        if name not in manifest.files:
            errors.append(f"manifest에 필수 파일 기록 없음: {name}")
    for name, digest in manifest.files.items():
        file_path = path / name
        if not file_path.exists():
            if name.startswith(OPTIONAL_PREFIXES):
                missing_optional.append(name)
            else:
                errors.append(f"파일 없음: {name}")
            continue
        if sha256_hex(file_path.read_bytes()) != digest:
            errors.append(f"해시 불일치: {name}")
    if errors:
        raise RunIntegrityError("; ".join(errors))
    return {"manifest": manifest, "missing_optional": missing_optional}


def latest_revision(path: Path) -> int:
    revisions = sorted((Path(path) / "revisions").glob("[0-9][0-9][0-9][0-9].json"))
    return int(revisions[-1].stem) if revisions else 0


def load_revision(path: Path, revision: int) -> tuple[dict, dict, str]:
    """검토 입력·의미 결과·저장 해시를 읽는다. 0번 이후 파일은 자체 해시로 대조한다."""
    path = Path(path)
    name = f"{revision:04d}"
    rev_bytes = (path / "revisions" / f"{name}.json").read_bytes()
    sem_bytes = (path / "semantic" / f"{name}.json").read_bytes()
    stored = (path / "semantic" / f"{name}.sha256").read_text("utf-8").strip()
    if revision:
        rev_hash = (path / "revisions" / f"{name}.sha256").read_text("utf-8").strip()
        if sha256_hex(rev_bytes) != rev_hash:
            raise RunIntegrityError(f"검토 입력 해시 불일치: revisions/{name}.json")
    return json.loads(rev_bytes), json.loads(sem_bytes), stored


def write_semantic(target, revision: int, payload: dict, semantic) -> str:
    """검토 입력과 의미 결과를 새 파일로 쓴다. target은 Staging 또는 게시된 실행 경로."""
    name = f"{revision:04d}"
    digest = semantic_hash(semantic)
    base = target.path if isinstance(target, Staging) else Path(target)
    rev_bytes = _json_bytes(payload)
    _write_new(base / "revisions" / f"{name}.json", rev_bytes)
    if revision:
        _write_new(
            base / "revisions" / f"{name}.sha256", sha256_hex(rev_bytes).encode()
        )
    _write_new(base / "semantic" / f"{name}.json", _json_bytes(semantic))
    _write_new(base / "semantic" / f"{name}.sha256", digest.encode())
    return digest


def list_runs(root: Path = RUNS_DIR, area_id: str | None = None) -> list[dict]:
    """게시된 실행의 manifest 요약을 최신순으로 반환한다. 읽을 수 없는 폴더는 건너뛴다."""
    root = Path(root)
    if not root.exists():
        return []
    pattern = f"{area_id}/*/*/manifest.json" if area_id else "*/*/*/manifest.json"
    runs = []
    for manifest_path in root.glob(pattern):
        try:
            manifest = RunManifest.model_validate(read_json(manifest_path))
        except (OSError, ValueError):
            continue
        runs.append({"path": manifest_path.parent, "manifest": manifest})
    return sorted(runs, key=lambda r: r["manifest"].run_id, reverse=True)


def find_run(root: Path, run_ref: str) -> Path:
    """실행 경로나 run_id로 실행 폴더를 찾는다."""
    candidate = Path(run_ref)
    if (candidate / "manifest.json").exists():
        return candidate
    for run in list_runs(root):
        if run["manifest"].run_id == run_ref:
            return run["path"]
    raise FileNotFoundError(f"실행을 찾지 못함: {run_ref}")
