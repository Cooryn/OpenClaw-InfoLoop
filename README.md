# OpenClaw-InfoLoop

InfoLoop is an AI-driven, human-in-the-loop content operation engine for OpenClaw.
It automates information discovery, digest generation, content drafting, and trend
analysis while keeping final publishing decisions under human control.

## Human-in-the-Loop Operating Model

1. Discovery: Monitor configured web sources and collect candidate articles.
2. Selection: Deliver indexed digest to the user for explicit candidate selection.
3. Production: Expand selected items into publication-ready WeChat drafts.
4. Evolution: Analyze daily corpus to recommend next-day monitoring keywords.

## Project Structure

```text
OpenClaw-InfoLoop/
|-- skills/
|   |-- web_radar.py
|   |-- mail_notifier.py
|   |-- content_studio.py
|   `-- trend_analyzer.py
|-- config/
|   `-- manifest.yaml
|-- .env.example
|-- requirements.txt
`-- README.md
```

## Environment Setup

1. Use Python 3.10+.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Create local environment file:

```bash
copy .env.example .env
```

4. Fill in required credentials:
- `QWEN_API_KEY`
- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `SMTP_HOST`
- `SMTP_USER`
- `SMTP_PASS`
- `TARGET_EMAIL`
- Optional proxy: `PROXY_URL` (primary), `HTTP_PROXY` (fallback)

## OpenClaw Integration

- Load `config/manifest.yaml` into your OpenClaw tool registry.
- Ensure runtime has access to `.env`.
- Invoke tools in loop order:
  - `fetch_articles`
  - `summarize_articles`
  - `send_digest_email`
  - `expand_content`
  - `post_to_wechat`
  - `generate_trend_report`

## Current Status

This Step 1 release provides project scaffolding, interface contracts, and
configuration baselines. Full skill implementations are delivered in Steps 2-5.

## Local Smoke Checks

Run module-level scaffold checks:

```bash
python skills/web_radar.py
python skills/mail_notifier.py
python skills/content_studio.py
python skills/trend_analyzer.py
```
