from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple


DEFAULT_INCLUDE = ("skills", "memories", "rules", "config")
OPTIONAL_INCLUDE = ("sessions",)
ALL_INCLUDE = DEFAULT_INCLUDE + OPTIONAL_INCLUDE
SYSTEM_SKILL_PREFIX = "skills/.system/"


@dataclass
class FileEntry:
    relative_path: str
    sha256: str
    size: int
    mtime: float


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_include(values: Iterable[str]) -> List[str]:
    result = []
    for value in values:
        lowered = value.strip().lower()
        if lowered not in ALL_INCLUDE:
            raise SystemExit(f"Unsupported include target: {value}")
        if lowered not in result:
            result.append(lowered)
    return result


def codex_home_from_arg(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def repo_paths(repo: Path) -> Tuple[Path, Path, Path]:
    meta = repo / ".codex-sync"
    data = repo / "data"
    return meta, meta / "config.json", meta / "manifest.json"


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_repo_initialized(repo: Path) -> Tuple[Path, Path, Path]:
    meta, config_path, manifest_path = repo_paths(repo)
    if not config_path.exists():
        raise SystemExit(f"Sync repo is not initialized: {repo}")
    (repo / "data").mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    return meta, config_path, manifest_path


def iter_selected_files(codex_home: Path, include: Iterable[str]) -> Iterator[Tuple[str, Path]]:
    include_set = set(include)
    if "config" in include_set:
        config_path = codex_home / "config.toml"
        if config_path.exists():
            yield "config.toml", config_path

    for bucket in ("memories", "rules", "sessions", "skills"):
        include_name = "config" if bucket == "config.toml" else bucket
        if include_name not in include_set:
            continue
        root = codex_home / bucket
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(codex_home).as_posix()
            if relative.startswith(SYSTEM_SKILL_PREFIX):
                continue
            yield relative, path


def manifest_from_source(codex_home: Path, include: Iterable[str]) -> Dict[str, FileEntry]:
    entries: Dict[str, FileEntry] = {}
    for relative, path in iter_selected_files(codex_home, include):
        stat = path.stat()
        entries[relative] = FileEntry(
            relative_path=relative,
            sha256=sha256_file(path),
            size=stat.st_size,
            mtime=stat.st_mtime,
        )
    return entries


def manifest_to_json(entries: Dict[str, FileEntry]) -> dict:
    return {
        "files": {
            key: {
                "sha256": entry.sha256,
                "size": entry.size,
                "mtime": entry.mtime,
            }
            for key, entry in sorted(entries.items())
        }
    }


def load_manifest_entries(path: Path) -> Dict[str, FileEntry]:
    payload = load_json(path, {"files": {}})
    files = payload.get("files", {})
    entries: Dict[str, FileEntry] = {}
    for relative, meta in files.items():
        entries[relative] = FileEntry(
            relative_path=relative,
            sha256=meta["sha256"],
            size=meta["size"],
            mtime=meta["mtime"],
        )
    return entries


def copy_with_mtime(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def remove_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def command_init(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    include = normalize_include(args.include or DEFAULT_INCLUDE)
    meta, config_path, manifest_path = repo_paths(repo)
    meta.mkdir(parents=True, exist_ok=True)
    (repo / "data").mkdir(parents=True, exist_ok=True)
    save_json(
        config_path,
        {
            "created_at": utc_now(),
            "default_include": include,
            "machine": socket.gethostname(),
            "version": 1,
        },
    )
    if not manifest_path.exists():
        save_json(manifest_path, {"files": {}, "generated_at": utc_now()})
    print(f"Initialized codex-sync repo: {repo}")
    print(f"Default include: {', '.join(include)}")


def command_backup(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    _, config_path, manifest_path = ensure_repo_initialized(repo)
    config = load_json(config_path, {})
    include = normalize_include(args.include or config.get("default_include", DEFAULT_INCLUDE))
    codex_home = codex_home_from_arg(args.codex_home)
    data_root = repo / "data"

    current = manifest_from_source(codex_home, include)
    previous = load_manifest_entries(manifest_path)

    for relative, entry in current.items():
        copy_with_mtime(codex_home / relative, data_root / relative)

    removed = sorted(set(previous) - set(current))
    for relative in removed:
        target = data_root / relative
        if target.exists():
            target.unlink()

    remove_empty_dirs(data_root)
    save_json(
        manifest_path,
        {
            "files": manifest_to_json(current)["files"],
            "generated_at": utc_now(),
            "include": include,
            "machine": socket.gethostname(),
            "source_codex_home": str(codex_home),
        },
    )

    print(f"Backed up {len(current)} files to {repo}")
    print(f"Removed {len(removed)} files from snapshot")


def compare_local_to_repo(codex_home: Path, repo: Path, include: Iterable[str]) -> Tuple[List[str], List[str], List[str], List[str]]:
    local = manifest_from_source(codex_home, include)
    repo_manifest = load_manifest_entries(repo / ".codex-sync" / "manifest.json")
    local_keys = set(local)
    repo_keys = set(repo_manifest)

    only_local = sorted(local_keys - repo_keys)
    only_repo = sorted(repo_keys - local_keys)
    identical = sorted(key for key in local_keys & repo_keys if local[key].sha256 == repo_manifest[key].sha256)
    changed = sorted(key for key in local_keys & repo_keys if local[key].sha256 != repo_manifest[key].sha256)
    return only_local, only_repo, changed, identical


def command_status(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    _, config_path, manifest_path = ensure_repo_initialized(repo)
    if not manifest_path.exists():
        raise SystemExit("Manifest missing; run backup first.")
    config = load_json(config_path, {})
    include = normalize_include(args.include or config.get("default_include", DEFAULT_INCLUDE))
    codex_home = codex_home_from_arg(args.codex_home)

    only_local, only_repo, changed, identical = compare_local_to_repo(codex_home, repo, include)

    print(f"Local only : {len(only_local)}")
    print(f"Repo only  : {len(only_repo)}")
    print(f"Changed    : {len(changed)}")
    print(f"Identical  : {len(identical)}")
    if args.verbose:
        for label, items in (
            ("LOCAL_ONLY", only_local),
            ("REPO_ONLY", only_repo),
            ("CHANGED", changed),
        ):
            if items:
                print(f"\n[{label}]")
                for item in items:
                    print(item)


def command_diff(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    _, config_path, manifest_path = ensure_repo_initialized(repo)
    if not manifest_path.exists():
        raise SystemExit("Manifest missing; run backup first.")
    config = load_json(config_path, {})
    include = normalize_include(args.include or config.get("default_include", DEFAULT_INCLUDE))
    codex_home = codex_home_from_arg(args.codex_home)

    only_local, only_repo, changed, _ = compare_local_to_repo(codex_home, repo, include)
    local = manifest_from_source(codex_home, include)
    repo_manifest = load_manifest_entries(manifest_path)

    for label, items in (
        ("LOCAL_ONLY", only_local),
        ("REPO_ONLY", only_repo),
    ):
        if items:
            print(f"[{label}]")
            for item in items:
                print(item)
            print()

    if changed:
        print("[CHANGED]")
        for item in changed:
            local_entry = local[item]
            repo_entry = repo_manifest[item]
            print(item)
            print(f"  local_sha256: {local_entry.sha256}")
            print(f"  repo_sha256 : {repo_entry.sha256}")
            print(f"  local_mtime : {local_entry.mtime}")
            print(f"  repo_mtime  : {repo_entry.mtime}")
            print()
    elif not only_local and not only_repo:
        print("No differences.")


def write_incoming_conflict(dst: Path, src: Path) -> Path:
    conflict_path = dst.with_name(dst.name + ".codex-sync-incoming")
    copy_with_mtime(src, conflict_path)
    return conflict_path


def command_restore(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    _, config_path, manifest_path = ensure_repo_initialized(repo)
    config = load_json(config_path, {})
    include = normalize_include(args.include or config.get("default_include", DEFAULT_INCLUDE))
    codex_home = codex_home_from_arg(args.codex_home)
    data_root = repo / "data"
    manifest = load_manifest_entries(manifest_path)
    strategy = args.strategy

    copied = 0
    skipped = 0
    conflicts = 0
    overwritten = 0

    for relative, incoming in sorted(manifest.items()):
        top_level = relative.split("/", 1)[0]
        normalized_top = "config" if relative == "config.toml" else top_level
        if normalized_top not in include:
            continue
        src = data_root / relative
        dst = codex_home / relative
        if not dst.exists():
            copy_with_mtime(src, dst)
            copied += 1
            continue

        local_hash = sha256_file(dst)
        if local_hash == incoming.sha256:
            skipped += 1
            continue

        if strategy == "backup":
            copy_with_mtime(src, dst)
            overwritten += 1
            continue

        if strategy == "keep":
            skipped += 1
            continue

        if strategy == "newer":
            local_mtime = dst.stat().st_mtime
            if incoming.mtime >= local_mtime:
                copy_with_mtime(src, dst)
                overwritten += 1
            else:
                skipped += 1
            continue

        write_incoming_conflict(dst, src)
        conflicts += 1

    print(f"Copied      : {copied}")
    print(f"Overwritten : {overwritten}")
    print(f"Skipped     : {skipped}")
    print(f"Conflicts   : {conflicts}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup and sync portable Codex data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a sync workspace.")
    init_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    init_parser.add_argument(
        "--include",
        nargs="+",
        help=f"Default include set: {', '.join(ALL_INCLUDE)}",
    )
    init_parser.set_defaults(func=command_init)

    backup_parser = subparsers.add_parser("backup", help="Snapshot Codex data into the sync workspace.")
    backup_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    backup_parser.add_argument("--codex-home", help="Override Codex home. Defaults to ~/.codex")
    backup_parser.add_argument("--include", nargs="+", help=f"Include set: {', '.join(ALL_INCLUDE)}")
    backup_parser.set_defaults(func=command_backup)

    status_parser = subparsers.add_parser("status", help="Compare local Codex data with the sync workspace.")
    status_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    status_parser.add_argument("--codex-home", help="Override Codex home. Defaults to ~/.codex")
    status_parser.add_argument("--include", nargs="+", help=f"Include set: {', '.join(ALL_INCLUDE)}")
    status_parser.add_argument("--verbose", action="store_true", help="List differing files.")
    status_parser.set_defaults(func=command_status)

    diff_parser = subparsers.add_parser("diff", help="List file-level differences in detail.")
    diff_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    diff_parser.add_argument("--codex-home", help="Override Codex home. Defaults to ~/.codex")
    diff_parser.add_argument("--include", nargs="+", help=f"Include set: {', '.join(ALL_INCLUDE)}")
    diff_parser.set_defaults(func=command_diff)

    restore_parser = subparsers.add_parser("restore", help="Restore sync workspace data into local Codex.")
    restore_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    restore_parser.add_argument("--codex-home", help="Override Codex home. Defaults to ~/.codex")
    restore_parser.add_argument("--include", nargs="+", help=f"Include set: {', '.join(ALL_INCLUDE)}")
    restore_parser.add_argument(
        "--strategy",
        choices=("conflict", "backup", "keep", "newer"),
        default="conflict",
        help="How to handle differing local files.",
    )
    restore_parser.set_defaults(func=command_restore)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
