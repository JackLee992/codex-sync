# Sync Model

## Purpose

`codex-sync` snapshots portable Codex data into a dedicated sync workspace. That workspace can then be moved between machines by any transport layer you prefer.

## Workspace Layout

```text
<repo>/
  .codex-sync/
    config.json
    manifest.json
  data/
    config.toml
    memories/
    rules/
    skills/
    sessions/
```

## Scope

Tracked by default:

- `skills/` excluding `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`

Excluded:

- auth and session tokens
- sqlite databases and WAL/SHM files
- logs and tmp directories
- sandbox directories
- machine-local runtime state

## Backup

`backup` walks the selected scope under `~/.codex`, copies files into `data/`, and writes a manifest with:

- relative path
- sha256
- file size
- source mtime

Files removed from the source are removed from the workspace on the next backup if they are still under the tracked scope.

## Restore

`restore` compares workspace files with the local `~/.codex` target.

Outcomes:

- missing local file -> copied from workspace
- identical local file -> skipped
- different local file -> handled by selected strategy

### Conflict Strategy

With `--strategy conflict`, the local file stays untouched and the incoming file is written beside it as:

```text
<filename>.codex-sync-incoming
```

Use this when both machines may have changed the same skill or memory file.

## Status

`status` compares the current machine against the sync workspace and reports counts for:

- only in local Codex
- only in workspace
- changed
- identical

## Recommendation

Use one sync workspace per Codex identity. Keep that workspace in:

- a Git repo for reviewable history
- a cloud-synced folder for fast personal sync
- Syncthing if you want peer-to-peer sync
