# LinkedIn Agent Metrics and Dashboard

This document describes the metrics tracking and dashboard visualization features of the LinkedIn Agent.

## Metrics Tracking

The LinkedIn Agent now includes comprehensive metrics tracking to monitor performance, execution times, and operational statistics. This helps in identifying bottlenecks, tracking success rates, and understanding the overall health of the automation process.

### Types of Metrics

1. **Events**: Point-in-time occurrences with associated metadata
   - Workflow starts/completions
   - Content generation events
   - Posting successes/failures
   - Error events

2. **Timers**: Duration measurements for operations
   - Total execution time
   - GitHub activity fetch time
   - Content generation time
   - LinkedIn posting time

3. **Counters**: Numeric values that increment
   - Error counts
   - Post regeneration attempts
   - Successful posts

4. **Gauges**: Current value measurements
   - SEO scores
   - Next post time
   - Posting mode (live/draft)

### Metrics Storage

Metrics are stored in a JSON file (`linkedin_agent_metrics.json`) with the following structure:

```json
{
  "events": [
    {
      "event": "workflow_start",
      "timestamp": "2023-06-01T12:00:00Z"
    },
    {
      "event": "post_generation_success",
      "timestamp": "2023-06-01T12:01:30Z",
      "data": {
        "seo_score": 85,
        "source": "repo",
        "keyword_count": 5,
        "hashtag_count": 3,
        "is_original": true,
        "regeneration_count": 0,
        "duration_seconds": 45.2,
        "character_count": 1250
      }
    }
  ],
  "timers": {
    "total_execution": [120.5, 115.2, 118.7],
    "github_activity_fetch": [3.2, 2.8, 3.5],
    "content_generation": [45.2, 42.1, 48.3]
  },
  "counters": {
    "errors": 2,
    "post_regenerations": 3
  },
  "gauges": {
    "seo_score": 85,
    "next_post_time": "2023-06-02T12:00:00Z",
    "posting_mode": "live"
  }
}
```

## Dashboard Visualization

The metrics dashboard provides visual representations of the collected metrics to help understand trends, patterns, and performance characteristics.

### Dashboard Components

1. **Execution Time Chart**
   - Total execution time trend
   - Average execution time by workflow phase

2. **Post Metrics Chart**
   - SEO score trend
   - Post source distribution (repo vs. niche)
   - Character count distribution
   - Regeneration count distribution

3. **Error Analysis Chart**
   - Error frequency by type
   - Error trend over time

4. **Summary Report**
   - Overview statistics (total runs, success rate, etc.)
   - Performance metrics
   - Error breakdown
   - Recent activity log

### Generating the Dashboard

To generate the dashboard, run the `generate_dashboard.py` script:

```bash
python generate_dashboard.py --metrics-file linkedin_agent_metrics.json
```

Options:
- `--metrics-file`: Path to the metrics JSON file (default: `linkedin_agent_metrics.json`)
- `--output-dir`: Directory to save dashboard files (default: `dashboard`)
- `--log-level`: Logging level (default: `INFO`)

### Viewing the Dashboard

After generating the dashboard, you can find the following files in the output directory:

- `execution_time_chart.png`: Chart showing execution time metrics
- `post_metrics_chart.png`: Chart showing post generation metrics
- `error_analysis_chart.png`: Chart showing error metrics
- `summary_report.md`: Markdown report with key statistics and recent activity

## Integration with Workflow

The metrics tracking is fully integrated into the main workflow in `run.py`. Each phase of the workflow records relevant metrics:

1. **Initialization**: Records workflow start and begins total execution timer
2. **Schedule Check**: Measures schedule check time and records result
3. **GitHub Activity Fetch**: Tracks fetch duration and activity counts
4. **Content Generation**: Measures generation time, tracks regeneration attempts, and records SEO metrics
5. **LinkedIn Posting**: Tracks posting duration and success/failure
6. **Email Reporting**: Measures email sending time
7. **Schedule Update**: Records next post time
8. **Completion**: Records total execution time and workflow completion

## Extending Metrics

To add new metrics to the system:

1. **Add Event Recording**: Use `metrics.record_event("event_name", {"key": "value"})` to record new events
2. **Add Timers**: Use `metrics.start_timer("timer_name")` and `metrics.stop_timer("timer_name")` to measure durations
3. **Add Counters**: Use `metrics.increment_counter("counter_name")` to track occurrences
4. **Add Gauges**: Use `metrics.set_gauge("gauge_name", value)` to record current values

## Troubleshooting

- If metrics are not being recorded, check that `metrics.save()` is being called at the end of the workflow
- If timers show unexpected values, ensure that each `start_timer()` has a corresponding `stop_timer()`
- If the dashboard fails to generate, verify that the metrics file exists and contains valid JSON