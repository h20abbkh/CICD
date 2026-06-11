#!/usr/bin/env python3
"""
Stage 5: Upload the rendered video to YouTube via the YouTube Data API v3.

Required environment variables (stored as GitHub Actions secrets):
  YOUTUBE_CLIENT_ID       — OAuth 2.0 client ID
  YOUTUBE_CLIENT_SECRET   — OAuth 2.0 client secret
  YOUTUBE_REFRESH_TOKEN   — long-lived refresh token (see README for setup)

Optional:
  VIDEO_VISIBILITY        — "public" | "unlisted" | "private"  (default: unlisted)

Writes:
  output/upload_summary.json  — video_id, video_url, title, visibility, upload time
"""

import json
import os
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, os.path.dirname(__file__))
from utils import load_json, save_json

VIDEO_PATH = "output/video/final_video.mp4"
THUMBNAIL_PATH = "output/video/thumbnail.jpg"
METADATA_PATH = "output/video/metadata.json"
SUMMARY_PATH = "output/upload_summary.json"

YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_client():
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"❌ Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
        return build(YOUTUBE_API_SERVICE, YOUTUBE_API_VERSION, credentials=creds)
    except Exception as exc:
        print(f"❌ YouTube authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)


def upload_video(youtube, metadata: dict, video_path: str, visibility: str) -> dict:
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags", []),
            "categoryId": metadata.get("category_id", "27"),
            "defaultLanguage": metadata.get("default_language", "en"),
        },
        "status": {
            "privacyStatus": visibility,
            "madeForKids": metadata.get("made_for_kids", False),
        },
    }

    size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    print(f"  Uploading {size_mb:.1f} MB…")

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    last_pct = -1
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct >= last_pct + 10:
                    print(f"  Upload progress: {pct}%")
                    last_pct = pct
        except Exception as exc:
            retries += 1
            if retries > 3:
                raise RuntimeError(f"upload failed after retries: {exc}") from exc
            wait_seconds = 2 ** retries
            print(f"  transient upload error, retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)

    print("  Upload complete ✅")
    return response


def upload_thumbnail(youtube, video_id: str, thumbnail_path: str):
    if not Path(thumbnail_path).exists():
        print("  ⚠️  No thumbnail found, skipping")
        return
    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    print("  Thumbnail uploaded ✅")


def main():
    visibility = os.environ.get("VIDEO_VISIBILITY", "unlisted")
    if visibility not in {"public", "unlisted", "private"}:
        print("❌ VIDEO_VISIBILITY must be one of: public, unlisted, private", file=sys.stderr)
        sys.exit(1)

    for path, label in [(VIDEO_PATH, "Video"), (METADATA_PATH, "Metadata")]:
        if not Path(path).exists():
            print(f"❌ {label} file not found: {path}")
            sys.exit(1)

    metadata = load_json(METADATA_PATH)
    for key in ["title", "description"]:
        if key not in metadata or not metadata[key]:
            print(f"❌ Metadata missing required key: {key}", file=sys.stderr)
            sys.exit(1)
    print(f"Uploading to YouTube ({visibility})…")
    print(f"  Title: {metadata['title']}")

    youtube = get_youtube_client()

    try:
        response = upload_video(youtube, metadata, VIDEO_PATH, visibility)
    except Exception as exc:
        print(f"❌ Upload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"\n  ✅ Video URL: {video_url}")

    print("  Uploading thumbnail…")
    upload_thumbnail(youtube, video_id, THUMBNAIL_PATH)

    summary = {
        "video_id": video_id,
        "video_url": video_url,
        "title": metadata["title"],
        "visibility": visibility,
        "published_at": response["snippet"].get("publishedAt", ""),
        "channel_id": response["snippet"].get("channelId", ""),
    }
    save_json(summary, SUMMARY_PATH)

    # Expose outputs to GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        def _escape_output(value: str) -> str:
            return value.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
        with open(github_output, "a") as f:
            f.write(f"video_url={_escape_output(video_url)}\n")
            f.write(f"video_id={_escape_output(video_id)}\n")

    print(f"\n✅ Published successfully!")
    print(f"   URL        : {video_url}")
    print(f"   Video ID   : {video_id}")
    print(f"   Visibility : {visibility}")


if __name__ == "__main__":
    main()
