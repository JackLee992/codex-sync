# Codex Sync

Portable backup and sync for Codex user data.

This skill snapshots the parts of `~/.codex` that are safe and useful to move between machines, then restores them with explicit conflict handling.

## What It Syncs

Default:

- `skills/` excluding `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`

Excluded by default:

- `auth.json`
- `cap_sid`
- sqlite state files
- logs
- tmp
- sandbox directories

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
python codex_sync.py init --repo C:\sync\codex-data
python codex_sync.py backup --repo C:\sync\codex-data
python codex_sync.py status --repo C:\sync\codex-data
python codex_sync.py diff --repo C:\sync\codex-data
python codex_sync.py restore --repo C:\sync\codex-data --strategy conflict
```

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
5. Run `restore` with the strategy you want.
