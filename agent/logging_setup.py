import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    """Custom formatter that outputs log records as JSON objects"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info)
            }
        
        # Add extra fields from the record
        if hasattr(record, "extra") and record.extra:
            log_data["extra"] = record.extra
        
        return json.dumps(log_data)


class LoggerAdapter(logging.LoggerAdapter):
    """Custom logger adapter that adds extra fields to log records"""
    
    def process(self, msg, kwargs):
        """Process the logging message and keyword arguments"""
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        if hasattr(self, 'extra'):
            kwargs['extra'].update(self.extra)
        return msg, kwargs


def setup_logging(log_file: Optional[str] = None, 
                 console_level: int = logging.INFO, 
                 file_level: int = logging.DEBUG,
                 json_format: bool = True) -> logging.Logger:
    """Set up logging with console and file handlers
    
    Args:
        log_file: Path to log file. If None, no file handler is created
        console_level: Logging level for console output
        file_level: Logging level for file output
        json_format: Whether to use JSON formatting for logs
        
    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger("linkedin-agent")
    logger.setLevel(logging.DEBUG)  # Set to lowest level, handlers will filter
    
    # Clear existing handlers
    logger.handlers = []
    
    # Create formatters
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (if log_file is provided)
    if log_file:
        # Create directory only if log_file has a directory path
        log_dir = os.path.dirname(log_file)
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as dir_exc:
                # Log warning but continue without file handler
                logger.warning(f"Failed to create log directory {log_dir}: {dir_exc}", exc_info=True)
                log_dir = None  # Prevent further directory creation attempts
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(file_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as file_exc:
            # Log warning but continue without file handler
            logger.warning(f"Failed to create file handler for {log_file}: {file_exc}", exc_info=True)
    
    return logger


def get_logger(name: str, extra: Optional[Dict[str, Any]] = None) -> LoggerAdapter:
    """Get a logger with optional extra fields
    
    Args:
        name: Name of the logger (will be appended to base logger name)
        extra: Extra fields to add to all log records
        
    Returns:
        Logger adapter with extra fields
    """
    logger = logging.getLogger(f"linkedin-agent.{name}")
    adapter = LoggerAdapter(logger, extra or {})
    adapter.extra = extra or {}
    return adapter