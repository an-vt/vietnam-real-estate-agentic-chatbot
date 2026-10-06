"""Configure logging for this application's modules without changing Uvicorn logs."""

import logging


_HANDLER_MARKER = "_real_estate_app_handler"


def setup_logging(level: str) -> None:
    """Send application logs to stderr without adding duplicate handlers."""
    app_logger = logging.getLogger("src")
    app_logger.setLevel(level)
    app_logger.propagate = False

    if any(getattr(handler, _HANDLER_MARKER, False) for handler in app_logger.handlers):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    setattr(handler, _HANDLER_MARKER, True)
    app_logger.addHandler(handler)
