# Backup Layout

Tracked docs:
- `BOARD_UPGRADE_RESTORE_2026-04-30.md`

Private local-only backups:
- `private/2026-04-30-board-upgrade/`

The `private/` subtree is intentionally ignored by git so that real env files, service snapshots, and dependency freezes can live in the workspace without being pushed to GitHub.

Recommended workflow:

1. Before wiping or upgrading the robot disk, run:

```bash
./prepare_robot_wipe_bundle.sh
```

2. After restore, run:

```bash
./restore_robot_voice_chain.sh
```

The backup script snapshots:

- `interrupt/.env.local`
- `interrupt-frontgate.service`
- `interrupt/.venv` freeze
- `wakeword-clean` freeze
- `OM1/.venv-g1` freeze
- current device / Pulse / audio snapshot

The asset packaging script exports:

- `om1-voice-assets.tar.gz`
- `g1-wakeword-assets.tar.gz`
- `asset-manifest.txt`

If needed, the lower-level steps are still available:

```bash
./package_robot_voice_assets.sh
./backup_robot_voice_chain.sh
```
