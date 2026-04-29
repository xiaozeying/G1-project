from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.cantonese_tts import EdgeCantoneseTts, load_cantonese_tts_config
from src.settings import load_environment


def main() -> None:
    load_environment()
    config = load_cantonese_tts_config()
    print("Cantonese TTS smoke")
    print(f"enabled={config.enabled}")
    print(f"voice={config.voice}")
    print(f"rate={config.rate}")
    print(f"playback_command={config.playback_command or '<auto>'}")
    provider = EdgeCantoneseTts(config)
    print(f"available={provider.is_available()}")


if __name__ == "__main__":
    main()
