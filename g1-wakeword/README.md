# G1 Wakeword

This directory contains the robot-side tri-language wakeword runtime expected by:

- `interrupt/src/om1_wakeword_gate.py`
- `OM1/scripts/wakeword_adaptive_to_om1.py`

The main entrypoint is:

- `wakeword_adaptive.py`

Its primary job is to expose a compatible `AdaptiveWakeWordSystem` class that:

- loads SenseVoice through FunASR
- keeps the tri-language wakeword table
- provides `_check_wake_word(...)`
- can still be used as a standalone microphone test tool

Default wakewords:

- `你好笨笨`
- `笨笨`
- `笨笨同学`
- `雷猴笨笨`
- `多多同学`
- `多多`
- `hello benben`
- `benben`

Recommended robot environment:

- Python 3.9 or 3.10
- `funasr==1.3.1`
- `modelscope`
- `sounddevice`
- `numpy<2`

Recommended deployment flow on Ubuntu 22.04 ARM:

```bash
cd ~/HongTu/g1-wakeword
./install_arm.sh
```

This creates or refreshes the `wakeword-clean` conda environment and downloads the
SenseVoice model cache expected by `wakeword_adaptive.py`.

When used by `interrupt/run_robot_frontgate_session.sh`, the default runtime path is:

```bash
/home/unitree/miniforge3/envs/wakeword-clean/bin/python
```
