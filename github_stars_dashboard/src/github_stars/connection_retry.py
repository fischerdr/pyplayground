"""Database connection retry utilities for container orchestration."""

import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry_on_connection(
    max_retries: int = 5,
    delay: int = 10,
    backoff: int = 2,
    exceptions: tuple = (Exception,),
) -> Callable[..., Any]:
    """Decorator to retry database connection on failure.

    Args:
        max_retries: Maximum number of retry attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier for delay between retries.
        exceptions: Tuple of exception types to catch and retry.

    Returns:
        Decorated function with retry logic.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            attempt = 0

            while attempt < max_retries:
                try:
                    logger.debug(
                        f"Attempt {attempt + 1}/{max_retries} to execute {func.__name__}"
                    )
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if attempt < max_retries:
                        logger.warning(
                            f"Connection failed (attempt {attempt}/{max_retries}): {e}. "
                            f"Retrying in {current_delay}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"Failed to execute {func.__name__} after {max_retries} attempts: {e}"
                        )
                        raise

            return None

        return wrapper

    return decorator
