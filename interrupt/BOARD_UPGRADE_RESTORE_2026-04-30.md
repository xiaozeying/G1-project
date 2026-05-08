# Interrupt Board Upgrade Restore

This document captures the restore procedure for the robot state that was verified on April 30, 2026.

Latest recovery delta and pitfalls are also captured in:

- `interrupt/docs/FRONTGATE_CHAIN_RECOVERY_2026-05-08.md`

Verified chain:
- Frontgate wake word
- Enter room
- Adaptive tri-language conversation
- Interruptible replies
- Timeout exit back to frontgate
- VLM visual Q&A

Primary git backup:
- Remote: `https://github.com/xiaozeying/G1`
- Branch: `g1-field-2026-04-24`
- Tag: `interrupt-frontgate-vlm-backup-2026-04-30`

Reference baseline:
- `interrupt-edge-cantonese-tts-2026-04-29`

## What Must Be Restored

Code:
- `interrupt/` from tag `interrupt-frontgate-vlm-backup-2026-04-30`
- `OM1/` workspace used by the robot

Private runtime backups:
- `interrupt/backups/private/2026-04-30-board-upgrade/robot-interrupt.env.local`
- `interrupt/backups/private/2026-04-30-board-upgrade/local-interrupt.env.local`
- `interrupt/backups/private/2026-04-30-board-upgrade/interrupt-frontgate.service`
- `interrupt/backups/private/2026-04-30-board-upgrade/interrupt-venv-freeze.txt`
- `interrupt/backups/private/2026-04-30-board-upgrade/wakeword-clean-freeze.txt`
- `interrupt/backups/private/2026-04-30-board-upgrade/om1-venv-freeze.txt`
- `interrupt/backups/private/2026-04-30-board-upgrade/device-snapshot.txt`

Runtime assumptions from the verified robot:
- Robot interrupt path: `/home/unitree/HongTu/interrupt`
- OM1 python path: `/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- Front camera device: `/dev/video2`
- USB audio card: `mvsilicon B1 usb audio`
- Frontgate service name: `interrupt-frontgate.service`

## 2026-05-07 Restore Delta For Ubuntu 22.04.5

Board upgrade recovery on May 7, 2026 confirmed these additional deltas:

- The real robot-side wakeword directory must also be restored:
  - `/home/unitree/HongTu/g1-wakeword`
  - and, if needed by legacy scripts, `/home/unitree/g1-wakeword`
- The frontgate wakeword python should come from:
  - `/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- The working Unitree network interface on this image is:
  - `enP8p1s0`
- Visual entrypoints were temporarily disabled during the first restore pass to keep the
  tri-language wakeword, adaptive dialogue, interruption, action and LED path stable:
  - `INTERRUPT_VISION_CHAT_ENABLED=0`
  - `INTERRUPT_VLM_ENABLED=0`
- `interrupt/.venv` also needs `edge-tts` available for the room-agent startup path
- Some copied OM1 virtualenv artifacts may still be x86-specific after restore; if so,
  rebuild or repair the ARM-side dependencies before testing robot action or LED paths

## Restore Order

1. Restore repository code.
   - Clone `https://github.com/xiaozeying/G1`
   - Checkout `interrupt-frontgate-vlm-backup-2026-04-30`

2. Restore private env files.
   - Put the saved `robot-interrupt.env.local` back at `~/HongTu/interrupt/.env.local`
   - Verify any secrets that may have changed, especially Gemini and proxy related settings

3. Recreate Python environments.
   - `interrupt/.venv` from `interrupt-venv-freeze.txt`
   - wakeword env from `wakeword-clean-freeze.txt`
   - `OM1/.venv` from `om1-venv-freeze.txt`
   - ensure `edge-tts` is importable from `interrupt/.venv`

4. Restore OM1 workspace and scripts.
   - Ensure `/home/unitree/HongTu/OM1` exists
   - Ensure `/home/unitree/HongTu/OM1/scripts/vim_visual_chat_smoke.py` exists

5. Restore the robot wakeword workspace.
   - Ensure `/home/unitree/HongTu/g1-wakeword` exists
   - Run `./install_arm.sh` under that directory if `wakeword-clean` is missing
   - Verify `/home/unitree/g1-wakeword/wakeword_adaptive.py` or the restored equivalent path is available to the frontgate runtime

6. Restore the user service.
   - Put `interrupt-frontgate.service` back under `~/.config/systemd/user/`
   - Run:

```bash
systemctl --user daemon-reload
systemctl --user enable interrupt-frontgate.service
systemctl --user start interrupt-frontgate.service
```

7. Verify devices.
   - Confirm `/dev/video2` still maps to the intended camera
   - Confirm the USB audio card still appears as `CARD=audio`
   - Confirm the active Unitree interface name; on the May 7 Ubuntu 22.04.5 image it was `enP8p1s0`
   - If board upgrade changes device enumeration, update `.env.local`

## Smoke Tests

Environment check:

```bash
cd ~/HongTu/interrupt
source .venv/bin/activate
python tools/check_env.py
```

Visual test without frontgate:

```bash
cd ~/HongTu/interrupt
source .venv/bin/activate
python tools/vlm_smoke_test.py "你现在面前有什么"
```

Frontgate service:

```bash
systemctl --user --no-pager --full status interrupt-frontgate.service
```

Wakeword factory sanity check:

```bash
cd ~/HongTu/interrupt
source .venv/bin/activate
python - <<'PY'
import sys
sys.path.insert(0, '/home/unitree/HongTu/interrupt')
from src.settings import load_environment, load_settings
from src.om1_wakeword_gate import factory
load_environment()
settings = load_settings('/home/unitree/HongTu/interrupt/config.yaml')
gate = factory(settings=settings)
print(type(gate).__name__)
gate.close()
PY
```

Room agent logs:

```bash
tail -f ~/HongTu/interrupt/logs/room-agent.log
```

## Expected Good Signals

- `interrupt-frontgate.service` is `active (running)`
- Wake word triggers entry into `interrupt-demo`
- `room-agent.log` shows `received job request`
- Visual questions call `ask_camera_vision`
- Successful vision log looks like:

```text
camera vision query succeeded
```

## Known Upgrade Risk Areas

- Audio card names may change after board upgrade
- `/dev/videoX` numbering may change
- Proxy settings may be required again for Gemini access
- OM1 path or python environment may be missing
- User-level systemd service may not be restored automatically
