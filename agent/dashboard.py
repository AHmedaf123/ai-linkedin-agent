import json
import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from datetime import datetime, timedelta
import numpy as np
from typing import Dict, List, Any, Optional, Tuple


class MetricsDashboard:
    """Generate visualizations and reports from LinkedIn Agent metrics data."""

    def __init__(self, metrics_file: str = "linkedin_agent_metrics.json"):
        """Initialize the dashboard with the metrics file path.

        Args:
            metrics_file: Path to the metrics JSON file
        """
        self.metrics_file = metrics_file
        self.metrics_data = self._load_metrics()
        # Prevent path traversal by restricting metrics_file to a trusted directory
        base_dir = os.path.abspath(os.getcwd())
        metrics_path = os.path.abspath(metrics_file)
        if not metrics_path.startswith(base_dir):
            raise ValueError("Invalid metrics_file path: Path traversal detected.")
        self.output_dir = os.path.join(os.path.dirname(metrics_path), "dashboard")
        os.makedirs(self.output_dir, exist_ok=True)

    def _load_metrics(self) -> Dict[str, Any]:
        """Load metrics data from the JSON file.

        Returns:
            Dictionary containing the metrics data
        """
        if not os.path.exists(self.metrics_file):
            return {"events": [], "timers": {}, "counters": {}, "gauges": {}}

        try:
            with open(self.metrics_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error decoding metrics file: {self.metrics_file}")
            return {"events": [], "timers": {}, "counters": {}, "gauges": {}}

    def _events_to_dataframe(self) -> pd.DataFrame:
        """Convert events data to a pandas DataFrame.

        Returns:
            DataFrame with events data
        """
        events = self.metrics_data.get("events", [])
        if not events:
            return pd.DataFrame()

        try:
            # Normalize the events data
            df = pd.json_normalize(events)
            
            # Convert timestamp to datetime
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                df["date"] = df["timestamp"].dt.date
            except Exception as e:
                print(f"Error converting 'timestamp' to datetime: {e}")
                df["timestamp"] = pd.NaT
                df["date"] = None
                df["date"] = df["timestamp"].dt.date

            return df
        except (ValueError, TypeError, KeyError) as e:
            print(f"Error processing events data: {e}")
            return pd.DataFrame()

    def generate_execution_time_chart(self) -> str:
        """Generate a chart showing execution times for different workflow phases.

        Returns:
            Path to the saved chart image
        """
        df = self._events_to_dataframe()
        if df.empty:
            return ""

        # Filter workflow_complete events to get total execution times
        workflow_df = df[df["event"] == "workflow_complete"].copy()
        if workflow_df.empty:
            return ""

        # Create a figure with multiple subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        fig.suptitle("LinkedIn Agent Execution Performance", fontsize=16)

        # Plot 1: Total execution time trend
        if "data.duration_seconds" in workflow_df.columns:
            workflow_df = workflow_df.sort_values("timestamp")
            ax1.plot(workflow_df["timestamp"], workflow_df["data.duration_seconds"], marker="o", linestyle="-")
            ax1.set_title("Total Execution Time Trend")
            ax1.set_xlabel("Date")
            ax1.set_ylabel("Duration (seconds)")
            ax1.grid(True)
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

        # Plot 2: Average execution time by phase
        phase_times = {}
        for timer_name, timer_data in self.metrics_data.get("timers", {}).items():
            if timer_name != "total_execution":
                phase_times[timer_name] = np.mean(timer_data)

        if phase_times:
            phases = list(phase_times.keys())
            times = list(phase_times.values())
            
            # Sort by execution time
            sorted_indices = np.argsort(times)
            sorted_phases = [phases[i] for i in sorted_indices]
            sorted_times = [times[i] for i in sorted_indices]
            
            bars = ax2.barh(sorted_phases, sorted_times)
            ax2.set_title("Average Execution Time by Phase")
            ax2.set_xlabel("Duration (seconds)")
            ax2.set_ylabel("Workflow Phase")
            ax2.grid(True, axis="x")
            
            # Add time labels to the bars
            for bar in bars:
                width = bar.get_width()
                label_x_pos = width * 1.01
                ax2.text(label_x_pos, bar.get_y() + bar.get_height()/2, f"{width:.2f}s", 
                        va="center")

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        
        # Save the chart
        chart_path = os.path.join(self.output_dir, "execution_time_chart.png")
        plt.savefig(chart_path)
        plt.close()
        
        return chart_path

    def generate_post_metrics_chart(self) -> str:
        """Generate a chart showing post generation metrics.

        Returns:
            Path to the saved chart image
        """
        df = self._events_to_dataframe()
        if df.empty:
            return ""

        # Filter post generation success events
        post_df = df[df["event"] == "post_generation_success"].copy()
        if post_df.empty:
            return ""

        # Create a figure with multiple subplots
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle("LinkedIn Post Generation Metrics", fontsize=16)

        # Plot 1: SEO Score Trend
        if "data.seo_score" in post_df.columns:
            post_df = post_df.sort_values("timestamp")
            axes[0, 0].plot(post_df["timestamp"], post_df["data.seo_score"], marker="o", linestyle="-")
            axes[0, 0].set_title("SEO Score Trend")
            axes[0, 0].set_xlabel("Date")
            axes[0, 0].set_ylabel("SEO Score")
            axes[0, 0].grid(True)
            plt.setp(axes[0, 0].xaxis.get_majorticklabels(), rotation=45)

        # Plot 2: Post Source Distribution
        if "data.source" in post_df.columns:
            source_counts = post_df["data.source"].value_counts()
            axes[0, 1].pie(source_counts, labels=source_counts.index, autopct="%1.1f%%", 
                          startangle=90, shadow=True)
            axes[0, 1].set_title("Post Source Distribution")
            axes[0, 1].axis("equal")  # Equal aspect ratio ensures that pie is drawn as a circle

        # Plot 3: Character Count Distribution
        if "data.character_count" in post_df.columns:
            sns.histplot(post_df["data.character_count"], kde=True, ax=axes[1, 0])
            axes[1, 0].set_title("Post Character Count Distribution")
            axes[1, 0].set_xlabel("Character Count")
            axes[1, 0].set_ylabel("Frequency")
            axes[1, 0].grid(True)

        # Plot 4: Regeneration Count Distribution
        if "data.regeneration_count" in post_df.columns:
            regen_counts = post_df["data.regeneration_count"].value_counts().sort_index()
            axes[1, 1].bar(regen_counts.index.astype(str), regen_counts.values)
            axes[1, 1].set_title("Post Regeneration Count Distribution")
            axes[1, 1].set_xlabel("Number of Regenerations")
            axes[1, 1].set_ylabel("Frequency")
            axes[1, 1].grid(True, axis="y")

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        
        # Save the chart
        chart_path = os.path.join(self.output_dir, "post_metrics_chart.png")
        plt.savefig(chart_path)
        plt.close()
        
        return chart_path

    def generate_error_analysis_chart(self) -> str:
        """Generate a chart showing error metrics.

        Returns:
            Path to the saved chart image
        """
        df = self._events_to_dataframe()
        if df.empty:
            return ""

        # Filter error events
        error_df = df[df["event"].str.contains("error", case=False)].copy()
        if error_df.empty:
            return ""

        # Create a figure with multiple subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle("LinkedIn Agent Error Analysis", fontsize=16)

        # Plot 1: Error frequency by type
        error_counts = error_df["event"].value_counts()
        ax1.barh(error_counts.index, error_counts.values)
        ax1.set_title("Error Frequency by Type")
        ax1.set_xlabel("Count")
        ax1.set_ylabel("Error Type")
        ax1.grid(True, axis="x")

        # Plot 2: Error trend over time
        error_by_date = error_df.groupby("date").size()
        ax2.plot(error_by_date.index, error_by_date.values, marker="o", linestyle="-")
        ax2.set_title("Error Trend Over Time")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Number of Errors")
        ax2.grid(True)
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        
        # Save the chart
        chart_path = os.path.join(self.output_dir, "error_analysis_chart.png")
        plt.savefig(chart_path)
        plt.close()
        
        return chart_path

    def generate_summary_report(self) -> str:
        """Generate a summary report of key metrics.

        Returns:
            Path to the saved report file
        """
        df = self._events_to_dataframe()
        if df.empty:
            return ""

        # Calculate summary statistics
        total_runs = len(df[df["event"] == "workflow_start"])
        successful_posts = len(df[df["event"] == "linkedin_post_success"])
        draft_posts = len(df[df["event"] == "linkedin_post_draft"])
        total_errors = len(df[df["event"].str.contains("error", case=False)])
        
        # Calculate success rate
        success_rate = (successful_posts / total_runs * 100) if total_runs > 0 else 0
        
        # Calculate average execution time
        avg_execution_time = 0
        if "data.duration_seconds" in df.columns and "event" in df.columns:
            workflow_complete = df[df["event"] == "workflow_complete"]
            if not workflow_complete.empty and "data.duration_seconds" in workflow_complete.columns:
                avg_execution_time = workflow_complete["data.duration_seconds"].mean()
        
        # Calculate average SEO score
        avg_seo_score = 0
        if "data.seo_score" in df.columns and "event" in df.columns:
            post_gen = df[df["event"] == "post_generation_success"]
            if not post_gen.empty and "data.seo_score" in post_gen.columns:
                avg_seo_score = post_gen["data.seo_score"].mean()
        
        # Generate the report content
        report_content = f"""# LinkedIn Agent Performance Summary

## Overview
- **Total Runs**: {total_runs}
- **Successful Posts**: {successful_posts}
- **Draft Posts**: {draft_posts}
- **Total Errors**: {total_errors}
- **Success Rate**: {success_rate:.2f}%

## Performance Metrics
- **Average Execution Time**: {avg_execution_time:.2f} seconds
- **Average SEO Score**: {avg_seo_score:.2f}

## Error Analysis
"""

        # Add error breakdown if there are errors
        if total_errors > 0:
            error_counts = df[df["event"].str.contains("error", case=False)]["event"].value_counts()
            report_content += "### Error Breakdown\n"
            for error_type, count in error_counts.items():
                report_content += f"- **{error_type}**: {count} occurrences\n"
        
        # Add recent activity
        report_content += "\n## Recent Activity\n"
        recent_df = df.sort_values("timestamp", ascending=False).head(10)
        for _, row in recent_df.iterrows():
            timestamp = row["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if "timestamp" in row else "Unknown"
            event = row["event"] if "event" in row else "Unknown"
            report_content += f"- **{timestamp}**: {event}\n"
        
        # Save the report
        report_path = os.path.join(self.output_dir, "summary_report.md")
        with open(report_path, "w") as f:
            f.write(report_content)
        
        return report_path

    def generate_dashboard(self) -> List[str]:
        """Generate all dashboard components.

        Returns:
            List of paths to generated files
        """
        generated_files = []
        
        # Generate execution time chart
        exec_chart = self.generate_execution_time_chart()
        if exec_chart:
            generated_files.append(exec_chart)
        
        # Generate post metrics chart
        post_chart = self.generate_post_metrics_chart()
        if post_chart:
            generated_files.append(post_chart)
        
        # Generate error analysis chart
        error_chart = self.generate_error_analysis_chart()
        if error_chart:
            generated_files.append(error_chart)
        
        # Generate summary report
        summary_report = self.generate_summary_report()
        if summary_report:
            generated_files.append(summary_report)
        
        return generated_files


def generate_dashboard(metrics_file: str = "linkedin_agent_metrics.json") -> List[str]:
    """Generate a dashboard from metrics data.

    Args:
        metrics_file: Path to the metrics JSON file

    Returns:
        List of paths to generated dashboard files
    """
    dashboard = MetricsDashboard(metrics_file)
    return dashboard.generate_dashboard()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate LinkedIn Agent metrics dashboard")
    parser.add_argument("--metrics-file", default="linkedin_agent_metrics.json",
                        help="Path to the metrics JSON file")
    args = parser.parse_args()
    
    files = generate_dashboard(args.metrics_file)
    print(f"Dashboard generated with {len(files)} components:")
    for file in files:
        print(f"- {file}")