# AI LinkedIn Agent

Automates creation and posting of short, scannable, SEO-optimized LinkedIn content from GitHub repos and niche topics. Tracks metrics, avoids duplicates, and emails reports.

## Features

- **Automated scheduling**: Posts on a configurable schedule with optional force mode
- **Smart content strategy**: Chooses between repo posts, calendar topics, niche list, trending (ArXiv), or a safe fallback
- **LLM-powered generation**: Uses OpenRouter (DeepSeek R1) with strict style/length constraints
- **Repo integration**: Pulls README preview and metadata for context-rich repo posts
- **Niche posts**: Calendar-aware topics with template rotation and LLM fallback
- **SEO optimization**: Scores and optimizes content; can regenerate on low scores
- **Deduplication**: Detects similar posts and regenerates with a different strategy
- **LinkedIn automation**: Posts using a headless browser (Playwright)
- **Metrics + dashboard**: Structured metrics, JSON logs, and a dashboard generator
- **Email reports**: Sends summary emails with SEO and engagement context
- **Self-healing & retries**: Error handling, retry queue processing, and health checks
- **CLI controls**: `--dry-run`, `--force`, `--process-retries`, `--check-health`

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
├── post_topic.py              # One-off niche post generator/poster
├── agent/
│   ├── content_strategy.py    # Chooses next content source/topic/template
│   ├── backlog_generator.py   # Repo queue, GitHub fetch, repo post generation
│   ├── topic_picker.py        # Niche topic generator (calendar + templates)
│   ├── llm_generator.py       # OpenRouter prompts, cleaning, SEO pipeline
│   ├── seo_optimizer.py       # SEO scoring/keywording helpers
│   ├── linkedin_poster.py     # Playwright posting to LinkedIn
│   ├── scheduler.py           # Time gates; updates next posting time
│   ├── deduper.py             # Similarity check & uniqueness enforcement
│   ├── engagement_tracker.py  # LinkedIn engagement and stats
│   ├── email_reporter.py      # Email summary sender
│   ├── logging_setup.py       # Structured logging
│   ├── metrics.py             # Metrics tracker
│   ├── github_signals.py      # GitHub activity signals
│   ├── calendar.yaml          # Weekday content plan & templates
│   ├── config.yaml            # Identity, niches, posting settings
│   ├── repo_queue.json        # Pending repos queue
│   ├── used_repos.json        # Already used repos
├── content_backlog/
│   ├── backlog.json           # Generated posts
│   └── used_posts.jsonl       # History of posted content
├── generate_dashboard.py      # Metrics dashboard generator
├── demo_metrics.py            # Demo for metrics
└── .github/workflows/daily.yml# Scheduled CI runs
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
  - `OPENROUTER_MODEL` (default: `x-ai/grok-4-fast:free`)
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
