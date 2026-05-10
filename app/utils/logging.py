import logging
import sys

def setup_logging():
    logger = logging.getLogger("tradeservices")
    logger.setLevel(logging.INFO)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    
    # Avoid duplicate logs if setup is called multiple times
    if not logger.handlers:
        logger.addHandler(handler)
        
    return logger

logger = setup_logging()
