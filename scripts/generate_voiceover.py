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
import time
from pathlib import Path

from openai import OpenAI, APIConnectionError, APIError, RateLimitError

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, load_json, save_json, format_time

SCRIPT_PATH = "output/script/script.json"
AUDIO_DIR = "output/audio"
VALID_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


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
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is required.", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)
    try:
        script = load_json(SCRIPT_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to load {SCRIPT_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)

    scenes = script["scenes"]
    voice = script.get("voice_type", "nova")
    if voice not in VALID_VOICES:
        print(f"ERROR: invalid voice '{voice}'.", file=sys.stderr)
        sys.exit(1)

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
        temp_path = f"{audio_path}.tmp"
        last_exc = None
        for attempt in range(3):
            try:
                response = client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=narration,
                    response_format="mp3",
                )
                response.stream_to_file(temp_path)
                Path(temp_path).replace(audio_path)
                break
            except (RateLimitError, APIConnectionError, APIError) as exc:
                last_exc = exc
                if attempt < 2:
                    wait_seconds = 2 ** attempt
                    print(f"    retrying in {wait_seconds}s due to transient API error")
                    time.sleep(wait_seconds)
                else:
                    print(f"ERROR: failed to generate scene {n:03d} audio: {last_exc}", file=sys.stderr)
                    sys.exit(1)

        dur = get_audio_duration(audio_path)
        if dur <= 0:
            print(f"ERROR: generated invalid audio duration for scene {n:03d}.", file=sys.stderr)
            sys.exit(1)
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
