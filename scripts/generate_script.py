#!/usr/bin/env python3
"""
Stage 1: Generate a full video script using OpenAI GPT-4o.

Reads inputs from environment variables and writes to:
  output/script/script.json          — full structured script
  output/script/script_readable.txt  — human-readable review copy

When config/channel_blueprint.json is present the script is generated
according to the channel's Pop Culture Lore identity, content pillars,
scripting rules, and SEO formulas defined in that file.
"""

import json
import os
import sys

from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from utils import ensure_dir, save_json, slugify, format_time

OUTPUT_DIR = "output/script"
BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "channel_blueprint.json")
WORDS_PER_MINUTE = 140  # average speaking rate for TTS


# ---------------------------------------------------------------------------
# Blueprint loader
# ---------------------------------------------------------------------------

def load_blueprint():
    """Return the channel blueprint dict, or an empty dict if not found."""
    try:
        with open(BLUEPRINT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_format_info(blueprint, video_format):
    """Return the title formula and description for the chosen video format."""
    formats = blueprint.get("video_formats", {})
    fmt = formats.get(video_format, {})
    return fmt.get("title_formula", ""), fmt.get("description", "")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_outline_prompt(topic, audience, duration_minutes, tone, style, video_format, blueprint):
    num_sections = max(5, int(duration_minutes / 5))

    # Blueprint-driven instructions
    bp_scripting = blueprint.get("scripting_rules", {})
    hook_rule = bp_scripting.get("hook", {}).get("rule", "")
    chapter_min = bp_scripting.get("chapter_duration_minutes", {}).get("min", 5)
    chapter_max = bp_scripting.get("chapter_duration_minutes", {}).get("max", 8)
    retention_rule = bp_scripting.get("retention_spike", "")
    title_formula, format_desc = get_format_info(blueprint, video_format)
    seo_formulas = "\n".join(f"  - {f}" for f in blueprint.get("seo_rules", {}).get("title_formulas", []))

    blueprint_context = ""
    if blueprint:
        blueprint_context = f"""
Channel Blueprint Rules (MUST be followed):
- Video format: {video_format} — {format_desc}
- Title formula for this format: {title_formula}
- Other proven title formulas for inspiration:
{seo_formulas}
- Hook rule: {hook_rule}
- Each chapter must be {chapter_min}–{chapter_max} minutes long
- Retention spike rule: {retention_rule}
- Narration style: {bp_scripting.get('narration_style', '')}
"""

    return f"""You are a professional video scriptwriter specialising in Pop Culture Lore and Character Evolution content.

Topic: {topic}
Target Audience: {audience}
Visual Style: {style}
Duration: {duration_minutes} minutes
Tone: {tone}
Number of chapters: approximately {num_sections}
{blueprint_context}
Return ONLY a JSON object with this exact structure (no markdown, no extra text):
{{
  "title": "Compelling, SEO-friendly video title using the formula above",
  "hook": "Opening hook sentence (max 30 seconds / ~70 words) — state the ultimate mystery or epic scale immediately",
  "outline": [
    {{"section": "Hook", "duration_minutes": 1, "key_points": ["Epic scale statement", "Central mystery teased"]}},
    {{"section": "Chapter Title", "duration_minutes": 7, "key_points": ["point1", "point2", "point3"], "retention_spike": "Cliffhanger or dramatic question at the end of this chapter"}},
    {{"section": "Conclusion", "duration_minutes": 2, "key_points": ["Summary", "Call to action"]}}
  ],
  "conclusion": "One-sentence conclusion summary",
  "call_to_action": "Subscribe and like call to action"
}}

Requirements:
- Total section durations must sum to exactly {duration_minutes} minutes
- First section is the Hook (~1 min), last section is Conclusion (~2 min)
- Every chapter (except Hook and Conclusion) must include a "retention_spike" field
- Each section has clear, engaging key points suited for dedicated franchise fans
"""


def build_scenes_prompt(topic, outline_data, tone, style, voice_type, total_words, video_format, blueprint):
    sections_text = json.dumps(outline_data.get("outline", []), indent=2)

    bp_visual = blueprint.get("visual_rules", {})
    scene_min = bp_visual.get("scene_change_frequency_seconds", {}).get("min", 5)
    scene_max = bp_visual.get("scene_change_frequency_seconds", {}).get("max", 7)
    anim_note = bp_visual.get("animation_technique", "")

    bp_audio = blueprint.get("audio_rules", {})
    mood_map = bp_audio.get("mood_mapping", {})
    mood_text = ", ".join(f"{k} → {v} music" for k, v in mood_map.items())

    bp_seo = blueprint.get("seo_rules", {})
    shorts_count_min = bp_seo.get("shorts_extraction", {}).get("count", {}).get("min", 3)
    shorts_count_max = bp_seo.get("shorts_extraction", {}).get("count", {}).get("max", 5)
    shorts_criteria = bp_seo.get("shorts_extraction", {}).get("criteria", "")

    blueprint_context = ""
    if blueprint:
        blueprint_context = f"""
Blueprint Visual & Audio Rules (MUST be followed):
- Animation: {anim_note}
- Change visual framing or background every {scene_min}–{scene_max} seconds
- Music mood mapping per scene: {mood_text}
- Mark {shorts_count_min}–{shorts_count_max} scenes as Shorts candidates: {shorts_criteria}
"""

    return f"""You are a professional video scriptwriter specialising in Pop Culture Lore and Character Evolution content.

Topic: {topic}
Tone: {tone}
Visual Style: {style}
Voice: {voice_type}
Video Format: {video_format}
Total target word count: approximately {total_words} words across all scenes
{blueprint_context}
Outline:
{sections_text}

Return ONLY a JSON object with this structure (no markdown, no extra text):
{{
  "scenes": [
    {{
      "scene_number": 1,
      "section": "Hook",
      "title": "Short scene title",
      "narration": "Full narration text. Opens with epic scale or central mystery. ~70 words for 30-second hook.",
      "visual_description": "Plain English description of what is shown on screen",
      "visual_prompt": "Detailed DALL-E image prompt. Include: {style} style, high quality, 16:9 composition. Be specific about subject, colours, lighting.",
      "on_screen_text": "Any text card or statistic overlaid on the screen (or empty string)",
      "transition_in": "fade",
      "caption": "Brief caption shown below the video — max 80 characters",
      "keywords": ["keyword1", "keyword2"],
      "estimated_duration_seconds": 30,
      "music_mood": "epic",
      "is_shorts_candidate": false,
      "retention_spike": ""
    }}
  ]
}}

Important rules:
- Scene 1 is always the 30-second hook; last scene is conclusion + CTA
- Narration word count must match estimated_duration_seconds (at 140 words/min)
- All visual_prompt values must maintain a consistent {style} aesthetic
- transition_in is one of: fade, slide, zoom, cut
- music_mood is one of: triumphant, eerie, tense, epic, neutral
- is_shorts_candidate: set to true for {shorts_count_min}–{shorts_count_max} scenes with the most dramatic/shocking content
- retention_spike: fill in for the last scene of each chapter (empty string otherwise)
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


def extract_shorts(scenes):
    """Return scenes flagged as Shorts candidates."""
    return [
        {
            "scene_number": s.get("scene_number"),
            "title": s.get("title", ""),
            "narration_preview": s.get("narration", "")[:200],
            "estimated_duration_seconds": s.get("estimated_duration_seconds", 60),
        }
        for s in scenes
        if s.get("is_shorts_candidate")
    ]


def write_readable_script(script, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"VIDEO SCRIPT: {script['upload_title']}\n")
        f.write("=" * 60 + "\n")
        f.write(f"Topic    : {script['topic']}\n")
        f.write(f"Audience : {script['audience']}\n")
        f.write(f"Format   : {script.get('video_format', 'N/A')}\n")
        f.write(f"Duration : ~{script['duration_minutes']} min  "
                f"(estimated {script['total_estimated_duration_formatted']})\n")
        f.write(f"Tone     : {script['tone']}  |  Style: {script['style']}  |  Voice: {script['voice_type']}\n\n")
        f.write(f"HOOK:\n{script.get('hook', '')}\n\n")
        f.write("=" * 60 + "\nSCENES:\n\n")
        for scene in script["scenes"]:
            shorts_flag = " [SHORTS CANDIDATE]" if scene.get("is_shorts_candidate") else ""
            f.write(f"Scene {scene['scene_number']:02d}: {scene.get('title', '')}{shorts_flag}\n")
            f.write(f"Section : {scene.get('section', '')}  |  "
                    f"Duration: {scene.get('estimated_duration_seconds', 90)}s  |  "
                    f"Music: {scene.get('music_mood', '')}\n")
            f.write(f"Narration:\n{scene.get('narration', '')}\n")
            f.write(f"Visual  : {scene.get('visual_description', '')}\n")
            f.write(f"Caption : {scene.get('caption', '')}\n")
            if scene.get("retention_spike"):
                f.write(f"↪ RETENTION SPIKE: {scene['retention_spike']}\n")
            f.write("-" * 40 + "\n")
        f.write("\nCHAPTERS:\n")
        for ch in script.get("chapters", []):
            f.write(f"  {ch['start_formatted']}  {ch['title']}\n")
        shorts = script.get("shorts_candidates", [])
        if shorts:
            f.write(f"\nSHORTS CANDIDATES ({len(shorts)}):\n")
            for s in shorts:
                f.write(f"  Scene {s['scene_number']:02d}: {s['title']} ({s['estimated_duration_seconds']}s)\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is required.", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    topic = os.environ.get("VIDEO_TOPIC")
    if not topic:
        print("ERROR: VIDEO_TOPIC is required.", file=sys.stderr)
        sys.exit(1)

    blueprint = load_blueprint()
    bp_defaults = blueprint.get("defaults", {})

    audience = os.environ.get("TARGET_AUDIENCE") or blueprint.get("channel", {}).get("target_audience", "general public")
    try:
        duration_minutes = int(os.environ.get("DURATION_MINUTES") or bp_defaults.get("duration_minutes", 45))
    except ValueError:
        print("ERROR: DURATION_MINUTES must be an integer.", file=sys.stderr)
        sys.exit(1)
    tone = os.environ.get("VIDEO_TONE") or bp_defaults.get("tone", "educational")
    style = os.environ.get("VISUAL_STYLE") or bp_defaults.get("style", "minimalist")
    voice_type = os.environ.get("VOICE_TYPE") or bp_defaults.get("voice_type", "nova")
    video_format = os.environ.get("VIDEO_FORMAT", "timeline")
    upload_title = os.environ.get("UPLOAD_TITLE", "")
    upload_description = os.environ.get("UPLOAD_DESCRIPTION", "")

    if not (30 <= duration_minutes <= 60):
        print("ERROR: DURATION_MINUTES must be between 30 and 60.", file=sys.stderr)
        sys.exit(1)

    valid_formats = list(blueprint.get("video_formats", {}).keys()) or ["timeline", "character_evolution", "animated_summary"]
    if video_format not in valid_formats:
        print(f"ERROR: VIDEO_FORMAT must be one of: {valid_formats}", file=sys.stderr)
        sys.exit(1)

    ensure_dir(OUTPUT_DIR)

    print(f"Generating script for: {topic}")
    print(f"Format: {video_format} | Duration: {duration_minutes} min | Tone: {tone} | Style: {style} | Voice: {voice_type}")
    if blueprint:
        print("Channel blueprint loaded ✓")

    # ---- Step 1: outline ----
    print("\n[1/2] Generating outline...")
    outline_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert pop culture lore video creator. Respond with valid JSON only."},
            {"role": "user", "content": build_outline_prompt(topic, audience, duration_minutes, tone, style, video_format, blueprint)},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    try:
        outline_data = json.loads(outline_resp.choices[0].message.content)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid outline JSON response: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(outline_data, dict):
        print("ERROR: outline response is not an object.", file=sys.stderr)
        sys.exit(1)

    # ---- Step 2: scenes ----
    print("[2/2] Generating detailed scenes...")
    total_words = duration_minutes * WORDS_PER_MINUTE
    scenes_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert pop culture lore video scriptwriter. Respond with valid JSON only."},
            {"role": "user", "content": build_scenes_prompt(
                topic, outline_data, tone, style, voice_type, total_words, video_format, blueprint)},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=8000,
    )
    try:
        scenes_raw = json.loads(scenes_resp.choices[0].message.content)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid scenes JSON response: {exc}", file=sys.stderr)
        sys.exit(1)
    scenes = scenes_raw if isinstance(scenes_raw, list) else scenes_raw.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        print("ERROR: scenes response is empty or invalid.", file=sys.stderr)
        sys.exit(1)

    total_seconds = sum(s.get("estimated_duration_seconds", 90) for s in scenes)
    chapters = calculate_chapters(scenes)
    shorts_candidates = extract_shorts(scenes)

    script = {
        "topic": topic,
        "audience": audience,
        "video_format": video_format,
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
        "shorts_candidates": shorts_candidates,
        "scene_count": len(scenes),
        "slug": slugify(topic),
    }

    save_json(script, f"{OUTPUT_DIR}/script.json")
    write_readable_script(script, f"{OUTPUT_DIR}/script_readable.txt")

    print(f"\n✅ Script generated successfully!")
    print(f"   Format   : {video_format}")
    print(f"   Scenes   : {len(scenes)}")
    print(f"   Shorts   : {len(shorts_candidates)} candidates")
    print(f"   Duration : {script['total_estimated_duration_formatted']}")
    print(f"   Output   : {OUTPUT_DIR}/script.json")


if __name__ == "__main__":
    main()

