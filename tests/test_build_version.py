"""배포 확인용 버전 표시(build_version)가 .git 파일에서 커밋을 올바르게 읽는지 검증한다."""

from frontend.live import build_version

SHA = "0123456789abcdef0123456789abcdef01234567"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_detached_head(tmp_path):
    write(tmp_path / ".git" / "HEAD", SHA + "\n")
    assert build_version(tmp_path) == "0123456"


def test_branch_ref_file(tmp_path):
    write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(tmp_path / ".git" / "refs" / "heads" / "main", SHA + "\n")
    assert build_version(tmp_path) == "0123456"


def test_packed_refs(tmp_path):
    write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(
        tmp_path / ".git" / "packed-refs",
        f"# pack-refs with: peeled fully-peeled sorted\n{SHA} refs/heads/main\n",
    )
    assert build_version(tmp_path) == "0123456"


def test_missing_git_dir(tmp_path):
    assert build_version(tmp_path) == ""


def test_unresolvable_ref(tmp_path):
    write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    assert build_version(tmp_path) == ""


def test_invalid_head_content(tmp_path):
    write(tmp_path / ".git" / "HEAD", "not-a-sha\n")
    assert build_version(tmp_path) == ""
