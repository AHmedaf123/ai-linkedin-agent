import os
import json
import argparse
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Importing agent-specific modules
from agent import storage
from agent.backlog_generator import get_next_repo_post
from agent.topic_picker import get_niche_post
from agent.linkedin_poster import post_to_linkedin
from agent.email_reporter import send_email_report
from agent.when_gate import should_post_now, update_next_post_time
from agent.github_signals import fetch_recent_github_activity
from agent.deduper import check_and_save_post
from agent.logging_setup import setup_logging, get_logger
from agent.metrics import get_metrics_tracker
from agent.content_strategy import get_next_content_strategy, save_topic_history, load_niches_list
from agent.engagement_tracker import fetch_linkedin_engagement, get_engagement_stats
from agent.performance_digest import build_performance_digest, is_similar_to_low_performers
from agent.self_healer import handle_error, process_retry_queue, check_system_health, retry_with_backoff

# --- Global Configuration and Logger Setup ---
# Configure structured JSON logging
logger = setup_logging(
    log_file="linkedin_agent.log",
    console_level=os.getenv("LOG_LEVEL_CONSOLE", "INFO").upper(),
    file_level=os.getenv("LOG_LEVEL_FILE", "DEBUG").upper(),
    json_format=os.getenv("LOG_FORMAT_JSON", "true").lower() == "true"
)

# --- Decorators for common functionality ---
def timed_operation(metric_name: str):
    """Decorator to time a function's execution and record it with metrics."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            self.metrics.start_timer(metric_name)
            try:
                result = func(self, *args, **kwargs)
                duration = self.metrics.stop_timer(metric_name)
                self.logger.debug(f"Operation '{metric_name}' completed in {duration:.4f} seconds.")
                return result
            except Exception as e:
                if metric_name in self.metrics._active_timers:
                    self.metrics.stop_timer(metric_name) # Ensure timer is stopped on error
                raise e
        return wrapper
    return decorator

def handled_operation(error_phase: str, send_report: bool = True, retry: bool = False, critical: bool = False):
    """Decorator to wrap operations with error handling and metric recording."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                self.logger.error(f"Error during {error_phase} phase: {str(e)}",
                                  exc_info=True,
                                  extra={"event": f"{error_phase.lower().replace(' ', '_')}_error"})
                self.metrics.record_event(f"{error_phase.lower().replace(' ', '_')}_error",
                                          {"error_type": type(e).__name__, "message": str(e)})
                self.metrics.increment_counter("errors")
                
                context = kwargs.get("context", {})
                retry_item = kwargs.get("retry_item", None)

                handle_error(e, error_phase,
                             context=context,
                             send_report=send_report,
                             retry=retry,
                             retry_item=retry_item,
                             critical=critical)
                if critical:
                    # Critical errors should halt execution
                    raise
                # For non-critical errors, we might want to continue or return a specific value
                return None # Indicate failure for the calling method
        return wrapper
    return decorator

# --- Helper Functions (can remain outside the class if general purpose) ---
def materialize_linkedin_session() -> None:
    """Write linkedin_storage.json from the LINKEDIN_STORAGE_B64 secret (CI).

    GitHub Actions can't do an interactive login, so the session captured locally
    (via scripts/capture_session.py) is base64-encoded into a secret and decoded
    here at startup. No-op when the secret is absent (local runs use the real file).
    """
    import base64
    b64 = os.getenv("LINKEDIN_STORAGE_B64")
    if not b64:
        return
    path = os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage.json")
    try:
        data = base64.b64decode(b64.strip())
        with open(path, "wb") as f:
            f.write(data)
        logger.info(f"Materialized LinkedIn session from LINKEDIN_STORAGE_B64 -> {path} ({len(data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to decode LINKEDIN_STORAGE_B64: {e}")


def set_github_output(name: str, value: str) -> None:
    """Set an output variable for GitHub Actions"""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{name}={value}\n")

def save_artifact(content: str, filename: str) -> None:
    """Save content to an artifact file for debugging"""
    import os.path
    try:
        # Sanitize filename to prevent path traversal
        safe_filename = os.path.basename(filename)
        artifact_dir = "artifacts"
        os.makedirs(artifact_dir, exist_ok=True)
        artifact_path = os.path.join(artifact_dir, safe_filename)
        with open(artifact_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Saved artifact: {artifact_path}")
    except (OSError, IOError) as e:
        logger.error(f"Failed to save artifact {safe_filename}: {str(e)}")

# --- Main LinkedInAgent Class ---
class LinkedInAgent:
    """
    Manages the end-to-end workflow for generating and posting content to LinkedIn,
    including scheduling, content generation, deduplication, posting, and reporting.
    """
    def __init__(self, dry_run: bool = False, force_post: bool = False):
        self.dry_run = dry_run
        self.force_post = force_post
        self.run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.logger = get_logger("linkedin_agent", {"run_id": self.run_id})
        self.metrics = get_metrics_tracker("linkedin_agent_metrics.json")
        self.posted = False
        self.enable_post = not self.dry_run and os.getenv("ENABLE_POST", "true").lower() == "true"
        self._digest = ""  # performance digest injected into generation prompts
        storage.init_db()
        
        self.metrics.record_event("workflow_start")
        self.metrics.start_timer("total_execution")
        self.logger.info("LinkedIn Agent initialized.", 
                         extra={"event": "agent_init", "dry_run": self.dry_run})

    @timed_operation("schedule_check")
    def _check_posting_schedule(self) -> bool:
        """Determines if a post should be made based on schedule or force flag."""
        should_post = self.force_post or should_post_now()
        event_data = {"result": "inside" if should_post else "outside"}
        self.logger.info(f"Posting window check: {event_data['result']}", 
                         extra={"event": "posting_window_check", **event_data})
        self.metrics.record_event("posting_window_check", event_data)
        return should_post

    @timed_operation("github_activity_fetch")
    @handled_operation("GitHub activity fetch", send_report=True)
    def _fetch_github_activity(self) -> dict:
        """Fetches recent GitHub activity for context."""
        github_username = os.getenv("GITHUB_USERNAME", "AHmedaf123")
        github_token = os.getenv("GH_API_TOKEN") or os.getenv("GITHUB_TOKEN")
        
        activity = fetch_recent_github_activity(github_username, token=github_token)
        
        activity_counts = {
            "commit_count": len(activity.get('commits', [])),
            "pr_count": len(activity.get('prs', [])),
            "star_count": len(activity.get('stars', [])),
            "issue_count": len(activity.get('issues', [])),
        }
        self.logger.info(
            f"Fetched GitHub activity: {activity_counts['commit_count']} commits, {activity_counts['pr_count']} PRs",
            extra={"event": "github_activity_fetch", **activity_counts}
        )
        self.metrics.record_event("github_activity_fetch", activity_counts)
        return activity

    @timed_operation("previous_stats_collection")
    @handled_operation("Previous post stats collection") # Non-critical, continue if fails
    def _collect_previous_post_stats(self) -> None:
        """Scrape the latest engagement for the PREVIOUS post before crafting a new one.

        This makes the posting run self-contained: extract the last post's stats,
        then use that fresh data to pick the next topic and craft the post. Skipped
        on the very first run (no previous post) and in dry-run by default.
        """
        if os.getenv("COLLECT_STATS_BEFORE_POST", "true").lower() != "true":
            return
        if self.dry_run and os.getenv("COLLECT_STATS_IN_DRY_RUN", "false").lower() != "true":
            self.logger.info("Dry-run: skipping live stats collection for previous post",
                             extra={"event": "prev_stats_skip_dryrun"})
            return

        previous = storage.get_recent_posts(1)
        if not previous:
            self.logger.info("No previous post yet — skipping stats collection (first run)",
                             extra={"event": "prev_stats_skip_firstrun"})
            return

        linkedin_email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
        linkedin_password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
        if not (linkedin_email and linkedin_password) and not os.path.exists(
                os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage.json")):
            self.logger.info("No LinkedIn creds/session — skipping previous-post stats",
                             extra={"event": "prev_stats_skip_nocreds"})
            return

        with open("agent/config.json", "r") as f:
            profile_url = json.load(f).get("user", {}).get("linkedin_profile_url")

        prev_topic = previous[0].get("topic")
        self.logger.info(f"Collecting latest stats for previous post: {prev_topic!r}",
                         extra={"event": "prev_stats_collect_start", "topic": prev_topic})
        results = fetch_linkedin_engagement(
            linkedin_email, linkedin_password,
            max_posts=int(os.getenv("METRICS_MAX_POSTS", "1")),
            linkedin_profile_url=profile_url,
        )
        refreshed = storage.get_recent_posts(1)
        s = refreshed[0] if refreshed else {}
        self.logger.info(
            f"Previous post stats now: likes={s.get('likes')} comments={s.get('comments')} "
            f"impressions={s.get('impressions')}",
            extra={"event": "prev_stats_collected", "topic": prev_topic,
                   "likes": s.get("likes"), "impressions": s.get("impressions"),
                   "scraped": len(results)}
        )
        self.metrics.record_event("prev_stats_collected", {
            "topic": prev_topic, "likes": s.get("likes"),
            "comments": s.get("comments"), "impressions": s.get("impressions")})

    @timed_operation("engagement_fetch")
    @handled_operation("Engagement fetch") # Non-critical error, continue if fails
    def _fetch_linkedin_engagement(self) -> dict | None:
        """Fetches LinkedIn engagement metrics.

        Disabled during posting runs by default: metrics are collected by the
        dedicated T+24h job (`run.py --collect-metrics`), and stats used for
        generation come straight from storage. Set ENGAGEMENT_FETCH_ON_POST=true
        to also scrape live during posting runs.
        """
        if os.getenv("ENGAGEMENT_FETCH_ON_POST", "false").lower() != "true":
            stats = get_engagement_stats()
            self.logger.info("Using stored engagement stats (live fetch disabled for posting runs)",
                             extra={"event": "engagement_fetch_from_storage",
                                    "measured_posts": stats.get("total_posts", 0)})
            return stats

        linkedin_email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
        linkedin_password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
        
        with open("agent/config.json", "r") as f:
            config = json.load(f)
        linkedin_profile_url = config.get("user", {}).get("linkedin_profile_url")

        if not (linkedin_email and linkedin_password):
            self.logger.info("LinkedIn credentials not provided, skipping engagement fetch",
                             extra={"event": "engagement_fetch_skip"})
            self.metrics.record_event("engagement_fetch_skip")
            return None

        self.logger.info("Fetching LinkedIn engagement metrics", 
                         extra={"event": "engagement_fetch_start"})
        
        try:
            engagement_data = fetch_linkedin_engagement(linkedin_email, linkedin_password, linkedin_profile_url=linkedin_profile_url)
        except Exception as fetch_error:
            self.logger.error(
                f"Error fetching LinkedIn engagement: {fetch_error}",
                exc_info=True,
                extra={"event": "engagement_fetch_failure"}
            )
            self.metrics.record_event(
                "engagement_fetch_failure",
                {
                    "error_type": type(fetch_error).__name__,
                    "message": str(fetch_error)
                }
            )
            self.metrics.increment_counter("errors")
            return {"avg_likes": 0, "avg_comments": 0}

        try:
            engagement_stats = get_engagement_stats()
        except Exception as stats_error:
            self.logger.error(
                f"Error computing engagement statistics: {stats_error}",
                exc_info=True,
                extra={"event": "engagement_stats_failure"}
            )
            self.metrics.record_event(
                "engagement_stats_failure",
                {
                    "error_type": type(stats_error).__name__,
                    "message": str(stats_error)
                }
            )
            self.metrics.increment_counter("errors")
            return {"avg_likes": 0, "avg_comments": 0}

        if not isinstance(engagement_stats, dict):
            engagement_stats = {}

        if engagement_data is not None:
            self.logger.info(
                f"Fetched engagement metrics for {len(engagement_data)} posts",
                extra={
                    "event": "engagement_fetch_success",
                    "post_count": len(engagement_data),
                    "avg_likes": engagement_stats.get("avg_likes", 0),
                    "avg_comments": engagement_stats.get("avg_comments", 0)
                }
            )
            self.metrics.record_event("engagement_fetch_success", {
                "post_count": len(engagement_data),
                "avg_likes": engagement_stats.get("avg_likes", 0),
                "avg_comments": engagement_stats.get("avg_comments", 0)
            })
        else:
            fallback_stats = {
                "avg_likes": engagement_stats.get("avg_likes", 0) if isinstance(engagement_stats, dict) else 0,
                "avg_comments": engagement_stats.get("avg_comments", 0) if isinstance(engagement_stats, dict) else 0
            }
            self.logger.warning(
                "Failed to fetch engagement data",
                extra={"event": "engagement_fetch_no_data", **fallback_stats}
            )
            self.metrics.record_event("engagement_fetch_no_data", fallback_stats)
            engagement_stats = fallback_stats
        return engagement_stats

    def _regenerate_post_content(self, current_post: dict, similar_post: dict = None,
                                 regeneration_count: int = 0, low_seo_attempt: int = 0) -> dict:
        """
        Regenerates post content based on a new content strategy.
        Used for deduplication or low SEO scores.
        
        Args:
            current_post: The current post dict that needs regeneration
            similar_post: The similar post found (for deduplication), optional
            regeneration_count: Number of regeneration attempts so far
            low_seo_attempt: Counter for low SEO regeneration attempts
        """
        # Extract source from current post, default to 'niche'
        current_source = current_post.get('source', 'niche')
        
        # Calculate similarity if we have a similar post
        similarity_score = 0.0
        if similar_post:
            from agent.deduper import calculate_similarity
            similarity_score, _ = calculate_similarity(
                current_post.get('body', ''), 
                [similar_post]
            )
        
        self.metrics.increment_counter("post_regenerations")
        event_data = {
            "event": "post_regeneration",
            "reason": "deduplication" if low_seo_attempt == 0 else "low_seo",
            "similarity_score": similarity_score,
            "original_source": current_source,
            "regeneration_count": regeneration_count,
            "low_seo_attempt": low_seo_attempt
        }
        self.logger.info(f"Regenerating post (attempt {regeneration_count})", extra=event_data)
        self.metrics.record_event("post_regeneration", event_data)

        # Get a new content strategy
        new_strategy = get_next_content_strategy()
        new_source = new_strategy["source"]
        
        self.logger.info(
            f"Using new content strategy for regeneration: {new_source}",
            extra={
                "event": "regeneration_strategy_selected",
                "source": new_source,
                "priority_score": new_strategy.get("priority_score", None)
            }
        )
        try:
            # Log the new content strategy, handle missing keys gracefully
            self.logger.info(
                f"Using new content strategy for regeneration: {new_source}",
                extra={
                    "event": "regeneration_strategy_selected",
                    "source": new_source,
                    "priority_score": new_strategy.get("priority_score", None)
                }
            )
        except Exception as log_exc:
            self.logger.warning(f"Error logging regeneration strategy: {str(log_exc)}")

        # Generate post based on the new strategy
        try:
            if new_source == "repo":
                # Add regeneration hint to force a different angle and higher creativity
                regen_hint = f"REGENERATE_HINT: Vary the angle, focus on methodology, dataset, or applications; avoid repeating previous phrasing. ATTEMPT={regeneration_count}"
                post = get_next_repo_post(skip_current=True, context="\n\n".join(
                    filter(None, [self._digest, new_strategy.get("context", ""), regen_hint])))
            elif new_source in ["niche", "calendar", "trending", "fallback"]:
                regen_hint = f"REGENERATE_HINT: Vary the angle, focus on methodology, dataset, or applications; avoid repeating previous phrasing. ATTEMPT={regeneration_count}"
                post = get_niche_post(
                    topic=new_strategy.get("topic", None),
                    template=new_strategy.get("template", None),
                    force_template_rotation=True, # Ensure a fresh template if possible
                    context="\n\n".join(filter(None, [self._digest, new_strategy.get("context", "") or "", regen_hint]))
                )
            else:
                # Fallback to niche topic with different template as last resort
                post = get_niche_post(force_template_rotation=True)
                self.logger.warning(f"Unknown regeneration content strategy source: {new_source}, falling back to niche topic")
        except Exception as e:
            self.logger.error(f"Error generating post content during regeneration: {str(e)}")
            post = None

        if not post:
            self.logger.warning(f"Regeneration failed: Could not generate content for source {new_source}")
            return None

        self._attach_strategy_meta(post, new_strategy)
        return post

    @staticmethod
    def _attach_strategy_meta(post: dict, strategy: dict) -> None:
        """Stamp topic/source/template_id onto a post so publish can persist them."""
        post["topic"] = post.get("primary_topic") or strategy.get("topic")
        post["source"] = strategy.get("source", "niche")
        post["template_id"] = post.get("post_type") or strategy.get("template_id") or strategy.get("source", "default")

    @timed_operation("content_generation")
    @handled_operation("Content generation", send_report=True, retry=True, critical=True)
    def _generate_and_validate_post(self) -> dict:
        """Generates, deduplicates, and validates the post content."""
        # Feedback loop: what worked / what flopped, injected into every prompt
        self._digest = build_performance_digest()
        if self._digest:
            self.logger.info("Injecting performance digest into generation context",
                             extra={"event": "performance_digest_injected",
                                    "digest_length": len(self._digest)})
            self.metrics.record_event("performance_digest_injected")

        content_strategy = get_next_content_strategy()
        post_source = content_strategy["source"]

        self.logger.info(f"Using content strategy: {post_source}",
                         extra={"event": "content_strategy_selected", "source": post_source})
        self.metrics.record_event("content_strategy_selected", {"source": post_source})

        initial_post: dict
        if post_source == "repo":
            initial_post = get_next_repo_post(context=self._digest)
        elif post_source in ["niche", "calendar", "trending", "fallback"]:
            initial_post = get_niche_post(
                topic=content_strategy["topic"],
                template=content_strategy["template"],
                context="\n\n".join(filter(None, [self._digest, content_strategy.get("context", "")]))
            )
        else:
            self.logger.warning(f"Unknown content strategy source: {post_source}, falling back to niche topic")
            initial_post = get_niche_post()
            post_source = "niche" # Update source for accurate logging

        if not initial_post:
            self.logger.error(f"Generate post returned None for source {post_source}")
            # This raising of error will be caught by the decorator and trigger retries or exit
            raise ValueError("Failed to generate valid initial post")

        self._attach_strategy_meta(initial_post, content_strategy)
        current_post = initial_post
        regeneration_count = 0
        max_regeneration_attempts = int(os.getenv("MAX_REGENERATION_ATTEMPTS", "5"))

        while True:
            result, is_original = check_and_save_post(current_post, self._regenerate_post_content)
            if is_original:
                current_post = result
                break
            
            current_post = result 
            regeneration_count += 1
            if regeneration_count >= max_regeneration_attempts:
                self.logger.warning("Could not generate a sufficiently unique post after multiple attempts",
                                    extra={"event": "post_uniqueness_failure", "regeneration_attempts": regeneration_count})
                self.metrics.record_event("post_uniqueness_failure", {"regeneration_attempts": regeneration_count})
                break 

        # Feedback gate: reject drafts that open like historically low-performing posts
        low_perf_attempts = 0
        max_low_perf_attempts = int(os.getenv("MAX_LOW_PERFORMER_ATTEMPTS", "2"))
        while low_perf_attempts < max_low_perf_attempts:
            matches_low, low_score = is_similar_to_low_performers(current_post.get("body", ""))
            if not matches_low:
                break
            self.logger.info(
                f"Draft hook matches low-performer pattern (similarity {low_score:.2f}). Regenerating...",
                extra={"event": "post_regeneration_low_performer", "similarity": low_score}
            )
            self.metrics.record_event("post_regeneration_low_performer", {"similarity": low_score})
            regenerated = self._regenerate_post_content(
                current_post, similar_post=None,
                regeneration_count=regeneration_count + low_perf_attempts + 1
            )
            if not regenerated:
                break
            current_post = regenerated
            low_perf_attempts += 1

        # SEO is a light lint now (humanized style intentionally uses few hashtags
        # and no emojis), so the gate is lenient — voice matters more than score.
        seo_threshold = int(os.getenv("MIN_SEO_SCORE", "60"))
        low_seo_attempts = 0
        max_low_seo_attempts = int(os.getenv("MAX_LOW_SEO_ATTEMPTS", "2"))

        while current_post['seo_score'] < seo_threshold and low_seo_attempts < max_low_seo_attempts:
            self.logger.info(
                f"SEO score {current_post['seo_score']} below threshold {seo_threshold}. Regenerating...",
                extra={"event": "post_regeneration_low_seo", "attempt": low_seo_attempts + 1}
            )
            self.metrics.record_event(
                "post_regeneration_low_seo",
                {"attempt": low_seo_attempts + 1, "current_seo": current_post['seo_score']}
            )
            
            # Regenerate using a potentially different template/topic
            regenerated_post = self._regenerate_post_content(
                current_post, similar_post=None, 
                regeneration_count=regeneration_count + 1, 
                low_seo_attempt=low_seo_attempts + 1
            )
            
            # If regeneration failed, keep the current post and stop trying
            if regenerated_post is None:
                self.logger.warning(
                    f"Regeneration failed at attempt {low_seo_attempts + 1}, keeping current post",
                    extra={"event": "regeneration_failed_keeping_current"}
                )
                break
            
            current_post = regenerated_post
            low_seo_attempts += 1
            save_artifact(current_post["body"], "post_preview.txt") # Save latest preview

        if current_post['seo_score'] < seo_threshold:
            self.logger.warning(f"Final post SEO score ({current_post['seo_score']}) still below threshold ({seo_threshold}) after retries.",
                                extra={"event": "final_post_low_seo", "final_seo_score": current_post['seo_score']})
            self.metrics.record_event("final_post_low_seo", {"final_seo_score": current_post['seo_score']})
            # Decide if this should be a critical error or if we proceed with a warning.
            # For now, we proceed as it might still be valuable, but log it clearly.

        save_artifact(current_post["body"], "post_preview.txt")
        
        post_metrics = {
            "seo_score": current_post['seo_score'],
            "source": post_source, # Original source, could be updated if regenerated fully
            "keyword_count": len(current_post['seo_keywords']),
            "hashtag_count": len(current_post['hashtags']),
            "is_original": is_original,
            "regeneration_count": regeneration_count,
            "character_count": len(current_post["body"])
        }
        self.logger.info(f"Generated post with SEO score: {current_post['seo_score']}",
                         extra={"event": "post_generation_success", **post_metrics})
        self.metrics.record_event("post_generation_success", post_metrics)
        self.metrics.set_gauge("seo_score", current_post['seo_score'])
        
        return current_post

    @timed_operation("linkedin_posting")
    @handled_operation("LinkedIn posting", send_report=True, retry=True)
    def _publish_to_linkedin(self, post_content: str, post_data: dict) -> None:
        """Publishes the post to LinkedIn or simulates in dry-run mode."""
        if self.enable_post:
            post_to_linkedin(post_content)
            self.logger.info("Successfully posted to LinkedIn",
                             extra={"event": "linkedin_post_success"})
            self.metrics.record_event("linkedin_post_success")
            self._update_post_history(post_data)
            self.posted = True
            self._post_first_comment(post_data)
        else:
            self.logger.info("Draft mode: post content prepared but not published",
                             extra={"event": "linkedin_post_draft"})
            self.metrics.record_event("linkedin_post_draft")
            self.posted = True # Still consider successful for scheduling in draft mode

    def _update_post_history(self, post: dict) -> None:
        """Persists the published post (with topic/hook/template_id) to storage."""
        try:
            saved = storage.save_used_post(post)
            self.logger.info(f"Post history saved to storage: {saved}",
                             extra={"event": "post_history_saved", "new_record": saved,
                                    "topic": post.get("topic"), "template_id": post.get("template_id")})
            self.metrics.record_event("post_history_saved", {"title": post.get("title"),
                                                             "length": len(post.get("body", ""))})
        except Exception:
            self.logger.error("Failed to persist post history", exc_info=True)

    def _post_first_comment(self, post: dict) -> None:
        """First-comment strategy (opt-in): add one extra insight under our own post."""
        if os.getenv("ENABLE_FIRST_COMMENT", "false").lower() != "true":
            return
        try:
            from agent.growth_agent import run_first_comment
            with open("agent/config.json", "r") as f:
                profile_url = json.load(f).get("user", {}).get("linkedin_profile_url")
            if not profile_url:
                self.logger.warning("First-comment skipped: no linkedin_profile_url in config.json")
                return
            ok = run_first_comment(profile_url, post.get("body", ""))
            self.metrics.record_event("first_comment", {"success": ok})
        except Exception:
            self.logger.error("First-comment step failed (non-critical)", exc_info=True)

    @timed_operation("email_report")
    @handled_operation("Email reporting", send_report=True, retry=True)
    def _send_report_email(self, post: dict) -> None:
        """Sends an email report about the posted content."""
        # If posting failed, include debug attachments when available
        attachments = []
        if not self.posted:
            for fname in [
                "before_post_click_screenshot.png",
                "before_post_click_page.html",
                "after_post_click_screenshot.png",
                "after_post_click_page.html",
                "final_error_state_screenshot.png",
                "verification_timeout_screenshot.png",
            ]:
                if os.path.exists(fname):
                    attachments.append(fname)
        sent = send_email_report(post, is_error=not self.posted, is_draft=not self.enable_post, attachments=attachments or None)
        if sent:
            self.logger.info("Email report sent", extra={"event": "email_report_success", "posted": self.posted})
            self.metrics.record_event("email_report_success", {"posted": self.posted})
        else:
            self.logger.warning("Email report NOT sent (send returned False — check SMTP creds/quota)",
                                extra={"event": "email_report_failed", "posted": self.posted})
            self.metrics.record_event("email_report_failed", {"posted": self.posted})

    @timed_operation("schedule_update")
    @handled_operation("Schedule update", send_report=True, retry=True)
    def _update_next_post_schedule(self) -> None:
        """Updates the scheduler for the next post time."""
        next_time = update_next_post_time()
        self.logger.info(f"Updated next post time to {next_time}",
                         extra={"event": "schedule_update", "next_post_time": next_time})
        self.metrics.record_event("schedule_update", {"next_post_time": next_time})
        self.metrics.set_gauge("next_post_time", next_time)

    def run(self) -> bool:
        """Main execution flow of the LinkedIn Agent."""
        try:
            self.logger.info("Starting LinkedIn Agent workflow.", 
                             extra={"event": "workflow_start", "dry_run": self.dry_run})
            
            # 1. Check if it's time to post
            if not self._check_posting_schedule():
                self.logger.info("Outside of posting window, exiting.", extra={"event": "workflow_exit_scheduled"})
                return False

            self.logger.info(f"Posting mode: {'live' if self.enable_post else 'draft'}", 
                             extra={"event": "posting_mode", "mode": "live" if self.enable_post else "draft"})
            self.metrics.set_gauge("posting_mode", "live" if self.enable_post else "draft")

            # 2. Fetch external data (can run concurrently if needed, but sequential here)
            github_activity = self._fetch_github_activity()

            # 2b. Collect the PREVIOUS post's latest stats FIRST, so the digest that
            #     drives topic choice + crafting is based on fresh engagement data.
            self._collect_previous_post_stats()

            linkedin_engagement_stats = self._fetch_linkedin_engagement()

            # 3. Generate, deduplicate, and validate post content
            generated_post = self._generate_and_validate_post()
            if generated_post is None: # _generate_and_validate_post caught a critical error
                self.logger.error("Failed to generate and validate post, exiting workflow.", extra={"event": "workflow_exit_content_error"})
                return False

            # 4. Publish to LinkedIn (critical for main objective);
            #    persists the post record + optional first comment on success
            self._publish_to_linkedin(generated_post["body"], generated_post)

            # 5. Send email report (non-critical, continue if fails)
            self._send_report_email(generated_post)

            # 6. Update next post schedule (non-critical, continue if fails)
            if self.posted: # Only update schedule if a post was effectively made/drafted
                self._update_next_post_schedule()
                # Topic is now saved during content strategy selection in get_next_topic_strategy()
                # No need to save it again here to avoid duplicates

            set_github_output("posted", str(self.posted).lower())
            
            total_duration = self.metrics.stop_timer("total_execution")
            self.metrics.set_gauge("total_duration_seconds", total_duration)
            self.metrics.set_gauge("posted", self.posted)
            self.logger.info("Workflow completed successfully.", 
                             extra={"event": "workflow_complete", "posted": self.posted, "duration_seconds": total_duration})
            return True

        except Exception as e:
            # Catch any unhandled exceptions from the `run` method itself
            if "total_execution" in self.metrics._active_timers:
                total_duration = self.metrics.stop_timer("total_execution")
            else:
                total_duration = 0
            
            self.logger.error(
                f"Unhandled critical error in main workflow: {str(e)}",
                exc_info=True,
                extra={"event": "workflow_failure", "duration_seconds": total_duration}
            )
            self.metrics.record_event("workflow_failure", {"error": str(e), "duration_seconds": total_duration})
            self.metrics.increment_counter("errors")
            handle_error(e, "Main workflow", send_report=True, critical=True) # Ensure critical errors are reported
            return False
        finally:
            self.metrics.save() # Always save metrics at the end of a run

# --- Entry point for script execution ---
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="LinkedIn Agent")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no actual posting)")
    parser.add_argument("--force", action="store_true", help="Force posting regardless of schedule")
    parser.add_argument("--process-retries", action="store_true", help="Process retry queue")
    parser.add_argument("--check-health", action="store_true", help="Check system health")
    parser.add_argument("--collect-metrics", action="store_true",
                        help="Scrape engagement (likes/comments/impressions) for recent posts and persist it")
    parser.add_argument("--growth", action="store_true",
                        help="Run a rate-limited growth session (niche comments + connection requests)")
    return parser.parse_args()


def collect_metrics_cli() -> None:
    """Scrape engagement for recent posts and store it (T+24h/T+48h job)."""
    linkedin_email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
    linkedin_password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
    with open("agent/config.json", "r") as f:
        profile_url = json.load(f).get("user", {}).get("linkedin_profile_url")

    storage.init_db()
    # Only the agent's own latest post(s) — not the whole profile feed.
    results = fetch_linkedin_engagement(
        linkedin_email, linkedin_password,
        max_posts=int(os.getenv("METRICS_MAX_POSTS", "1")),
        linkedin_profile_url=profile_url,
    )
    stats = get_engagement_stats()
    logger.info(
        f"Metrics collection done: scraped {len(results)} posts; "
        f"{stats.get('total_posts', 0)} posts have stored engagement "
        f"(avg {stats.get('avg_likes', 0):.1f} likes, {stats.get('avg_impressions', 0):.0f} impressions)"
    )

def main_cli():
    """
    Main command-line interface entry point for the LinkedIn Agent.
    Handles special operations like retry processing or health checks before
    potentially initiating a posting workflow.
    """
    args = parse_arguments()
    materialize_linkedin_session()  # decode LINKEDIN_STORAGE_B64 secret into the session file (CI)
    metrics = get_metrics_tracker("linkedin_agent_metrics.json") # CLI specific metrics tracker

    try:
        if args.process_retries:
            logger.info("Processing retry queue via CLI command.")
            process_retry_queue()
            logger.info("Retry queue processing complete.")
            metrics.record_event("retry_queue_process_cli")
            return

        if args.check_health:
            logger.info("Checking system health via CLI command.")
            health_status = check_system_health()
            logger.info(f"System health check complete: {health_status['status']}",
                         extra={"status": health_status['status']})
            metrics.record_event("health_check_cli", {"status": health_status['status']})
            return

        if args.collect_metrics:
            logger.info("Collecting engagement metrics via CLI command.")
            collect_metrics_cli()
            metrics.record_event("metrics_collection_cli")
            return

        if args.growth:
            logger.info("Running growth session via CLI command.")
            from agent.growth_agent import run_growth
            result = run_growth(load_niches_list())
            logger.info(f"Growth session result: {result}")
            metrics.record_event("growth_session_cli", result)
            return

        # Regular workflow execution
        agent = LinkedInAgent(dry_run=args.dry_run, force_post=args.force)
        agent.run()

    except Exception as e:
        logger.critical(f"Fatal error in CLI entry point: {str(e)}", exc_info=True)
        handle_error(e, "CLI Main", critical=True, send_report=True)
    finally:
        metrics.save() # Ensure metrics are saved even for CLI-specific actions

if __name__ == "__main__":
    main_cli()