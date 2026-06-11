#!/usr/bin/env python3
"""
Stage 4b: Quality checks on the assembled video.

Validates:
  - Video file exists and is readable
  - Duration is within the 30-60 min target (±5 min tolerance)
  - Video and audio streams are present
  - Resolution is at least 1280×720
  - All scene images and audio files exist
  - Thumbnail exists
  - File size is reasonable

Exits with code 1 if any check fails so the workflow stops before upload.
Writes output/video/qc_report.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from utils import load_json, save_json

VIDEO_PATH = "output/video/final_video.mp4"
SCRIPT_PATH = "output/script/script.json"
AUDIO_DIR = "output/audio"
ASSETS_DIR = "output/assets/images"
REPORT_PATH = "output/video/qc_report.json"

MIN_DURATION_MIN = 25   # 5 min below target floor
MAX_DURATION_MIN = 70   # 10 min above target ceiling


def ffprobe_json(path: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration,size,bit_rate",
         "-show_entries", "stream=codec_type,codec_name,width,height",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON: {exc}") from exc


def main():
    checks = []
    passed = failed = 0

    def check(name: str, ok: bool, msg: str):
        nonlocal passed, failed
        status = "PASS" if ok else "FAIL"
        checks.append({"check": name, "result": status, "message": msg})
        icon = "✅" if ok else "❌"
        print(f"  {icon} [{status}] {name}: {msg}")
        if ok:
            passed += 1
        else:
            failed += 1
        return ok

    print("Running quality checks…\n")
    script = load_json(SCRIPT_PATH)
    scenes = script["scenes"]
    target_min = script.get("duration_minutes", 45)

    # 1. File exists
    video_exists = Path(VIDEO_PATH).exists()
    check("video_exists", video_exists, f"File exists at {VIDEO_PATH}")

    # 2. Probe video
    info = {"format": {}, "streams": []}
    duration_s = 0.0
    duration_min = 0.0
    size_mb = 0.0
    if video_exists:
        try:
            info = ffprobe_json(VIDEO_PATH)
        except RuntimeError as exc:
            check("ffprobe_readable", False, str(exc))
        duration_s = float(info.get("format", {}).get("duration") or 0)
        duration_min = duration_s / 60
        size_raw = info.get("format", {}).get("size")
        size_mb = int(size_raw) / (1024 * 1024) if size_raw else 0.0
    else:
        check("ffprobe_readable", False, "Skipped: video file missing")

    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    check("duration_range",
          MIN_DURATION_MIN <= duration_min <= MAX_DURATION_MIN,
          f"{duration_min:.1f} min (target {target_min} min, acceptable {MIN_DURATION_MIN}-{MAX_DURATION_MIN})")

    check("has_video_stream", bool(video_streams),
          f"Video stream: {[s['codec_name'] for s in video_streams] or 'MISSING'}")

    check("has_audio_stream", bool(audio_streams),
          f"Audio stream: {[s['codec_name'] for s in audio_streams] or 'MISSING'}")

    if video_streams:
        w = video_streams[0].get("width", 0)
        h = video_streams[0].get("height", 0)
        check("resolution", w >= 1280 and h >= 720, f"{w}×{h} (min 1280×720)")

    # 3. All scene assets exist
    missing_img = [s["scene_number"] for s in scenes
                   if not Path(f"{ASSETS_DIR}/scene_{s['scene_number']:03d}.png").exists()]
    check("all_images_exist", not missing_img,
          f"All {len(scenes)} scene images present" if not missing_img
          else f"Missing scene images: {missing_img}")

    missing_aud = [s["scene_number"] for s in scenes
                   if not Path(f"{AUDIO_DIR}/scene_{s['scene_number']:03d}.mp3").exists()]
    check("all_audio_exists", not missing_aud,
          f"All {len(scenes)} scene audio files present" if not missing_aud
          else f"Missing scene audio: {missing_aud}")

    # 4. Thumbnail
    check("thumbnail_exists", Path("output/video/thumbnail.jpg").exists(),
          "Thumbnail file present")

    # 5. File size sanity (min 5 MB — avoids empty/broken renders)
    check("file_size_ok", size_mb >= 5,
          f"{size_mb:.1f} MB (minimum 5 MB)")

    # ---- Report ----
    report = {
        "overall": "PASS" if failed == 0 else "FAIL",
        "total_checks": passed + failed,
        "passed": passed,
        "failed": failed,
        "video_duration_seconds": duration_s,
        "video_duration_minutes": round(duration_min, 2),
        "file_size_mb": round(size_mb, 2),
        "checks": checks,
    }
    save_json(report, REPORT_PATH)

    print(f"\n{'='*50}")
    print(f"QC Result : {report['overall']}")
    print(f"Passed    : {passed}/{passed + failed}")
    print(f"Report    : {REPORT_PATH}")

    if failed > 0:
        print(f"\n❌ {failed} check(s) failed. Fix issues before uploading.")
        sys.exit(1)

    print("\n✅ All quality checks passed!")


if __name__ == "__main__":
    main()
