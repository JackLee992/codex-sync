---
name: codex-sync
description: Backup and sync portable Codex data across machines. Use when you want to export, restore, compare, or merge Codex skills, memories, rules, and selected config between computers without copying auth tokens, logs, or machine-local state.
metadata:
---

# Codex Sync

Use this skill to keep portable Codex data aligned across multiple computers. It creates a clean sync workspace, exports selected data from `~/.codex`, and restores it with explicit conflict handling.

## What This Skill Syncs

Default portable scope:

- `skills/` except `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`

Never synced by default:

- `auth.json`
- `cap_sid`
- `logs_*.sqlite*`
- `state_*.sqlite*`
- `history.jsonl`
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

## Commands

Use `scripts/codex_sync.py`.

### Initialize a sync workspace

```powershell
python scripts/codex_sync.py init --repo C:\sync\codex-data
```

### Export current Codex data

```powershell
python scripts/codex_sync.py backup --repo C:\sync\codex-data
```

### Check differences against the sync workspace

```powershell
python scripts/codex_sync.py status --repo C:\sync\codex-data
```

### Restore into this machine

```powershell
python scripts/codex_sync.py restore --repo C:\sync\codex-data --strategy conflict
```

## Merge Strategies

- `conflict`: safe default; keep local file and write incoming copy as `*.codex-sync-incoming`
- `backup`: overwrite local file from the sync workspace
- `keep`: keep local file and skip incoming changes
- `newer`: choose the file with the newer modification time

## When To Read References

- Read `references/sync-model.md` if you need the exact repo layout or conflict behavior.

## Notes

- Treat the sync workspace as the portable source of truth, not `~/.codex` directly.
- If you sync the workspace with Git, review conflicts there first, then run `restore`.
- This skill is for portable user data, not for live process state or credentials.
