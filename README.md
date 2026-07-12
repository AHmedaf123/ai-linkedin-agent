# AI LinkedIn Agent

Automates creation and posting of short, scannable, SEO-optimized LinkedIn content from GitHub repos and niche topics. Tracks metrics, avoids duplicates, and emails reports.

## Features

- **Persistent memory (single source of truth)**: One SQLite store (`agent/agent_storage.db`) holds every published post — hash, topic, hook, hashtags, template_id, posted_at — plus its later engagement (likes/comments/impressions). Dedup, cooldowns, and learning all read from this one place, and CI commits it back so state survives runs.
- **Real deduplication**: Full-body TF-IDF similarity against the last 30 published posts **and** a hook (first-sentence) similarity check against the last 10 — so repeated openings get rejected, not just repeated bodies.
- **Feedback loop (learning)**: Before each post, a performance digest of your best/worst past posts is injected into the generation prompt; drafts that open like historically low-performing posts are regenerated.
- **Bandit topic selection**: Epsilon-greedy over niches — mostly exploit the best-performing topic by measured engagement, sometimes explore — falling back to round-robin while there's no data yet.
- **Engagement collection**: A separate scheduled job scrapes likes/comments/**impressions** at ~T+24h/T+48h (Playwright, same browser stack as posting) and joins them back to the stored post.
- **Smart content strategy**: Repo posts → trending (ArXiv) → bandit niche → safe fallback.
- **LLM-powered generation**: OpenRouter with strict style/length constraints and specificity checks.
- **Slot-based scheduling**: Rotates through `candidate_times` so different posting times can be A/B-tested; posts at most once per day.
- **Growth engine (opt-in)**: First-comment on your own post, LLM-generated niche comments, and connection requests — all rate-limited with human-like pacing.
- **LinkedIn automation**: Playwright only (Selenium removed).
- **Metrics, email reports, self-healing, health checks**.
- **CLI controls**: `--dry-run`, `--force`, `--process-retries`, `--check-health`, `--collect-metrics`, `--growth`

## How it works

1. **Schedule gate**
   - Runs if inside posting window (`scheduler.should_post_now()`), or immediately with `--force`.
2. **Context fetch**
   - GitHub activity (if `GITHUB_USERNAME`/token present) and LinkedIn engagement (if creds present).
3. **Content strategy selection**
   - Priority: repo queue → calendar (weekday) → niches from config → trending topics (ArXiv) → generic fallback.
4. **Content generation**
   - LLM generates the post using strict constraints (length, tone, structure, hashtags).
   - Cleans labels, extracts up to 5 hashtags, and runs SEO optimizer.
5. **Deduplication & regeneration**
   - Checks backlog for similarity; if duplicate or low SEO score, regenerates with a different strategy/template.
6. **Publish & persist**
   - Saves to backlog, posts to LinkedIn (unless dry-run or `ENABLE_POST=false`), emails a report, and updates next schedule.
7. **Metrics**
   - Timers, counters, and events saved to `linkedin_agent_metrics.json`; structured logs in `linkedin_agent.log`.

## Project structure (key files)

```
ai-linkedin-agent/
├── run.py                     # Main orchestrator & CLI entry point
├── agent/
│   ├── storage.py             # SQLite single source of truth (posts, engagement, state, counters)
│   ├── content_strategy.py    # Content source + epsilon-greedy bandit niche picker
│   ├── performance_digest.py  # Turns engagement history into prompt context + low-performer gate
│   ├── backlog_generator.py   # Repo queue, GitHub fetch, repo post generation
│   ├── topic_picker.py        # Niche topic generator (calendar + templates)
│   ├── llm_generator.py       # OpenRouter prompts, cleaning, SEO pipeline
│   ├── seo_optimizer.py       # SEO scoring/keywording helpers
│   ├── linkedin_poster.py     # Playwright posting to LinkedIn
│   ├── engagement_tracker.py  # Playwright engagement/impressions scraper (T+24h/T+48h)
│   ├── growth_agent.py        # First-comment, niche comments, connections (opt-in, rate-limited)
│   ├── when_gate.py           # Slot-based posting gate (replaces old scheduler.py)
│   ├── deduper.py             # Body + hook similarity against persistent history
│   ├── email_reporter.py      # Email summary sender
│   ├── logging_setup.py       # Structured logging
│   ├── metrics.py             # Metrics tracker
│   ├── github_signals.py      # GitHub activity signals
│   ├── calendar.yaml          # Weekday content plan & templates
│   ├── config.yaml            # Identity, niches, posting settings (start_time, candidate_times)
│   ├── config.json            # user.linkedin_profile_url, SMTP defaults
│   ├── agent_storage.db       # Persistent store (committed by CI)
│   ├── repo_queue.json        # Pending repos queue
│   └── used_repos.json        # Already used repos
├── scripts/
│   ├── post_topic.py          # One-off niche post generator/poster
│   └── generate_dashboard.py  # Metrics dashboard generator
└── .github/workflows/
    ├── daily.yml              # Scheduled posting (candidate-time slots)
    ├── metrics.yml            # T+24h/T+48h engagement collection
    └── growth.yml             # Opt-in growth session
```

## Data & learning flow

```
publish  ──> storage.save_used_post()  (hash, topic, hook, template_id, posted_at)
metrics  ──> engagement_tracker  ──> storage.update_post_engagement()  (likes/comments/impressions)
generate <── performance_digest  <── storage  (best/worst hooks, topic/template performance)
         └── content_strategy bandit picks the best-performing niche
```

## Requirements

- Python 3.8+ (recommended: Python 3.11)
- `pip install -r requirements.txt`
- Playwright browser dependencies: `python -m playwright install chromium`

## Quick Setup

```bash
# 1. Clone and setup
git clone https://github.com/your-username/ai-linkedin-agent.git
cd ai-linkedin-agent

# 2. Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 3. Initialize project structure
python setup.py

# 4. Configure environment
cp .env.template .env
# Edit .env with your API keys and credentials

# 5. Validate setup
python health_check.py

# 6. Test run
python run.py --dry-run --force
```

## Configuration

Edit these files and provide environment variables before running:

- **agent/config.yaml**
  - `user.name/persona/voice`: Author identity and tone
  - `niches`: List of niche topics
  - `posting`: start time, increment, timezone
- **agent/repo_queue.json**
  - `{"pending_repos": ["RepoName1", "RepoName2"]}`
- **agent/calendar.yaml**
  - Weekday schedules and optional post templates

### Environment variables

- **OpenRouter**
  - `OPENROUTER_API_KEY` (required for LLM)
  - `OPENROUTER_MODEL` (default: `alibaba/tongyi-deepresearch-30b-a3b:free`)
- **GitHub**
  - `GITHUB_USERNAME` (default in code: `AHmedaf123`)
  - `GH_API_TOKEN` or `GITHUB_TOKEN`
- **LinkedIn** (choose one pair)
  - `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` OR `LINKEDIN_USER` + `LINKEDIN_PASS`
- **Email** (choose one pair) + receiver
  - `EMAIL_USER` + `EMAIL_PASS` OR `EMAIL_SENDER` + `EMAIL_PASSWORD`
  - `EMAIL_RECEIVER` or `EMAIL_TO`
- **Optional**
  - `ENABLE_POST=true|false` (default true)
  - `LOG_LEVEL_CONSOLE`, `LOG_LEVEL_FILE`, `LOG_FORMAT_JSON`
  - `MIN_SEO_SCORE` (default 70), `MAX_LOW_SEO_ATTEMPTS` (default 2), `MAX_REGENERATION_ATTEMPTS` (default 3)

## Usage

### Install

```bash
# Clone the repository
git clone https://github.com/your-username/ai-linkedin-agent.git
cd ai-linkedin-agent

# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Initialize project
python setup.py

# Set up environment variables
cp .env.template .env
# Edit .env with your actual API keys and credentials

# Validate setup
python health_check.py
```

### Quick start (preview only)

```bash
python run.py --dry-run --force
```

- Generates content immediately, saves artifacts, does not post to LinkedIn.

### Run now (respecting schedule unless forced)

```bash
# Respect schedule
python run.py

# Ignore schedule and run now
python run.py --force
```

### CLI utilities

- Process retry queue: `python run.py --process-retries`
- Health check: `python run.py --check-health`

## Running for niche posts

You have two options:

1) One-off niche post with explicit topic (recommended for manual runs)

```bash
# Preview only
python scripts/post_topic.py --topic "AI for Protein Design" --dry-run

# Post live (requires LinkedIn creds and ENABLE_POST=true)
python scripts/post_topic.py --topic "AI for Protein Design"
```

- Saves `post_preview.txt` and `latest_post.json`. Honors `ENABLE_POST`.

2) Through the main workflow

- Ensure `agent/repo_queue.json` has no pending repos (otherwise repo takes priority).
- Ensure `agent/config.yaml` has your `niches` and/or configure `agent/calendar.yaml`.
- Run:

```bash
python run.py --force
```

The strategy will pick a calendar topic (weekday) or a niche from config and generate/post accordingly.

## Running for repo posts

- Add repos to `agent/repo_queue.json` under `pending_repos`.
- Ensure GitHub token is available for README/metadata fetch.
- Run:

```bash
# Preview only
python run.py --dry-run --force

# Live run
python run.py --force
```

The strategy prioritizes repos when the queue is non-empty, generating a repo-focused post using README context.

## GitHub Actions (scheduled runs)

Push to your repository and configure secrets. The workflow in `.github/workflows/daily.yml` runs the agent on a schedule and respects the same environment variables.

## Metrics and dashboard

- Metrics saved to `linkedin_agent_metrics.json` and logs to `linkedin_agent.log`.
- Generate a dashboard:

```bash
python scripts/generate_dashboard.py --metrics-file linkedin_agent_metrics.json --output-dir reports
```

## Troubleshooting

- Set `--dry-run` for safe testing; set `ENABLE_POST=false` to disable posting globally.
- Ensure all required environment variables are set, especially `OPENROUTER_API_KEY`.
- Playwright may prompt to install browsers on first use when posting to LinkedIn.

## License

MIT
