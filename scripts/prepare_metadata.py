#!/usr/bin/env python3
"""
Stage 4c: Build YouTube upload metadata from the generated script.

Writes output/video/metadata.json with:
  - title (≤100 chars)
  - description (≤5000 chars) including outline, chapter timestamps, and CTA
  - tags (≤500 chars total)
  - chapters list
  - shorts_candidates list
  - category_id, language, made_for_kids flag

When config/channel_blueprint.json is present the metadata is enriched with
channel-specific tags and the correct YouTube category (Gaming = 20).
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from utils import load_json, save_json

SCRIPT_PATH = "output/script/script.json"
METADATA_PATH = "output/video/metadata.json"
BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "channel_blueprint.json")

DISCLAIMER = (
    "\n⚠️ This video was produced with AI-assisted tools. "
    "Content is for educational purposes only — "
    "always verify information from authoritative sources."
)

DEFAULT_TAGS = ["educational", "explainer", "ai-generated", "documentary", "learning"]
YOUTUBE_EDUCATION_CATEGORY = "27"


def load_blueprint():
    try:
        with open(BLUEPRINT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def format_chapters_text(chapters: list) -> str:
    items = []
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        start = ch.get("start_formatted", "0:00")
        title = ch.get("title", "Untitled")
        items.append(f"{start}  {title}")
    return "\n".join(items) if items else "0:00  Intro"


def format_shorts_text(shorts: list) -> str:
    if not shorts:
        return ""
    lines = ["🎬 ALSO WATCH — SHORTS FROM THIS VIDEO:"]
    for s in shorts:
        lines.append(f"  • {s.get('title', 'Scene')} ({s.get('estimated_duration_seconds', 60)}s)")
    return "\n".join(lines)


def build_description(script: dict, blueprint: dict) -> str:
    topic = script.get("topic", "")
    audience = script.get("audience", "")
    video_format = script.get("video_format", "")
    sections = "\n".join(
        f"  • {s.get('section', '')}" for s in script.get("outline", [])
        if isinstance(s, dict) and s.get("section", "").strip()
    )
    if not sections:
        sections = "  • Main topic overview"
    chapters_text = format_chapters_text(script.get("chapters", []))
    cta = script.get("call_to_action", "Subscribe for more!")
    shorts_text = format_shorts_text(script.get("shorts_candidates", []))
    channel_name = blueprint.get("channel", {}).get("name", "")
    channel_line = f"📺 Channel: {channel_name}\n" if channel_name else ""
    format_line = f"📁 Format: {video_format.replace('_', ' ').title()}\n" if video_format else ""

    desc = f"""In this video we explore: {topic}

🎯 Perfect for: {audience}
{channel_line}{format_line}
📋 WHAT YOU'LL LEARN:
{sections}

⏱️ CHAPTERS:
{chapters_text}
{DISCLAIMER}

---
{shorts_text}

{cta}

🔔 Subscribe to never miss a new video!
👍 Like if this was helpful!
💬 Drop a comment with your thoughts!
""".strip()

    return desc


def build_tags(script: dict, blueprint: dict) -> list:
    # Start with blueprint channel tags if available
    bp_tags = blueprint.get("seo_rules", {}).get("default_tags", DEFAULT_TAGS)
    tags = list(bp_tags)

    # Topic words (>3 chars)
    topic_words = [w for w in script.get("topic", "").lower().split() if len(w) > 3]
    tags.extend(topic_words[:6])

    # Video format tag
    video_format = script.get("video_format", "")
    if video_format:
        tags.append(video_format.replace("_", " "))

    # Scene keywords
    for scene in script.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        keywords = scene.get("keywords", [])
        if isinstance(keywords, list):
            tags.extend(k for k in keywords if isinstance(k, str))

    # Deduplicate, preserve order
    seen = set()
    unique_tags = []
    for t in tags:
        t = t.lower().strip()
        if t and t not in seen:
            seen.add(t)
            unique_tags.append(t)

    # YouTube: max 500 chars total across all tags
    result, total = [], 0
    for tag in unique_tags:
        if total + len(tag) + 1 <= 495:
            result.append(tag)
            total += len(tag) + 1

    return result


def main():
    try:
        script = load_json(SCRIPT_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"❌ Error reading {SCRIPT_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)

    blueprint = load_blueprint()
    bp_seo = blueprint.get("seo_rules", {})
    # Use blueprint category if available, fall back to Education
    category_id = bp_seo.get("youtube_category_id", YOUTUBE_EDUCATION_CATEGORY)

    title = (script.get("upload_title") or script.get("topic", "Untitled Video"))[:100]
    description = (script.get("upload_description") or build_description(script, blueprint))[:5000]
    tags = build_tags(script, blueprint)

    metadata = {
        "title": title,
        "description": description,
        "tags": tags,
        "chapters": script.get("chapters", []),
        "shorts_candidates": script.get("shorts_candidates", []),
        "category_id": category_id,
        "default_language": "en",
        "made_for_kids": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": script.get("topic", ""),
        "video_format": script.get("video_format", ""),
        "slug": script.get("slug", ""),
    }

    save_json(metadata, METADATA_PATH)

    print("✅ YouTube metadata prepared:")
    print(f"   Title       : {metadata['title']}")
    print(f"   Description : {len(metadata['description'])} chars")
    print(f"   Tags        : {len(metadata['tags'])}")
    print(f"   Chapters    : {len(metadata['chapters'])}")
    print(f"   Shorts      : {len(metadata['shorts_candidates'])} candidates")
    print(f"   Category ID : {category_id}")
    print(f"   Output      : {METADATA_PATH}")


if __name__ == "__main__":
    main()
