from __future__ import annotations

import logging
import sys


def configure_logging() -> logging.Logger:
    log_formatter = logging.Formatter("%(levelname)s | %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    if not logger.handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logging.getLogger("disnake.gateway").setLevel(logging.WARNING)
    logging.getLogger("disnake.client").setLevel(logging.WARNING)
    logging.getLogger("disnake.http").setLevel(logging.INFO)

    return logging.getLogger("bot")
