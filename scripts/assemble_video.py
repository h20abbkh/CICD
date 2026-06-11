#!/usr/bin/env python3
"""
Stage 4: Assemble the final video from images, audio, captions, intro, and outro.

Pipeline per scene:
  1. Apply Ken Burns slow-zoom to the scene image (ffmpeg zoompan filter)
  2. Overlay caption text and optional on-screen title card
  3. Mux the TTS audio track
  → scene_NNN.mp4

Final assembly:
  - intro title card
  - all scene clips (concatenated with concat demuxer)
  - outro call-to-action card
  - optional background music mixed at low volume
  → output/video/final_video.mp4

Also generates output/video/thumbnail.jpg from the first scene image.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, load_json

SCRIPT_PATH = "output/script/script.json"
AUDIO_DIR = "output/audio"
ASSETS_DIR = "output/assets/images"
VIDEO_DIR = "output/video"
SCENES_DIR = f"{VIDEO_DIR}/scenes"

W, H = 1920, 1080
FPS = 30
INTRO_DURATION = 5   # seconds
OUTRO_DURATION = 8   # seconds


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def ffmpeg(*args, description=""):
    cmd = ["ffmpeg", "-y"] + list(args)
    if description:
        print(f"    {description}…")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        print("ffmpeg stderr:\n" + result.stderr[-3000:])
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {' '.join(cmd[:8])}")
    return result


def ffprobe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------

def _font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _font_regular(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Build title-card image + silent video clip
# ---------------------------------------------------------------------------

def create_title_card_clip(title: str, subtitle: str, duration: int, output_mp4: str):
    img_path = output_mp4.replace(".mp4", ".png")
    img = Image.new("RGB", (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    draw.text((W // 2, H // 2 - 70), title[:70], fill="white",
              font=_font(72), anchor="mm")
    if subtitle:
        draw.text((W // 2, H // 2 + 70), subtitle[:90], fill=(170, 170, 190),
                  font=_font_regular(40), anchor="mm")
    img.save(img_path, "PNG")

    ffmpeg(
        "-loop", "1", "-framerate", str(FPS), "-i", img_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H}",
        "-an",
        output_mp4,
        description=f"Title card ({title[:30]}…)",
    )


# ---------------------------------------------------------------------------
# Build one scene clip: image → Ken Burns video + TTS audio + captions
# ---------------------------------------------------------------------------

def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext."""
    return (
        text.replace("\\", "\\\\")
            .replace("'", "\u2019")   # replace straight quote with curly to avoid shell issues
            .replace(":", "\\:")
            .replace("%", "\\%")
    )


def create_scene_clip(image_path: str, audio_path: str, caption: str,
                      on_screen_text: str, output_mp4: str) -> float:
    duration = ffprobe_duration(audio_path)
    if duration <= 0:
        raise RuntimeError(f"Invalid audio duration for {audio_path}")

    # Ken Burns: slow zoom-in (1.0 → 1.05) centred on the image
    frames = max(1, int(duration * FPS))
    zoom_end = 1.05
    zoom_step = (zoom_end - 1.0) / frames

    vf_parts = [
        f"scale={int(W * 1.12)}:{int(H * 1.12)},",
        f"zoompan=z='min(zoom+{zoom_step:.6f},1.05)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={W}x{H}:fps={FPS}",
    ]

    # Caption bar at the bottom
    if caption:
        safe_cap = _escape_drawtext(caption[:90])
        vf_parts.append(
            f",drawtext=text='{safe_cap}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            f":fontsize=34:fontcolor=white:borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y=h-90"
        )

    # On-screen title card near the top
    if on_screen_text:
        safe_title = _escape_drawtext(on_screen_text[:80])
        vf_parts.append(
            f",drawtext=text='{safe_title}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=110"
        )

    vf = "".join(vf_parts)

    ffmpeg(
        "-loop", "1", "-framerate", str(FPS), "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration + 0.3),
        "-shortest",
        output_mp4,
        description="Scene clip",
    )
    return duration


# ---------------------------------------------------------------------------
# Concatenate clips with ffmpeg concat demuxer
# ---------------------------------------------------------------------------

def concatenate_clips(clips: list, output_mp4: str):
    list_file = output_mp4.replace(".mp4", "_list.txt")
    allowed_prefix = os.path.abspath(SCENES_DIR)
    with open(list_file, "w") as f:
        for c in clips:
            abs_path = os.path.abspath(c)
            if not abs_path.startswith(allowed_prefix + os.sep):
                raise RuntimeError(f"Unsafe clip path outside scenes dir: {c}")
            f.write(f"file '{abs_path}'\n")

    ffmpeg(
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy",
        output_mp4,
        description="Concatenating all clips",
    )
    os.remove(list_file)


# ---------------------------------------------------------------------------
# Optional background music
# ---------------------------------------------------------------------------

def mix_background_music(video_path: str, music_path: str, output_path: str):
    ffmpeg(
        "-i", video_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex",
        "[1:a]volume=0.07,aformat=fltp[bg];"
        "[0:a][bg]amix=inputs=2:duration=first:weights=1 0.07[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
        description="Mixing background music",
    )


# ---------------------------------------------------------------------------
# Thumbnail (1280×720 from first scene image + title overlay)
# ---------------------------------------------------------------------------

def generate_thumbnail(script: dict, out_path: str):
    first_img = f"{ASSETS_DIR}/scene_001.png"
    if Path(first_img).exists():
        img = Image.open(first_img).resize((1280, 720), Image.LANCZOS)
    else:
        img = Image.new("RGB", (1280, 720), (20, 20, 30))

    # Dark overlay so text is readable
    overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 120))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    title = script.get("upload_title", script.get("topic", "Video"))[:55]
    # Shadow
    draw.text((643, 363), title, fill=(30, 30, 30), font=_font(68), anchor="mm")
    draw.text((640, 360), title, fill="white", font=_font(68), anchor="mm")

    img.save(out_path, "JPEG", quality=95)
    print(f"    ✅ Thumbnail saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    script = load_json(SCRIPT_PATH)
    scenes = script["scenes"]

    ensure_dir(VIDEO_DIR)
    ensure_dir(SCENES_DIR)

    print(f"Assembling video from {len(scenes)} scenes…\n")
    all_clips = []

    # Intro
    intro_mp4 = f"{SCENES_DIR}/intro.mp4"
    print("[Intro]")
    create_title_card_clip(
        title=script.get("upload_title", script.get("topic", "Video")),
        subtitle=f"A {script.get('tone', 'educational')} video",
        duration=INTRO_DURATION,
        output_mp4=intro_mp4,
    )
    all_clips.append(intro_mp4)

    # Scene clips
    for i, scene in enumerate(scenes, 1):
        n = scene["scene_number"]
        img = f"{ASSETS_DIR}/scene_{n:03d}.png"
        aud = f"{AUDIO_DIR}/scene_{n:03d}.mp3"
        out = f"{SCENES_DIR}/scene_{n:03d}.mp4"

        print(f"[Scene {i}/{len(scenes)}] {scene.get('title', '')}")

        for req, label in [(img, "image"), (aud, "audio")]:
            if not Path(req).exists():
                print(f"  ❌ Missing {label}: {req}")
                sys.exit(1)

        if Path(out).exists():
            print("  Already assembled ✓")
        else:
            dur = create_scene_clip(
                image_path=img,
                audio_path=aud,
                caption=scene.get("caption", ""),
                on_screen_text=scene.get("on_screen_text", ""),
                output_mp4=out,
            )
            print(f"  ✅ {dur:.1f}s")

        all_clips.append(out)

    # Outro
    outro_mp4 = f"{SCENES_DIR}/outro.mp4"
    print("\n[Outro]")
    create_title_card_clip(
        title=script.get("call_to_action", "Thanks for watching!"),
        subtitle="Like & Subscribe for more",
        duration=OUTRO_DURATION,
        output_mp4=outro_mp4,
    )
    all_clips.append(outro_mp4)

    # Concat
    print("\n[Final] Concatenating…")
    raw_mp4 = f"{VIDEO_DIR}/final_video_raw.mp4"
    concatenate_clips(all_clips, raw_mp4)

    # Background music (optional)
    music_path = "config/background_music.mp3"
    final_mp4 = f"{VIDEO_DIR}/final_video.mp4"
    if Path(music_path).exists():
        print("\n[Music] Adding background music…")
        mix_background_music(raw_mp4, music_path, final_mp4)
        os.remove(raw_mp4)
    else:
        os.rename(raw_mp4, final_mp4)

    # Thumbnail
    print("\n[Thumbnail]")
    generate_thumbnail(script, f"{VIDEO_DIR}/thumbnail.jpg")

    # Summary
    dur = ffprobe_duration(final_mp4)
    size_mb = Path(final_mp4).stat().st_size / (1024 * 1024)
    print(f"\n✅ Video assembled!")
    print(f"   Duration : {int(dur//60)}:{int(dur%60):02d}")
    print(f"   Size     : {size_mb:.1f} MB")
    print(f"   Output   : {final_mp4}")


if __name__ == "__main__":
    main()
