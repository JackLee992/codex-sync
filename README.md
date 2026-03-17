# Codex Sync

Portable backup and sync for Codex user data.

This skill snapshots the parts of `~/.codex` that are safe and useful to move between machines, then restores them with explicit conflict handling.

It also supports encrypted snapshots so the sync artifact itself can be pushed to GitHub without exposing the plaintext contents.

## What It Syncs

Default:

- `skills/` excluding `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`
- extra paths under `~/.codex`, such as `history.jsonl`

Excluded by default:

- `auth.json`
- `cap_sid`
- sqlite state files
- logs
- tmp
- sandbox directories
- `*.codex-sync-incoming` conflict copies

## Install

```powershell
python "$env:USERPROFILE\\.codex\\skills\\.system\\skill-installer\\scripts\\install-skill-from-github.py" `
  --repo JackLee992/codex-sync `
  --path . `
  --name codex-sync `
  --method download `
  --ref master
```

## Commands

```powershell
python codex_sync.py init --repo C:\sync\codex-data --extra-include history.jsonl
python codex_sync.py backup --repo C:\sync\codex-data --include skills memories rules config sessions --extra-include history.jsonl
python codex_sync.py status --repo C:\sync\codex-data --extra-include history.jsonl
python codex_sync.py diff --repo C:\sync\codex-data
python codex_sync.py restore --repo C:\sync\codex-data --strategy conflict --preview
python codex_sync.py restore --repo C:\sync\codex-data --strategy conflict --extra-include history.jsonl
python codex_sync.py snapshot-create --repo C:\sync\codex-data --output C:\sync\codex-data\codex-sync.snapshot
python codex_sync.py snapshot-create --repo C:\sync\codex-data --output C:\sync\snapshots --auto-name
python codex_sync.py snapshot-verify --snapshot C:\sync\snapshots\codex-sync-desktop-a-windows-20260315T120000Z-sess-hist-f118.snapshot
python codex_sync.py snapshot-info --snapshot C:\sync\snapshots\codex-sync-desktop-a-windows-20260315T120000Z-sess-hist-f118.snapshot
python codex_sync.py snapshot-restore --snapshot C:\sync\codex-data\codex-sync.snapshot --repo C:\sync\codex-data --force
```

`--extra-include` accepts file or directory paths relative to `~/.codex`. The most useful example is `history.jsonl`.
`snapshot-create --auto-name` generates a filename like `codex-sync-<machine>-<platform>-<timestamp>-<scope>.snapshot`.
`snapshot-create` now verifies the written snapshot by default. Use `--no-verify` only when you intentionally want to skip the post-write check.
`snapshot-verify` checks a candidate password and confirms that the encrypted archive can be opened without writing anything into `~/.codex`.
`snapshot-info` reads the unencrypted header only, so you can inspect version, machine, platform, and scope before restoring.

## Restore Strategies

- `conflict` - keep local file and write incoming copy as `*.codex-sync-incoming`
- `backup` - overwrite local file from snapshot
- `keep` - keep local file and skip incoming copy
- `newer` - choose the newer file by mtime

## Typical Workflow

1. Run `init` once for a sync workspace.
2. Run `backup` on machine A.
3. Move the workspace using Git, Syncthing, OneDrive, or similar.
4. Run `diff` or `status` on machine B.
5. Run `restore --preview` to inspect planned actions.
6. Run `restore` with the strategy you want.

## Encrypted Snapshot Flow

1. Run `backup` on machine A.
2. Run `snapshot-create` and set a deliberate password that you will keep or record outside the snapshot itself.
3. Sync only the encrypted snapshot file to GitHub.
4. Run `snapshot-verify` if you want to confirm the password before writing any files on machine B.
5. On machine B, pull the snapshot file and run `snapshot-restore`.
6. Enter the same password, then run `diff` or `restore`.

## What Changed In This Version

- `history.jsonl` and similar files can be included via `--extra-include`
- workspace manifests now record include scope, extra paths, source machine, and tool version
- workspace manifests and snapshot headers now record tool, platform, Python, and Codex CLI version info when available
- encrypted snapshot headers now carry enough metadata to inspect the snapshot scope after restore
- `snapshot-create` now verifies newly written snapshots by default and `snapshot-verify` checks passwords without restoring files
- snapshot files can now be auto-named with machine/platform/time markers for easier multi-machine comparison
- `restore --preview` shows copy/overwrite/conflict actions without modifying local files
