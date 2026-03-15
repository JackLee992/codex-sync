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
    history.jsonl
    memories/
    rules/
    skills/
    sessions/
  codex-sync.snapshot
```

## Scope

Tracked by default:

- `skills/` excluding `.system/`
- `memories/`
- `rules/`
- `config.toml`

Optional:

- `sessions/`
- extra files or directories under `~/.codex`, such as `history.jsonl`

Excluded by default:

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
- include targets
- extra include paths
- source machine and Codex home
- tool version

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

Use this when both machines may have changed the same skill, memory, session, or extra tracked file.

Run `restore --preview` first if you want a dry run before writing anything into the target `~/.codex`.

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

## Encrypted Snapshot Mode

If you do not want the `data/` directory in plaintext on a remote service, use:

- `snapshot-create` to pack `.codex-sync/` and `data/` into one encrypted file
- `snapshot-restore` to unpack it on another machine

The password is not stored in the workspace. Without the password, the snapshot cannot be restored.
The snapshot header records metadata such as file count, include scope, extra paths, source machine, and manifest generation time.

Recommended GitHub pattern:

1. Keep a local sync workspace.
2. Create `codex-sync.snapshot`.
3. Push only the encrypted snapshot file to the remote repo.
4. Pull it on another machine and restore locally.
