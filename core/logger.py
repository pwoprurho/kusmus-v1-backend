# core/logger.py
import logging
import os
import sys

def setup_logger(app):
    """
    Configures centralized logging for the Kusmus AI platform.
    In production, this logs to SysLog or a structured log file.
    In development, it prints to standard output with readable formatting.
    """
    log_level = logging.DEBUG if app.debug else logging.INFO
    
    # Define formatting
    log_format = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    
    # Console Handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(log_format)
    
    # Configure root logger
    logger = logging.getLogger('kusmus')
    logger.setLevel(log_level)
    logger.addHandler(handler)
    
    # Attach to Flask logger
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)
    
    logger.info(f"[*] Centralized logging initialized at level {logging.getLevelName(log_level)}")
    
    return logger

# Global logger instance
logger = logging.getLogger('kusmus')
