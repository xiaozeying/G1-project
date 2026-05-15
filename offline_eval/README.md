# Offline Eval Quickstart

## Goal

This folder is the starting point for Phase 1 local offline model evaluation.

It is designed to answer three questions:

1. Can a local model produce stable structured robot actions?
2. Can it stay within the allowed capability boundary?
3. Is it good enough to advance to G1 Orin real-machine testing?

## Files

| File | Purpose |
|---|---|
| `phase1_test_cases.csv` | Prompt suite for Phase 1 local evaluation |
| `results_template.csv` | Manual or scripted result capture template |
| `run_phase1_batch.py` | Batch runner that starts an isolated OM1 runtime, sends all Phase 1 prompts, and writes a results CSV |
| `../OM1/config/unitree_g1_text_arm_led_ollama_local_eval.json5` | Local OM1 evaluation config using `MockInput + OllamaLLM + local_debug` |
| `../OM1/scripts/run_local_offline_eval.sh` | Helper script to launch the local evaluation config |

## Recommended first run

### Terminal 1

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16
export OLLAMA_MODEL=gemma4
./OM1/scripts/run_local_offline_eval.sh
```

### Terminal 2

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16
python OM1/scripts/send_mock_input.py "你是谁" --port 8878
python OM1/scripts/send_mock_input.py "挥挥手" --port 8878
python OM1/scripts/send_mock_input.py "把灯调成蓝色" --port 8878
```

## First-pass workflow

| Step | Action | Output |
|---|---|---|
| 1 | Start Ollama locally and ensure the selected model is available | Local LLM service ready |
| 2 | Start OM1 local eval config | MockInput server and OM1 runtime ready |
| 3 | Send prompts from `phase1_test_cases.csv` one by one | Observe logs and action output |
| 4 | Record each result in `results_template.csv` | Structured evaluation data |
| 5 | Compare multiple models with the same prompt suite | Shortlist best candidates |

## Batch Run

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16
OM1/.venv_x86/bin/python offline_eval/run_phase1_batch.py \
  --model gemma4 \
  --port 8879 \
  --results offline_eval/results_auto_gemma4.csv
```

Notes:

| Topic | Note |
|---|---|
| Ollama | The local Ollama service must already be running and have the requested model available |
| Port | The batch runner defaults to `8879` so it does not collide with a manually-run `8878` session |
| Output | The script writes both a result CSV and a runtime log for later review |

## Promotion rule

Advance a model to real-machine Phase 2 only if:

| Metric | Minimum bar |
|---|---|
| Request success rate | >= 95 percent |
| Intent correctness | >= 90 percent |
| Action schema correctness | >= 95 percent |
| Action semantic correctness | >= 90 percent |
| Invalid action rate | <= 2 percent |
| Capability honesty | No fake navigation / vision / web claims in this config |

## Notes

| Topic | Note |
|---|---|
| Safety | This config uses `local_debug` action connectors, so it does not drive real hardware in the first round |
| Model name | Override `OLLAMA_MODEL` explicitly if your local Ollama tag is different |
| Scope | This is Phase 1 only. It is intentionally narrower than the current `interrupt` production path |
