import logging
import sys

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"tradeservices.{name}")
    logger.setLevel(logging.INFO)
    
    # Avoid adding duplicate handlers if they already exist
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger
