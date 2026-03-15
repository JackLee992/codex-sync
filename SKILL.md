---
name: codex-sync
description: Backup and sync portable Codex data across machines. Use when you want to export, restore, compare, or merge Codex skills, memories, rules, and selected config between computers without copying auth tokens, logs, or machine-local state.
metadata:
---

# Codex Sync

Use this skill to keep portable Codex data aligned across multiple computers. It creates a clean sync workspace, exports selected data from `~/.codex`, restores it with explicit conflict handling, and can pack that workspace into an encrypted snapshot file for syncing through GitHub or other remote storage.

## What This Skill Syncs

Default portable scope:

- `skills/` except `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`
- extra paths under `~/.codex`, such as `history.jsonl`

Never synced by default:

- `auth.json`
- `cap_sid`
- `logs_*.sqlite*`
- `state_*.sqlite*`
- `history.jsonl` unless you explicitly add it with `--extra-include history.jsonl`
- `log/`
- `tmp/`
- `.sandbox/`
- `.sandbox-bin/`

## Workflow

1. Create a sync workspace with `init`.
2. Run `backup` on the source machine.
3. Move or sync that workspace using Git, Syncthing, OneDrive, or another transport.
4. Run `status` on the destination machine to see drift.
5. Run `restore` with an explicit merge strategy.

If you do not want to sync the workspace in plaintext, create an encrypted snapshot after `backup`, publish only the encrypted file, and restore the snapshot on the other machine with the password.

## Commands

Use `scripts/codex_sync.py`.

### Initialize a sync workspace

```powershell
python scripts/codex_sync.py init --repo C:\sync\codex-data
```

To make chat history portable too:

```powershell
python scripts/codex_sync.py init --repo C:\sync\codex-data --extra-include history.jsonl
```

### Export current Codex data

```powershell
python scripts/codex_sync.py backup --repo C:\sync\codex-data
```

To include sessions and chat history:

```powershell
python scripts/codex_sync.py backup --repo C:\sync\codex-data --include skills memories rules config sessions --extra-include history.jsonl
```

### Check differences against the sync workspace

```powershell
python scripts/codex_sync.py status --repo C:\sync\codex-data
```

### Restore into this machine

```powershell
python scripts/codex_sync.py restore --repo C:\sync\codex-data --strategy conflict --preview
python scripts/codex_sync.py restore --repo C:\sync\codex-data --strategy conflict --extra-include history.jsonl
```

### Create an encrypted snapshot for GitHub

```powershell
python scripts/codex_sync.py snapshot-create --repo C:\sync\codex-data --output C:\sync\codex-data\codex-sync.snapshot
python scripts/codex_sync.py snapshot-create --repo C:\sync\codex-data --output C:\sync\snapshots --auto-name
```

This prompts for a password and writes a single encrypted file.
With `--auto-name`, the file name includes machine, platform, UTC timestamp, and scope markers such as sessions/history.

### Restore a workspace from an encrypted snapshot

```powershell
python scripts/codex_sync.py snapshot-restore --snapshot C:\sync\codex-data\codex-sync.snapshot --repo C:\sync\codex-data --force
```

This prompts for the password again before decrypting.

### Inspect snapshot metadata without decrypting it

```powershell
python scripts/codex_sync.py snapshot-info --snapshot C:\sync\codex-data\codex-sync.snapshot
python scripts/codex_sync.py snapshot-info --snapshot C:\sync\codex-data\codex-sync.snapshot --json
```

This reads only the snapshot header so you can see machine, version, runtime, and scope information before restore.

## Merge Strategies

- `conflict`: safe default; keep local file and write incoming copy as `*.codex-sync-incoming`
- `backup`: overwrite local file from the sync workspace
- `keep`: keep local file and skip incoming changes
- `newer`: choose the file with the newer modification time

`restore --preview` reports planned actions without changing local files.

## Encrypted Snapshots

- `snapshot-create` requires a password. If you do not pass `--password` or `--password-env`, it prompts and asks for confirmation.
- `snapshot-restore` requires the same password to decrypt.
- The encrypted snapshot is the file you can safely commit or sync to GitHub instead of the plaintext `data/` directory.
- The snapshot header now records scope metadata such as file count, include targets, extra paths, source machine, manifest generation time, tool version, platform info, Python version, and Codex CLI version when detectable.
- Credentials are still excluded from the snapshot because they are excluded from the sync workspace itself.

## When To Read References

- Read `references/sync-model.md` if you need the exact repo layout or conflict behavior.

## Notes

- Treat the sync workspace as the portable source of truth, not `~/.codex` directly.
- If you sync the workspace with Git, review conflicts there first, then run `restore`.
- This skill is for portable user data, not for live process state or credentials.
