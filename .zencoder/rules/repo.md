# AI LinkedIn Agent — Repository Overview

## Purpose
Automates creation and posting of short, scannable, SEO-optimized LinkedIn content from GitHub repos and niche topics. Tracks metrics, avoids duplicates, and emails reports.

## Key Components
- **agent/llm_generator.py**: Calls OpenRouter (DeepSeek R1) to generate posts.
- **agent/backlog_generator.py**: Fetches GitHub repo info (incl. README preview) and builds repo posts.
- **agent/topic_picker.py**: Picks niche posts from config and other strategies.
- **agent/post_builder.py / seo_optimizer.py**: Post assembly and SEO scoring.
- **agent/scheduler.py / when_gate.py**: Decides when to post.
- **agent/linkedin_poster.py**: Handles posting to LinkedIn (via Playwright).
- **agent/deduper.py**: Prevents duplicate/similar posts.
- **agent/metrics.py / dashboard.py**: Metrics tracking and visualization.
- **run.py**: Main orchestrator. Saves backlog, posts (optional), emails report.

## Prompts & Content Rules (Important)
Implemented in `agent/llm_generator.py`.
- Shared constraints in `PROMPT_CONSTRAINTS` enforce:
  - Length: 120–200 words and under 1,300 characters
  - Short paragraphs: 1–2 lines with line breaks
  - Tone: conversational, authoritative, value-driven
  - Structure with labels: 1) Hook → 2) Context/Story → 3) Insights/Value → 4) CTA
  - Hashtags: 3–5 total (broad + niche), placed at the end
  - Mentions: 1–2 if relevant
  - Natural keyword usage
  - Visual suggestion line at the end (e.g., "Suggested visual: …")
  - Avoid heavy Markdown headings; use plain text + line breaks
- Repo prompt includes: problem solved, core features/approach, direct repo link.
- Niche prompt focuses on trends, use cases, research, and ends with a question.
- Post-processing currently limits extracted hashtags to **5**.

## Configuration
- File: `agent/config.yaml`
  - **user.name/persona/voice**: Author identity
  - **niches**: List of niche topics
  - **posting**: start time, increment, timezone (e.g., Asia/Karachi)
- Repos queue: `agent/repo_queue.json` (pending repos); `agent/used_repos.json` (history)
- Content calendar: `agent/calendar.yaml`

## Environment Variables (set via .env or CI secrets)
- OpenRouter:
  - `OPENROUTER_API_KEY` (required)
  - `OPENROUTER_MODEL` (default: alibaba/tongyi-deepresearch-30b-a3b:free)
- GitHub:
  - `GITHUB_USERNAME` (default used in code: AHmedaf123)
  - `GH_API_TOKEN` or `GITHUB_TOKEN`
- LinkedIn (pick one pair):
  - `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` OR `LINKEDIN_USER` + `LINKEDIN_PASS`
- Email (pick one pair) + receiver:
  - `EMAIL_USER` + `EMAIL_PASS` OR `EMAIL_SENDER` + `EMAIL_PASSWORD`
  - `EMAIL_RECEIVER` or `EMAIL_TO`
- Optional logging:
  - `LOG_LEVEL_CONSOLE`, `LOG_LEVEL_FILE`, `LOG_FORMAT_JSON`

## Workflow (run.py)
1. Schedule check via `scheduler.should_post_now()` (or `--force`).
2. Fetch GitHub and LinkedIn engagement context (if creds present).
3. Select content strategy via `content_strategy.get_next_content_strategy()`.
4. Generate post:
   - Repo: `backlog_generator.get_next_repo_post()` → `llm_generator.generate_post(repo=…)`
   - Niche: `topic_picker.get_niche_post()` → `llm_generator.generate_post(niche=…)`
5. Deduplicate via `deduper.check_and_save_post()`; regenerate if needed.
6. Post to LinkedIn (unless `--dry-run` or `ENABLE_POST=false`).
7. Save to backlog `content_backlog/backlog.json` and send email report.
8. Metrics saved to `linkedin_agent_metrics.json`.

## Data & Outputs
- Generated backlog: `content_backlog/backlog.json`
- Logs: `linkedin_agent.log`, optional `structured_logs.json`
- Metrics: `linkedin_agent_metrics.json`
- Artifacts (may be produced by scripts): `generated_posts.json`, `post_preview.txt`

## CI/CD
- GitHub Actions workflow: `.github/workflows/daily.yml` (scheduled runs)

## Development Tips
- Update the post style/constraints in `PROMPT_CONSTRAINTS` inside `agent/llm_generator.py`.
- To hard-enforce character limits, add post-generation trimming in `generate_post()`.
- To adjust hashtags count, modify extraction in `_postprocess_content()`.

## Testing
- `tests/test_metrics.py` covers metrics module. Extend as needed.

## Known Considerations
- Requires valid OpenRouter key. Network calls to GitHub API for repo fetch.
- LinkedIn automation depends on Playwright browser availability and credentials.
- Timezone-sensitive scheduling; ensure `posting.timezone` is correct.