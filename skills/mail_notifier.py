"""InfoLoop email notification skill scaffold.

Step 1 defines the digest email entrypoint used by the OpenClaw manifest.
Full HTML rendering and SMTP delivery logic will be implemented in Step 3.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def send_digest_email(summarized_json: List[Dict[str, Any]]) -> bool:
    """Send an indexed HTML digest email to the configured target mailbox.

    Args:
        summarized_json: Structured article summaries.

    Returns:
        bool: ``False`` in Step 1 scaffold mode.
    """
    logger.info(
        "mail_notifier.send_digest_email scaffold invoked with %s item(s).",
        len(summarized_json),
    )
    return False


if __name__ == "__main__":
    ok = send_digest_email(
        summarized_json=[
            {
                "index": 1,
                "title": "Demo title",
                "category": "Demo category",
                "summary": "Demo summary",
            }
        ]
    )
    print(f"Digest sent: {ok}")
