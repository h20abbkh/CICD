#!/usr/bin/env python3
"""
Stage 3a: Generate a visual image for each scene using DALL-E 3.

Reads  : output/script/script.json
Writes : output/assets/images/scene_NNN.png
         output/assets/image_metadata.json

Set USE_PLACEHOLDER_IMAGES=true to skip DALL-E and use cheap coloured
placeholder images — useful for testing the pipeline without API costs.
"""

import json
import os
import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, load_json, save_json

SCRIPT_PATH = "output/script/script.json"
ASSETS_DIR = "output/assets/images"
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080

USE_PLACEHOLDERS = os.environ.get("USE_PLACEHOLDER_IMAGES", "false").lower() == "true"

PLACEHOLDER_COLORS = [
    (41, 128, 185), (39, 174, 96), (142, 68, 173),
    (211, 84, 0), (44, 62, 80), (22, 160, 133),
    (192, 57, 43), (243, 156, 18), (26, 188, 156),
]


def _load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def generate_placeholder_image(scene: dict, output_path: str):
    color = PLACEHOLDER_COLORS[scene["scene_number"] % len(PLACEHOLDER_COLORS)]
    img = Image.new("RGB", (OUTPUT_WIDTH, OUTPUT_HEIGHT), color)
    draw = ImageDraw.Draw(img)

    title = scene.get("title", f"Scene {scene['scene_number']}")
    desc = scene.get("visual_description", "")[:100]

    draw.text((OUTPUT_WIDTH // 2, OUTPUT_HEIGHT // 2 - 60),
              title, fill="white", font=_load_font(60), anchor="mm")
    draw.text((OUTPUT_WIDTH // 2, OUTPUT_HEIGHT // 2 + 60),
              desc, fill=(220, 220, 220), font=_load_font(30), anchor="mm")
    draw.text((OUTPUT_WIDTH // 2, 50),
              f"Scene {scene['scene_number']}", fill=(200, 200, 200), font=_load_font(28), anchor="mt")

    img.save(output_path, "PNG")


def generate_dalle_image(client: OpenAI, scene: dict, output_path: str, style: str):
    base_prompt = scene.get("visual_prompt") or scene.get("visual_description", "abstract background")
    prompt = f"{base_prompt}. Visual style: {style}. High quality, detailed, 16:9 composition."

    print(f"    Calling DALL-E 3 for scene {scene['scene_number']}…")
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt[:4000],
        size="1792x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    last_exc = None
    for attempt in range(3):
        try:
            img_data = requests.get(image_url, timeout=60)
            img_data.raise_for_status()
            with NamedTemporaryFile(delete=False, dir=str(Path(output_path).parent), suffix=".tmp") as tmp:
                tmp.write(img_data.content)
                temp_path = tmp.name
            Path(temp_path).replace(output_path)
            break
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise last_exc

    # Normalise to 1920x1080
    img = Image.open(output_path).resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.LANCZOS)
    img.save(output_path, "PNG")


def main():
    try:
        script = load_json(SCRIPT_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to load {SCRIPT_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)
    scenes = script["scenes"]
    style = script.get("style", "minimalist")
    if not isinstance(scenes, list) or not scenes:
        print("ERROR: script.json must include a non-empty scenes list.", file=sys.stderr)
        sys.exit(1)

    ensure_dir(ASSETS_DIR)

    mode = "placeholder" if USE_PLACEHOLDERS else "DALL-E 3"
    print(f"Generating {len(scenes)} scene images ({mode})…")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not USE_PLACEHOLDERS and not api_key:
        print("ERROR: OPENAI_API_KEY is required when placeholders are disabled.", file=sys.stderr)
        sys.exit(1)
    client = None if USE_PLACEHOLDERS else OpenAI(api_key=api_key)

    metadata = {}
    failed = []

    for scene in scenes:
        n = scene.get("scene_number")
        if not isinstance(n, int) or n <= 0:
            print(f"ERROR: invalid scene_number in scene: {scene}", file=sys.stderr)
            sys.exit(1)
        out = f"{ASSETS_DIR}/scene_{n:03d}.png"

        if Path(out).exists():
            print(f"  Scene {n:03d}: cached ✓")
            metadata[f"scene_{n:03d}"] = out
            continue

        print(f"  Scene {n:03d}/{len(scenes)}: {scene.get('title', '')}")
        try:
            if USE_PLACEHOLDERS:
                generate_placeholder_image(scene, out)
            else:
                generate_dalle_image(client, scene, out, style)
                time.sleep(1)  # respect rate limits
            metadata[f"scene_{n:03d}"] = out
            print(f"    ✅ saved")
        except Exception as exc:
            print(f"    ❌ failed ({exc}), using placeholder")
            generate_placeholder_image(scene, out)
            metadata[f"scene_{n:03d}"] = out
            failed.append(n)

    save_json(metadata, "output/assets/image_metadata.json")

    print(f"\n✅ Images: {len(metadata) - len(failed)} generated, {len(failed)} fell back to placeholder")
    if failed:
        print(f"   Placeholder fallbacks for scenes: {failed}")


if __name__ == "__main__":
    main()
