from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import struct
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple


DEFAULT_INCLUDE = ("skills", "memories", "rules", "config")
OPTIONAL_INCLUDE = ("sessions",)
ALL_INCLUDE = DEFAULT_INCLUDE + OPTIONAL_INCLUDE
SYSTEM_SKILL_PREFIX = "skills/.system/"
SNAPSHOT_MAGIC = b"CDXSNAP1"
SNAPSHOT_TAG_SIZE = 32


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


def derive_keys(password: str, salt: bytes) -> Tuple[bytes, bytes]:
    material = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return material[:32], material[32:]


def keystream_block(enc_key: bytes, nonce: bytes, counter: int) -> bytes:
    return hmac.new(enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()


def xor_stream_file(src: Path, dst: Path, enc_key: bytes, nonce: bytes, mac_key: bytes | None = None, mac_prefix: bytes = b"") -> bytes:
    dst.parent.mkdir(parents=True, exist_ok=True)
    mac = hmac.new(mac_key, digestmod=hashlib.sha256) if mac_key is not None else None
    if mac is not None and mac_prefix:
        mac.update(mac_prefix)
    counter = 0
    with src.open("rb") as reader, dst.open("wb") as writer:
        while True:
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            output = bytearray(len(chunk))
            offset = 0
            while offset < len(chunk):
                block = keystream_block(enc_key, nonce, counter)
                counter += 1
                take = min(len(block), len(chunk) - offset)
                for idx in range(take):
                    output[offset + idx] = chunk[offset + idx] ^ block[idx]
                offset += take
            out_bytes = bytes(output)
            writer.write(out_bytes)
            if mac is not None:
                mac.update(out_bytes)
    return mac.digest() if mac is not None else b""


def get_password(args: argparse.Namespace, purpose: str, confirm: bool = False) -> str:
    if getattr(args, "password_env", None):
        value = os.environ.get(args.password_env)
        if not value:
            raise SystemExit(f"Environment variable is empty or missing: {args.password_env}")
        return value
    if getattr(args, "password", None):
        if confirm and getattr(args, "password_confirm", None) is not None and args.password != args.password_confirm:
            raise SystemExit("Password confirmation does not match.")
        return args.password

    first = getpass(f"{purpose} password: ")
    if not first:
        raise SystemExit("Password cannot be empty.")
    if confirm:
        second = getpass("Confirm password: ")
        if first != second:
            raise SystemExit("Password confirmation does not match.")
    return first


def build_snapshot_header(salt: bytes, nonce: bytes, repo: Path) -> bytes:
    header = {
        "created_at": utc_now(),
        "format": "codex-sync-snapshot",
        "hostname": socket.gethostname(),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "repo_name": repo.name,
        "salt": base64.b64encode(salt).decode("ascii"),
        "version": 1,
    }
    return json.dumps(header, sort_keys=True).encode("utf-8")


def write_snapshot_archive(repo: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tar:
        for relative in (".codex-sync", "data"):
            source = repo / relative
            if source.exists():
                tar.add(source, arcname=relative)


def ensure_snapshot_repo_layout(repo: Path, force: bool) -> None:
    if repo.exists():
        meta = repo / ".codex-sync"
        data = repo / "data"
        has_existing = meta.exists() or data.exists()
        if has_existing and not force:
            raise SystemExit(f"Target repo already contains sync data: {repo}. Use --force to replace it.")
        if force:
            if meta.exists():
                shutil.rmtree(meta)
            if data.exists():
                shutil.rmtree(data)
    repo.mkdir(parents=True, exist_ok=True)


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


def command_snapshot_create(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    ensure_repo_initialized(repo)
    output = Path(args.output).expanduser().resolve()
    password = get_password(args, "Snapshot", confirm=True)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = derive_keys(password, salt)
    header = build_snapshot_header(salt, nonce, repo)
    header_prefix = SNAPSHOT_MAGIC + struct.pack(">I", len(header)) + header

    with tempfile.TemporaryDirectory(prefix="codex-sync-pack-") as tmpdir:
        archive_path = Path(tmpdir) / "snapshot.tar.gz"
        encrypted_path = Path(tmpdir) / "snapshot.enc.bin"
        write_snapshot_archive(repo, archive_path)
        ciphertext_tag = xor_stream_file(archive_path, encrypted_path, enc_key, nonce, mac_key=mac_key, mac_prefix=header_prefix)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as writer, encrypted_path.open("rb") as reader:
            writer.write(header_prefix)
            shutil.copyfileobj(reader, writer)
            writer.write(ciphertext_tag)

    print(f"Created encrypted snapshot: {output}")


def command_snapshot_restore(args: argparse.Namespace) -> None:
    snapshot = Path(args.snapshot).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    password = get_password(args, "Snapshot", confirm=False)
    with snapshot.open("rb") as reader:
        magic = reader.read(len(SNAPSHOT_MAGIC))
        if magic != SNAPSHOT_MAGIC:
            raise SystemExit("Invalid snapshot file.")
        header_len = struct.unpack(">I", reader.read(4))[0]
        header = reader.read(header_len)
        header_obj = json.loads(header.decode("utf-8"))
        ciphertext = reader.read()
    if len(ciphertext) < SNAPSHOT_TAG_SIZE:
        raise SystemExit("Snapshot payload is truncated.")

    tag = ciphertext[-SNAPSHOT_TAG_SIZE:]
    cipher_bytes = ciphertext[:-SNAPSHOT_TAG_SIZE]
    salt = base64.b64decode(header_obj["salt"])
    nonce = base64.b64decode(header_obj["nonce"])
    enc_key, mac_key = derive_keys(password, salt)
    expected_mac = hmac.new(mac_key, digestmod=hashlib.sha256)
    expected_mac.update(SNAPSHOT_MAGIC + struct.pack(">I", len(header)) + header)
    expected_mac.update(cipher_bytes)
    expected_tag = expected_mac.digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise SystemExit("Snapshot password is incorrect or the file was tampered with.")

    ensure_snapshot_repo_layout(repo, force=args.force)
    with tempfile.TemporaryDirectory(prefix="codex-sync-unpack-") as tmpdir:
        encrypted_path = Path(tmpdir) / "snapshot.enc.bin"
        archive_path = Path(tmpdir) / "snapshot.tar.gz"
        encrypted_path.write_bytes(cipher_bytes)
        xor_stream_file(encrypted_path, archive_path, enc_key, nonce)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(repo)

    print(f"Restored encrypted snapshot into: {repo}")


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

    snapshot_create_parser = subparsers.add_parser("snapshot-create", help="Create an encrypted snapshot file from a sync workspace.")
    snapshot_create_parser.add_argument("--repo", required=True, help="Path to the sync workspace.")
    snapshot_create_parser.add_argument("--output", required=True, help="Encrypted snapshot file to create.")
    snapshot_create_parser.add_argument("--password", help="Password for non-interactive use.")
    snapshot_create_parser.add_argument("--password-confirm", help="Confirmation for non-interactive use.")
    snapshot_create_parser.add_argument("--password-env", help="Read the password from an environment variable.")
    snapshot_create_parser.set_defaults(func=command_snapshot_create)

    snapshot_restore_parser = subparsers.add_parser("snapshot-restore", help="Restore a sync workspace from an encrypted snapshot file.")
    snapshot_restore_parser.add_argument("--snapshot", required=True, help="Encrypted snapshot file to restore.")
    snapshot_restore_parser.add_argument("--repo", required=True, help="Target sync workspace directory.")
    snapshot_restore_parser.add_argument("--password", help="Password for non-interactive use.")
    snapshot_restore_parser.add_argument("--password-env", help="Read the password from an environment variable.")
    snapshot_restore_parser.add_argument("--force", action="store_true", help="Replace existing .codex-sync and data directories in the target repo.")
    snapshot_restore_parser.set_defaults(func=command_snapshot_restore)

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
