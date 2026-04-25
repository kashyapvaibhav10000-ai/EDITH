"""
EDITH Event Bus — Item 6: Pub/Sub backbone

Topics: SYSTEM_ALERT, CALENDAR_REMINDER, EMAIL_ARRIVED, AGENT_DONE,
        HEALTH_CRITICAL, PHONE_NOTIFICATION, SELF_IMPROVE_PROPOSAL

Thread-safe. Subscribers are called in the publisher's thread by default.
Pass async_dispatch=True to EventBus() to fire subscribers in daemon threads.
No external dependencies.

Usage:
    from event_bus import bus, Topic

    @bus.subscribe(Topic.SYSTEM_ALERT)
    def on_alert(payload):
        print(f"Alert: {payload['message']}")

    bus.publish(Topic.SYSTEM_ALERT, {"message": "Disk almost full", "severity": "high"})
"""

import threading
import datetime
import queue
from enum import Enum
from typing import Callable, Dict, List, Any
from config import get_logger
from errors import Result

log = get_logger("event_bus")


class Topic(str, Enum):
    SYSTEM_ALERT          = "system_alert"
    CALENDAR_REMINDER     = "calendar_reminder"
    EMAIL_ARRIVED         = "email_arrived"
    AGENT_DONE            = "agent_done"
    HEALTH_CRITICAL       = "health_critical"
    PHONE_NOTIFICATION    = "phone_notification"
    SELF_IMPROVE_PROPOSAL = "self_improve_proposal"
    WAKE                  = "wake"


class Event:
    __slots__ = ("topic", "payload", "timestamp", "source")

    def __init__(self, topic: Topic, payload: dict, source: str = "system"):
        self.topic = topic
        self.payload = payload
        self.timestamp = datetime.datetime.now().isoformat()
        self.source = source

    def __repr__(self):
        return f"Event({self.topic.value}, source={self.source}, ts={self.timestamp})"


class EventBus:
    """Thread-safe pub/sub event bus."""

    def __init__(self, async_dispatch: bool = False):
        self._subscribers: Dict[Topic, List[Callable]] = {t: [] for t in Topic}
        self._lock = threading.Lock()
        self._history: List[Event] = []
        self._max_history = 200
        self._async_dispatch = async_dispatch

    def subscribe(self, topic: Topic) -> Callable:
        """Decorator: register a callback for a topic."""
        def decorator(fn: Callable) -> Callable:
            with self._lock:
                self._subscribers[topic].append(fn)
            log.debug(f"Subscribed {fn.__name__} to {topic.value}")
            return fn
        return decorator

    def subscribe_fn(self, topic: Topic, fn: Callable):
        """Register a callback imperatively (non-decorator form)."""
        with self._lock:
            self._subscribers[topic].append(fn)
        log.debug(f"Subscribed {fn.__name__} to {topic.value}")

    def unsubscribe(self, topic: Topic, fn: Callable) -> bool:
        """Remove a subscriber. Returns True if found and removed."""
        with self._lock:
            subs = self._subscribers[topic]
            if fn in subs:
                subs.remove(fn)
                return True
        return False

    def publish(self, topic: Topic, payload: dict, source: str = "system") -> Result:
        """Fire all subscribers for a topic. Returns Result with subscriber count."""
        event = Event(topic, payload, source)

        with self._lock:
            handlers = list(self._subscribers[topic])
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        if not handlers:
            log.debug(f"No subscribers for {topic.value}")
            return Result.success(0)

        errors = []
        for handler in handlers:
            try:
                if self._async_dispatch:
                    t = threading.Thread(target=handler, args=(payload,), daemon=True)
                    t.start()
                else:
                    handler(payload)
            except Exception as e:
                log.error(f"Event handler {handler.__name__} failed for {topic.value}: {e}")
                errors.append(str(e))

        if errors:
            return Result.failure(f"{len(errors)} handler(s) failed: {errors[0]}", error_type="partial")
        return Result.success(len(handlers))

    def get_history(self, topic: Topic = None, limit: int = 20) -> List[Event]:
        """Get recent event history, optionally filtered by topic."""
        with self._lock:
            events = list(self._history)
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def subscriber_count(self, topic: Topic) -> int:
        with self._lock:
            return len(self._subscribers[topic])

    def clear_subscribers(self, topic: Topic = None):
        """Clear all subscribers for a topic (or all topics if None)."""
        with self._lock:
            if topic:
                self._subscribers[topic] = []
            else:
                for t in Topic:
                    self._subscribers[t] = []


# ──────────────────────────────────────────────
# Global singleton
# ──────────────────────────────────────────────
bus = EventBus(async_dispatch=True)


# ──────────────────────────────────────────────
# Convenience publishers
# ──────────────────────────────────────────────
def alert(message: str, severity: str = "medium", source: str = "system") -> Result:
    """Publish a SYSTEM_ALERT event."""
    return bus.publish(Topic.SYSTEM_ALERT, {
        "message": message, "severity": severity
    }, source=source)


def health_critical(check: str, detail: str, source: str = "validator") -> Result:
    """Publish a HEALTH_CRITICAL event."""
    return bus.publish(Topic.HEALTH_CRITICAL, {
        "check": check, "detail": detail
    }, source=source)


def agent_done(task_id: str, task: str, state: str, summary: str) -> Result:
    """Publish an AGENT_DONE event."""
    return bus.publish(Topic.AGENT_DONE, {
        "task_id": task_id, "task": task, "state": state, "summary": summary
    }, source="agent")


def calendar_reminder(event_title: str, start_time: str, minutes_until: int) -> Result:
    """Publish a CALENDAR_REMINDER event."""
    return bus.publish(Topic.CALENDAR_REMINDER, {
        "title": event_title, "start_time": start_time, "minutes_until": minutes_until
    }, source="calendar")


if __name__ == "__main__":
    import time

    received = []

    @bus.subscribe(Topic.SYSTEM_ALERT)
    def on_alert(payload):
        received.append(payload)
        print(f"[ALERT] {payload['message']} (severity={payload['severity']})")

    @bus.subscribe(Topic.HEALTH_CRITICAL)
    def on_critical(payload):
        print(f"[CRITICAL] {payload['check']}: {payload['detail']}")

    print("Testing event bus...")
    r = alert("Test alert", severity="low")
    print(f"Publish result: {r}")
    r = health_critical("disk", "Only 0.3 GB free")
    time.sleep(0.1)  # Let async threads complete

    history = bus.get_history(limit=5)
    print(f"\nEvent history ({len(history)} events):")
    for e in history:
        print(f"  {e}")

    print(f"\nReceived alerts: {received}")
