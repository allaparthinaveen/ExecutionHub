import json
from datetime import datetime
from typing import Dict, Any

class EventStore:
    """
    Simple file-based event store for audit trailing.
    Records every critical decision and state change.
    """
    def __init__(self, log_file: str = "audit_events.jsonl"):
        self.log_file = log_file
        
    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Record a structured event for compliance and forensics.
        """
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "payload": payload
        }
        
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            # We log to stdout as fallback if event store fails to write
            print(f"FAILED TO RECORD EVENT: {e} - {event}")
