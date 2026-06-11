#!/usr/bin/env python3
"""
Stage 1: Generate a full video script using OpenAI GPT-4o.

Reads inputs from environment variables and writes to:
  output/script/script.json          — full structured script
  output/script/script_readable.txt  — human-readable review copy
"""

import json
import os
import sys

from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, save_json, slugify, format_time

OUTPUT_DIR = "output/script"
WORDS_PER_MINUTE = 140  # average speaking rate for TTS


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_outline_prompt(topic, audience, duration_minutes, tone, style):
    num_sections = max(5, int(duration_minutes / 5))
    return f"""You are a professional video scriptwriter. Create a structured outline for a {duration_minutes}-minute {tone} video.

Topic: {topic}
Target Audience: {audience}
Visual Style: {style}
Number of sections: approximately {num_sections}

Return ONLY a JSON object with this exact structure (no markdown, no extra text):
{{
  "title": "Compelling, SEO-friendly video title",
  "hook": "Opening hook sentence that grabs attention in the first 15 seconds",
  "outline": [
    {{"section": "Introduction", "duration_minutes": 2, "key_points": ["point1", "point2"]}},
    {{"section": "Section Title", "duration_minutes": 8, "key_points": ["point1", "point2", "point3"]}}
  ],
  "conclusion": "One-sentence conclusion summary",
  "call_to_action": "Subscribe and like call to action"
}}

Requirements:
- Total section durations must sum to exactly {duration_minutes} minutes
- First section is Introduction (~2 min), last section is Conclusion (~2 min)
- Each section has clear, engaging key points suited for {audience}
"""


def build_scenes_prompt(topic, outline_data, tone, style, voice_type, total_words):
    sections_text = json.dumps(outline_data.get("outline", []), indent=2)
    return f"""You are a professional video scriptwriter. Expand this outline into a detailed scene-by-scene script.

Topic: {topic}
Tone: {tone}
Visual Style: {style}
Voice: {voice_type}
Total target word count: approximately {total_words} words across all scenes

Outline:
{sections_text}

Return ONLY a JSON object with this structure (no markdown, no extra text):
{{
  "scenes": [
    {{
      "scene_number": 1,
      "section": "Introduction",
      "title": "Short scene title",
      "narration": "Full narration text. 100-200 words for a ~1 minute scene. Conversational, engaging, suitable for {voice_type} voice.",
      "visual_description": "Plain English description of what is shown on screen",
      "visual_prompt": "Detailed DALL-E image prompt. Include: {style} style, high quality, 16:9 composition. Be specific about subject, colors, lighting.",
      "on_screen_text": "Any text card or statistic overlaid on the screen (or empty string)",
      "transition_in": "fade",
      "caption": "Brief caption shown below the video — max 80 characters",
      "keywords": ["keyword1", "keyword2"],
      "estimated_duration_seconds": 90
    }}
  ]
}}

Important rules:
- Scene 1 is the hook/intro; last scene is conclusion + CTA
- Narration word count must match estimated_duration_seconds (at 140 words/min)
- All visual_prompt values must maintain a consistent {style} aesthetic
- transition_in is one of: fade, slide, zoom, cut
- Make narration warm and direct — the viewer is {tone}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculate_chapters(scenes):
    chapters = []
    current_time = 0
    current_section = None
    for scene in scenes:
        section = scene.get("section", "")
        if section != current_section:
            chapters.append({
                "title": section,
                "start_seconds": current_time,
                "start_formatted": format_time(current_time),
            })
            current_section = section
        current_time += scene.get("estimated_duration_seconds", 90)
    return chapters


def write_readable_script(script, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"VIDEO SCRIPT: {script['upload_title']}\n")
        f.write("=" * 60 + "\n")
        f.write(f"Topic    : {script['topic']}\n")
        f.write(f"Audience : {script['audience']}\n")
        f.write(f"Duration : ~{script['duration_minutes']} min  "
                f"(estimated {script['total_estimated_duration_formatted']})\n")
        f.write(f"Tone     : {script['tone']}  |  Style: {script['style']}  |  Voice: {script['voice_type']}\n\n")
        f.write(f"HOOK:\n{script.get('hook', '')}\n\n")
        f.write("=" * 60 + "\nSCENES:\n\n")
        for scene in script["scenes"]:
            f.write(f"Scene {scene['scene_number']:02d}: {scene.get('title', '')}\n")
            f.write(f"Section : {scene.get('section', '')}  |  "
                    f"Duration: {scene.get('estimated_duration_seconds', 90)}s\n")
            f.write(f"Narration:\n{scene.get('narration', '')}\n")
            f.write(f"Visual  : {scene.get('visual_description', '')}\n")
            f.write(f"Caption : {scene.get('caption', '')}\n")
            f.write("-" * 40 + "\n")
        f.write("\nCHAPTERS:\n")
        for ch in script.get("chapters", []):
            f.write(f"  {ch['start_formatted']}  {ch['title']}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    topic = os.environ["VIDEO_TOPIC"]
    audience = os.environ.get("TARGET_AUDIENCE", "general public")
    duration_minutes = int(os.environ.get("DURATION_MINUTES", "45"))
    tone = os.environ.get("VIDEO_TONE", "educational")
    style = os.environ.get("VISUAL_STYLE", "minimalist")
    voice_type = os.environ.get("VOICE_TYPE", "nova")
    upload_title = os.environ.get("UPLOAD_TITLE", "")
    upload_description = os.environ.get("UPLOAD_DESCRIPTION", "")

    if not (30 <= duration_minutes <= 60):
        print(f"WARNING: duration_minutes={duration_minutes} is outside 30-60 min range.")

    ensure_dir(OUTPUT_DIR)

    print(f"Generating script for: {topic}")
    print(f"Duration: {duration_minutes} min | Tone: {tone} | Style: {style} | Voice: {voice_type}")

    # ---- Step 1: outline ----
    print("\n[1/2] Generating outline...")
    outline_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert video content creator. Respond with valid JSON only."},
            {"role": "user", "content": build_outline_prompt(topic, audience, duration_minutes, tone, style)},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    outline_data = json.loads(outline_resp.choices[0].message.content)

    # ---- Step 2: scenes ----
    print("[2/2] Generating detailed scenes...")
    total_words = duration_minutes * WORDS_PER_MINUTE
    scenes_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert video scriptwriter. Respond with valid JSON only."},
            {"role": "user", "content": build_scenes_prompt(
                topic, outline_data, tone, style, voice_type, total_words)},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=8000,
    )
    scenes_raw = json.loads(scenes_resp.choices[0].message.content)
    scenes = scenes_raw if isinstance(scenes_raw, list) else scenes_raw.get("scenes", [])

    total_seconds = sum(s.get("estimated_duration_seconds", 90) for s in scenes)
    chapters = calculate_chapters(scenes)

    script = {
        "topic": topic,
        "audience": audience,
        "duration_minutes": duration_minutes,
        "tone": tone,
        "style": style,
        "voice_type": voice_type,
        "upload_title": upload_title or outline_data.get("title", topic),
        "upload_description": upload_description,
        "hook": outline_data.get("hook", ""),
        "call_to_action": outline_data.get("call_to_action", ""),
        "outline": outline_data.get("outline", []),
        "scenes": scenes,
        "total_estimated_duration_seconds": total_seconds,
        "total_estimated_duration_formatted": format_time(total_seconds),
        "chapters": chapters,
        "scene_count": len(scenes),
        "slug": slugify(topic),
    }

    save_json(script, f"{OUTPUT_DIR}/script.json")
    write_readable_script(script, f"{OUTPUT_DIR}/script_readable.txt")

    print(f"\n✅ Script generated successfully!")
    print(f"   Scenes   : {len(scenes)}")
    print(f"   Duration : {script['total_estimated_duration_formatted']}")
    print(f"   Output   : {OUTPUT_DIR}/script.json")


if __name__ == "__main__":
    main()
