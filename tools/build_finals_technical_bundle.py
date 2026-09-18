"""Build reproducible public technical bundles; integrity is not functional acceptance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import zipfile


SCHEMA = "visiondata-gate.technical-bundle.v1"
MAX_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 50000
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
                  "output", "outputs", "10_reports", "submission_ready", "dist", "target"}
EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".log",
                     ".zip", ".exe", ".mp4", ".mov", ".wav", ".pptx", ".pdf",
                     ".pt", ".pth", ".onnx", ".safetensors", ".ckpt"}


class BundleError(ValueError):
    """An input is unsafe, inconsistent, or not bound to the inventory."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def decode(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BundleError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise BundleError("non-finite JSON number")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise BundleError("invalid JSON evidence or manifest") from exc
    if not isinstance(value, dict):
        raise BundleError("JSON root must be an object")
    return value


def safe_name(name: str) -> None:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise BundleError("unsafe path")
    parts = name.split("/")
    for part in parts:
        if (part in {"", ".", ".."} or part.endswith((".", " "))
                or re.search(r'[\x00-\x1f<>"|?*]', part)
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)):
            raise BundleError("unsafe path")


def check_names(names) -> None:
    seen = set()
    for name in names:
        safe_name(name)
        if name.casefold() in seen:
            raise BundleError("member name collision")
        seen.add(name.casefold())


def allowed_source(name: str) -> bool:
    path = PurePosixPath(name)
    return (not any(p.lower() in EXCLUDED_PARTS for p in path.parts)
            and path.suffix.lower() not in EXCLUDED_SUFFIXES
            and not any(p.lower() == ".env" or p.lower().startswith(".env.")
                        and p.lower() not in {".env.example", ".env.template"}
                        for p in path.parts))


def check_regular(path: Path) -> None:
    for node in [path, *path.parents]:
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BundleError("symlink or reparse path refused")
    if not path.is_file():
        raise BundleError("regular file required")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise BundleError("file size limit")


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def public_text(name: str, data: bytes) -> None:
    if PurePosixPath(name).suffix.lower() not in {".json", ".md", ".txt", ".xml"}:
        raise BundleError("public evidence must be reviewed text")
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise BundleError("public evidence must be UTF-8") from exc
    if "\x00" in text or re.search(
        r"(?i)(?:[A-Z]:[\\/]+Users[\\/]|/home/|/Users/|"
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|github_pat_[A-Za-z0-9_]+|"
        r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})", text
    ):
        raise BundleError("private content in evidence")
    if name.endswith(".json"):
        decode(data)


def inventory(payload: dict[str, bytes]) -> list[dict]:
    return [{"path": name, "bytes": len(data), "sha256": digest(data)}
            for name, data in sorted(payload.items())]


def build_bundle(repository: Path, target: Path, *, allow_dirty: bool = False,
                 evidence=None, public_evidence_reviewed: bool = False) -> dict:
    repository, target = Path(repository).resolve(), Path(target).absolute()
    if target.exists():
        raise BundleError("output already exists")
    if evidence and not public_evidence_reviewed:
        raise BundleError("public evidence review declaration required")
    commit = git(repository, "rev-parse", "HEAD").decode().strip()
    dirty = bool(git(repository, "status", "--porcelain", "--untracked-files=no"))
    if dirty and not allow_dirty:
        raise BundleError("dirty tracked source; commit first or label patched worktree")
    state = "PATCHED_WORKTREE" if dirty else "CLEAN_COMMIT"
    source = {}
    if dirty:
        for row in git(repository, "ls-files", "--stage", "-z").split(b"\0"):
            if not row:
                continue
            metadata, name = row.split(b"\t", 1)
            mode, _oid, stage = metadata.decode().split()
            if mode == "120000":
                raise BundleError("git symlink refused")
            if mode not in {"100644", "100755"} or stage != "0":
                raise BundleError("submodule or unmerged source refused")
            name = name.decode("utf-8")
            safe_name(name)
            path = repository / name
            if allowed_source(name) and path.exists():
                check_regular(path)
                source[name] = path.read_bytes()
    else:
        with tarfile.open(fileobj=io.BytesIO(git(repository, "archive", "--format=tar", commit))) as archive:
            for member in archive:
                if member.isdir():
                    continue
                if member.issym() or member.islnk():
                    raise BundleError("git symlink refused")
                if not member.isfile():
                    raise BundleError("non-file source refused")
                safe_name(member.name)
                if allowed_source(member.name):
                    if member.size > MAX_FILE_BYTES:
                        raise BundleError("file size limit")
                    source[member.name] = archive.extractfile(member).read()
    if not source:
        raise BundleError("no source files")
    payload = {f"source/{name}": data for name, data in source.items()}
    evidence_names = []
    for name, path in evidence or []:
        safe_name(name)
        if "/" in name:
            raise BundleError("evidence path must be a basename")
        check_regular(Path(path).absolute())
        data = Path(path).read_bytes()
        public_text(name, data)
        key = f"evidence/{name}"
        if key in payload:
            raise BundleError("evidence collision")
        payload[key] = data
        evidence_names.append(name)
    identity = {"schema_version": SCHEMA, "source_commit": commit, "source_state": state,
                "source_files": len(source), "source_payload_sha256": digest(encode(inventory(source))),
                "source_scope": "FILTERED_TRACKED_SOURCE_NO_GIT_HISTORY",
                "untracked_files": "EXCLUDED", "capability_validation": "NOT_RUN_BY_BUNDLER",
                "privacy_review": "NOT_CERTIFIED_BY_BUNDLER",
                "installer": "NOT_INCLUDED_NOT_REBUILT",
                "presentation": "NOT_INCLUDED_IN_TECHNICAL_BUNDLE",
                "evidence_review": "PUBLIC_SYNTHETIC_REVIEW_DECLARED" if evidence else "NONE",
                "evidence_files": sorted(evidence_names)}
    payload["SOURCE_IDENTITY.json"] = encode(identity)
    payload["START_HERE.md"] = (
        "# VisionData Gate 技术提交包\n\n"
        "[项目介绍](source/README.md) · [源码版本](SOURCE_IDENTITY.json)\n\n"
        "本包保存筛选后的源码、依赖锁文件和明确选入的公开文字回执。"
        "source 内保持仓库相对目录；不包含私域数据、密钥、运行数据库、Git 历史、PPT 或安装器。\n\n"
        "完整性核验不代表功能验收、隐私认证或赛事提交成功。"
        "安装包须按各自源码与文件摘要单独验收；请以源码内复现指南重新运行。\n"
    ).encode("utf-8")
    rows = inventory(payload)
    payload["BUNDLE_MANIFEST.json"] = encode({"schema_version": SCHEMA,
        "members": rows, "payload_sha256": digest(encode(rows))})
    check_names(payload)
    if len(payload) > MAX_MEMBERS or sum(map(len, payload.values())) > MAX_BYTES:
        raise BundleError("bundle size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    return verify_bundle(target)


def verify_bundle(target: Path, *, expected_sha256: str | None = None) -> dict:
    target = Path(target)
    payload = {}
    zip_sha = None
    if target.is_dir():
        for root, dirs, files in os.walk(target, followlinks=False):
            for name in dirs + files:
                path = Path(root) / name
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise BundleError("symlink or reparse entry refused")
            for name in files:
                path = Path(root) / name
                check_regular(path.absolute())
                payload[path.relative_to(target).as_posix()] = path.read_bytes()
                if len(payload) > MAX_MEMBERS or sum(map(len, payload.values())) > MAX_BYTES:
                    raise BundleError("bundle size limit")
        if expected_sha256:
            raise BundleError("archive digest requires a ZIP")
    else:
        check_regular(target.absolute())
        zip_sha = digest(target.read_bytes())
        if expected_sha256 is not None and zip_sha != expected_sha256:
            raise BundleError("archive digest mismatch")
        with zipfile.ZipFile(target) as archive:
            infos = archive.infolist()
            # ZipInfo.filename is normalized on Windows; audit the original bytes' name too.
            check_names(i.orig_filename for i in infos)
            check_names(i.filename for i in infos)
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_BYTES:
                raise BundleError("bundle size limit")
            for item in infos:
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise BundleError("ZIP symlink refused")
                if item.is_dir() or item.file_size > MAX_FILE_BYTES:
                    raise BundleError("invalid entry size or kind")
                payload[item.filename] = archive.read(item)
    check_names(payload)
    if "BUNDLE_MANIFEST.json" not in payload:
        raise BundleError("manifest missing")
    manifest = decode(payload.pop("BUNDLE_MANIFEST.json"))
    rows = manifest.get("members")
    if (manifest.get("schema_version") != SCHEMA or not isinstance(rows, list)
            or manifest.get("payload_sha256") != digest(encode(rows))):
        raise BundleError("manifest digest mismatch")
    if rows != inventory(payload):
        raise BundleError("members inventory mismatch")
    if not {"START_HERE.md", "SOURCE_IDENTITY.json"}.issubset(payload):
        raise BundleError("required members missing")
    identity = decode(payload["SOURCE_IDENTITY.json"])
    source = {n[len("source/"):]: d for n, d in payload.items() if n.startswith("source/")}
    if (identity.get("schema_version") != SCHEMA or identity.get("source_files") != len(source)
            or identity.get("source_payload_sha256") != digest(encode(inventory(source)))
            or identity.get("source_state") not in {"CLEAN_COMMIT", "PATCHED_WORKTREE"}):
        raise BundleError("source identity digest mismatch")
    return {"integrity_status": "INTEGRITY_VERIFIED", "capability_validation": "NOT_RUN_BY_BUNDLER",
            "source_commit": identity["source_commit"], "source_state": identity["source_state"],
            "source_payload_sha256": identity["source_payload_sha256"], "source_files": len(source),
            "member_count": len(payload) + 1, "zip_sha256": zip_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--repo", type=Path, default=Path.cwd())
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--allow-dirty", action="store_true")
    build.add_argument("--evidence", action="append", default=[], metavar="NAME=FILE")
    build.add_argument("--public-evidence-reviewed", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("target", type=Path)
    verify.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if args.command == "build":
            entries = [entry.split("=", 1) for entry in args.evidence]
            if any(len(entry) != 2 for entry in entries):
                raise BundleError("evidence requires NAME=FILE")
            result = build_bundle(args.repo, args.output, allow_dirty=args.allow_dirty,
                evidence=[(n, Path(p)) for n, p in entries],
                public_evidence_reviewed=args.public_evidence_reviewed)
        else:
            result = verify_bundle(args.target, expected_sha256=args.expected_sha256)
        print(encode(result).decode("utf-8"))
        return 0
    except (BundleError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(json.dumps({"integrity_status": "HOLD", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
