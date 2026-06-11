#!/usr/bin/env python3
"""
Stage 4c: Build YouTube upload metadata from the generated script.

Writes output/video/metadata.json with:
  - title (≤100 chars)
  - description (≤5000 chars) including outline, chapter timestamps, and CTA
  - tags (≤500 chars total)
  - chapters list
  - category_id, language, made_for_kids flag
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from utils import load_json, save_json

SCRIPT_PATH = "output/script/script.json"
METADATA_PATH = "output/video/metadata.json"

DISCLAIMER = (
    "\n⚠️ This video was produced with AI-assisted tools. "
    "Content is for educational purposes only — "
    "always verify information from authoritative sources."
)

DEFAULT_TAGS = ["educational", "explainer", "ai-generated", "documentary", "learning"]
YOUTUBE_EDUCATION_CATEGORY = "27"


def format_chapters_text(chapters: list) -> str:
    return "\n".join(f"{ch['start_formatted']}  {ch['title']}" for ch in chapters)


def build_description(script: dict) -> str:
    topic = script.get("topic", "")
    audience = script.get("audience", "")
    sections = "\n".join(
        f"  • {s.get('section', '')}" for s in script.get("outline", [])
    )
    chapters_text = format_chapters_text(script.get("chapters", []))
    cta = script.get("call_to_action", "Subscribe for more!")

    return f"""In this video we explore: {topic}

🎯 Perfect for: {audience}

📋 WHAT YOU'LL LEARN:
{sections}

⏱️ CHAPTERS:
{chapters_text}
{DISCLAIMER}

---
{cta}

🔔 Subscribe to never miss a new video!
👍 Like if this was helpful!
💬 Drop a comment with your thoughts!
""".strip()


def build_tags(script: dict) -> list:
    tags = list(DEFAULT_TAGS)

    # Topic words (>3 chars)
    topic_words = [w for w in script.get("topic", "").lower().split() if len(w) > 3]
    tags.extend(topic_words[:6])

    # Scene keywords
    for scene in script.get("scenes", []):
        tags.extend(scene.get("keywords", []))

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
    script = load_json(SCRIPT_PATH)

    title = (script.get("upload_title") or script.get("topic", "Untitled Video"))[:100]
    description = (script.get("upload_description") or build_description(script))[:5000]
    tags = build_tags(script)

    metadata = {
        "title": title,
        "description": description,
        "tags": tags,
        "chapters": script.get("chapters", []),
        "category_id": YOUTUBE_EDUCATION_CATEGORY,
        "default_language": "en",
        "made_for_kids": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": script.get("topic", ""),
        "slug": script.get("slug", ""),
    }

    save_json(metadata, METADATA_PATH)

    print("✅ YouTube metadata prepared:")
    print(f"   Title       : {metadata['title']}")
    print(f"   Description : {len(metadata['description'])} chars")
    print(f"   Tags        : {len(metadata['tags'])}")
    print(f"   Chapters    : {len(metadata['chapters'])}")
    print(f"   Output      : {METADATA_PATH}")


if __name__ == "__main__":
    main()
