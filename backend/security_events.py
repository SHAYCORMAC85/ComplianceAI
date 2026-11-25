"""Security events contain only operation codes, outcomes and a pseudonymous actor."""
import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("compliance.security")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())


def event(operation, outcome, actor=None):
    fields = {"time": datetime.now(timezone.utc).isoformat(), "operation": operation, "outcome": outcome}
    if actor:
        fields["officer_ref"] = hashlib.sha256(actor.encode()).hexdigest()[:20]
    logger.info(json.dumps(fields, separators=(",", ":")))
