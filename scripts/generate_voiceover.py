#!/usr/bin/env python3
"""
Stage 3b: Generate voiceover audio for each scene using OpenAI TTS.

Reads  : output/script/script.json
Writes : output/audio/scene_NNN.mp3
         output/audio/timing_metadata.json
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, load_json, save_json, format_time

SCRIPT_PATH = "output/script/script.json"
AUDIO_DIR = "output/audio"


def get_audio_duration(audio_path: str) -> float:
    """Return duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main():
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    script = load_json(SCRIPT_PATH)

    scenes = script["scenes"]
    voice = script.get("voice_type", "nova")

    ensure_dir(AUDIO_DIR)
    print(f"Generating voiceover for {len(scenes)} scenes (voice: {voice})…")

    timing: dict = {}
    total_seconds = 0.0

    for scene in scenes:
        n = scene["scene_number"]
        narration = scene.get("narration", "").strip()
        audio_path = f"{AUDIO_DIR}/scene_{n:03d}.mp3"

        if not narration:
            print(f"  Scene {n:03d}: no narration — skipping")
            continue

        if Path(audio_path).exists():
            dur = get_audio_duration(audio_path)
            timing[f"scene_{n:03d}"] = {"path": audio_path, "duration_seconds": dur}
            total_seconds += dur
            print(f"  Scene {n:03d}: cached ({dur:.1f}s) ✓")
            continue

        print(f"  Scene {n:03d}/{len(scenes)}: generating ({len(narration)} chars)…")
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=narration,
            response_format="mp3",
        )
        response.stream_to_file(audio_path)

        dur = get_audio_duration(audio_path)
        timing[f"scene_{n:03d}"] = {"path": audio_path, "duration_seconds": dur}
        total_seconds += dur
        print(f"    ✅ {dur:.1f}s")

    metadata = {
        "voice": voice,
        "total_audio_seconds": total_seconds,
        "total_formatted": format_time(total_seconds),
        "scenes": timing,
    }
    save_json(metadata, f"{AUDIO_DIR}/timing_metadata.json")

    print(f"\n✅ Voiceover complete: {metadata['total_formatted']} total audio")
    print(f"   Output: {AUDIO_DIR}/timing_metadata.json")


if __name__ == "__main__":
    main()
