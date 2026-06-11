# Automated Video Pipeline → YouTube

End-to-end GitHub Actions pipeline that turns a text topic into a fully produced 30–60 minute animated video and uploads it to YouTube.

```
Topic input
    │
    ▼
[Workflow 1] Generate Script (GPT-4o)
    │  artifact: video-script-{run_id}
    ▼
[Workflow 2] Script Approval  ← human review gate
    │  artifact: approved-script-{run_id}
    ▼
[Workflow 3] Asset + Voice Generation (DALL-E 3 + OpenAI TTS)  ← two parallel jobs
    │  artifacts: visual-assets-{run_id}, voiceover-assets-{run_id}
    ▼
[Workflow 4] Video Assembly + Render (ffmpeg) + QC + Metadata
    │  artifact: rendered-video-{run_id}
    ▼
[Workflow 5] Upload to YouTube  ← human approval gate
    │
    ▼
  YouTube URL
```

---

## Quick Start

### 1. Required GitHub Secrets

Add these in **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o + DALL-E 3 + TTS) |
| `YOUTUBE_CLIENT_ID` | Google OAuth 2.0 client ID |
| `YOUTUBE_CLIENT_SECRET` | Google OAuth 2.0 client secret |
| `YOUTUBE_REFRESH_TOKEN` | Long-lived refresh token (see setup below) |

### 2. Optional Repository Variable

| Variable | Default | Description |
|---|---|---|
| `USE_PLACEHOLDER_IMAGES` | `false` | Set to `true` to skip DALL-E and use cheap coloured placeholders for pipeline testing |

### 3. Set Up GitHub Environments (approval gates)

Create two environments in **Settings → Environments**:

- **`script-approval`** — add required reviewers who must approve the script before assets are generated
- **`youtube-publish`** — add required reviewers who must approve before the video goes live

### 4. Get a YouTube Refresh Token

1. Create an OAuth 2.0 credential in [Google Cloud Console](https://console.cloud.google.com/)
   → APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app
2. Enable the **YouTube Data API v3**
3. Run the one-time authorisation flow locally:

```bash
pip install google-auth-oauthlib
python - <<'EOF'
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)
creds = flow.run_local_server(port=0)
print("REFRESH TOKEN:", creds.refresh_token)
EOF
```

4. Add the printed refresh token as `YOUTUBE_REFRESH_TOKEN` secret.

---

## Running the Pipeline

### Step 1 — Generate Script

Go to **Actions → 1 - Content Planning → Run workflow** and fill in:

| Input | Example |
|---|---|
| `topic` | "The History of the Internet" |
| `audience` | "curious adults" |
| `duration_minutes` | `45` |
| `tone` | `educational` |
| `style` | `minimalist` |
| `voice_type` | `nova` |
| `upload_title` | *(optional — auto-generated if blank)* |

Note the **Run ID** shown in the job summary.

### Step 2 — Review & Approve Script

1. Download the `video-script-{run_id}` artifact
2. Read `script_readable.txt`
3. Trigger **Actions → 2 - Script Approval** with the Run ID and set `approved = true`

### Step 3 — Generate Assets

Trigger **Actions → 3 - Asset and Voice Generation** with the same Run ID.
Two parallel jobs run: DALL-E image generation and TTS voiceover.

> **Cost note:** DALL-E 3 standard is ~$0.04/image. A 45-minute video has ~30 scenes → ~$1.20. Set `USE_PLACEHOLDER_IMAGES=true` to test for free.

### Step 4 — Assemble & Render

Trigger **Actions → 4 - Video Assembly and Render** with the same Run ID.
ffmpeg assembles all scenes with Ken Burns zoom, captions, intro/outro, and optional background music.

> **Optional background music:** add `config/background_music.mp3` to the repo and it will be mixed at 7% volume automatically.

### Step 5 — Upload to YouTube

Trigger **Actions → 5 - Upload and Publish** with the Run ID and desired visibility (`public` / `unlisted` / `private`).
The job requires manual approval via the `youtube-publish` environment.

---

## File Structure

```
.github/workflows/
  1-content-planning.yml       # Script generation
  2-script-approval.yml        # Human review gate
  3-asset-voice-generation.yml # DALL-E + TTS (parallel)
  4-video-assembly-render.yml  # ffmpeg + QC + metadata
  5-upload-publish.yml         # YouTube upload

scripts/
  utils.py                     # Shared helpers
  generate_script.py           # GPT-4o script writer
  generate_assets.py           # DALL-E 3 image generator
  generate_voiceover.py        # OpenAI TTS voiceover
  assemble_video.py            # ffmpeg video assembly
  quality_check.py             # Runtime + asset validation
  prepare_metadata.py          # YouTube title/description/chapters
  upload_youtube.py            # YouTube Data API upload

config/
  style_config.json            # Visual style definitions
  background_music.mp3         # (optional) royalty-free music

requirements.txt
```

---

## Artifacts Produced

Each run ID produces these artifacts (retained for 7–30 days):

| Artifact | Contents |
|---|---|
| `video-script-{id}` | `script.json`, `script_readable.txt` |
| `approved-script-{id}` | Same as above, after approval |
| `visual-assets-{id}` | PNG images per scene |
| `voiceover-assets-{id}` | MP3 audio per scene + timing metadata |
| `rendered-video-{id}` | `final_video.mp4`, `thumbnail.jpg`, `qc_report.json`, `metadata.json` |
| `upload-summary-{id}` | `upload_summary.json` with YouTube URL |
