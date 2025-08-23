#!/usr/bin/env python3

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from agent.dashboard import generate_dashboard
from agent.logging_setup import setup_logging, get_logger


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate LinkedIn Agent metrics dashboard")
    parser.add_argument("--metrics-file", default="linkedin_agent_metrics.json",
                        help="Path to the metrics JSON file")
    parser.add_argument("--output-dir", default="dashboard",
                        help="Directory to save dashboard files")
    parser.add_argument("--log-level", default="INFO",
                        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_level=args.log_level)
    logger = get_logger("dashboard_generator")
    
    logger.info(f"Starting dashboard generation from metrics file: {args.metrics_file}")
    
    # Check if metrics file exists
    if not os.path.exists(args.metrics_file):
        logger.error(f"Metrics file not found: {args.metrics_file}")
        print(f"Error: Metrics file not found: {args.metrics_file}")
        return 1
    
    try:
        # Generate dashboard
        start_time = datetime.now()
        files = generate_dashboard(args.metrics_file)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Log results
        logger.info(f"Dashboard generation completed in {duration:.2f} seconds")
        logger.info(f"Generated {len(files)} dashboard components")
        
        # Print results to console
        print(f"\nDashboard generation completed in {duration:.2f} seconds")
        print(f"Generated {len(files)} dashboard components:")
        for file in files:
            print(f"- {file}")
            logger.debug(f"Generated file: {file}")
        
        # Provide instructions for viewing
        dashboard_dir = os.path.dirname(files[0]) if files else args.output_dir
        print(f"\nTo view the dashboard, open the files in the directory:\n{dashboard_dir}")
        
        return 0
    except Exception as e:
        logger.error(f"Error generating dashboard: {str(e)}", exc_info=True)
        print(f"Error generating dashboard: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())