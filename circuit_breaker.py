"""
EDITH Circuit Breaker — Phase 4.7

Checks health of Ollama, SearXNG, and cloud providers BEFORE firing agents.
Per-service state: CLOSED (healthy) / OPEN (broken) / HALF_OPEN (testing).
Exponential backoff with jitter for recovery.
"""

import time
import random
import threading
import requests
from config import get_logger, OLLAMA_URL

log = get_logger("circuit_breaker")

# States
CLOSED = "CLOSED"      # Service healthy, allow requests
OPEN = "OPEN"          # Service broken, reject requests
HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreaker:
    """Per-service circuit breaker with exponential backoff."""

    def __init__(self, name: str, failure_threshold: int = 3,
                 recovery_timeout: float = 60.0, max_backoff: float = 300.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.max_backoff = max_backoff

        self.state = CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.backoff_multiplier = 1
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if service is available for requests."""
        with self._lock:
            if self.state == CLOSED:
                return True
            elif self.state == OPEN:
                elapsed = time.time() - self.last_failure_time
                timeout = min(self.recovery_timeout * self.backoff_multiplier, self.max_backoff)
                # Add jitter
                timeout += random.uniform(0, timeout * 0.1)
                if elapsed >= timeout:
                    self.state = HALF_OPEN
                    log.info(f"Circuit {self.name}: OPEN → HALF_OPEN (testing)")
                    return True
                return False
            elif self.state == HALF_OPEN:
                return True
            return False

    def record_success(self):
        """Record a successful request."""
        with self._lock:
            if self.state == HALF_OPEN:
                log.info(f"Circuit {self.name}: HALF_OPEN → CLOSED (recovered)")
            self.state = CLOSED
            self.failure_count = 0
            self.backoff_multiplier = 1

    def record_failure(self):
        """Record a failed request."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                if self.state != OPEN:
                    log.warning(f"Circuit {self.name}: → OPEN (failures: {self.failure_count})")
                self.state = OPEN
                self.backoff_multiplier = min(self.backoff_multiplier * 2, 10)

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failure_count,
            "backoff": self.backoff_multiplier,
        }


# Global circuit breakers
_breakers = {
    "ollama": CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30),
    "searxng": CircuitBreaker("searxng", failure_threshold=2, recovery_timeout=60),
    "groq": CircuitBreaker("groq", failure_threshold=3, recovery_timeout=120),
    "gemini": CircuitBreaker("gemini", failure_threshold=3, recovery_timeout=120),
    "nvidia": CircuitBreaker("nvidia", failure_threshold=3, recovery_timeout=120),
    "openrouter": CircuitBreaker("openrouter", failure_threshold=3, recovery_timeout=120),
}
_breakers_lock = threading.Lock()  # Protects _breakers dict from TOCTOU on get_breaker()


def get_breaker(service: str) -> CircuitBreaker:
    """Get or create a circuit breaker for a service. Thread-safe."""
    if service not in _breakers:
        with _breakers_lock:
            if service not in _breakers:
                _breakers[service] = CircuitBreaker(service)
    return _breakers[service]


def is_service_available(service: str) -> bool:
    """Check if a service is available."""
    return get_breaker(service).is_available()


def record_success(service: str):
    get_breaker(service).record_success()


def record_failure(service: str):
    get_breaker(service).record_failure()


from errors import Result

def check_ollama_health() -> Result:
    """Ping Ollama to check if it's responsive."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            record_success("ollama")
            return Result.success()
    except Exception as e:
        record_failure("ollama")
        return Result.from_exception(e)
    record_failure("ollama")
    return Result.failure("Bad status code")


def check_searxng_health() -> Result:
    """Ping SearXNG to check if it's responsive."""
    try:
        r = requests.get("http://localhost:8080/search?q=test", timeout=3)
        if r.status_code == 200:
            record_success("searxng")
            return Result.success()
    except Exception as e:
        record_failure("searxng")
        return Result.from_exception(e)
    record_failure("searxng")
    return Result.failure("Bad status code")


def get_all_status() -> dict:
    """Get status of all circuit breakers."""
    with _breakers_lock:
        snapshot = dict(_breakers)
    return {name: b.get_status() for name, b in snapshot.items()}


def pre_flight_check() -> dict:
    """Run pre-flight health checks before agent dispatch.

    Returns dict with service availability.
    """
    res = check_ollama_health()
    is_ok = res.ok if isinstance(res, Result) else res
    results = {
        "ollama": is_ok,
        "timestamp": time.time(),
    }
    log.info(f"Pre-flight: ollama={'OK' if results['ollama'] else 'DOWN'}")
    return results


if __name__ == "__main__":
    print("Circuit Breaker Status:")
    pf = pre_flight_check()
    print(f"  Ollama: {'OK' if pf['ollama'] else 'DOWN'}")
    for name, status in get_all_status().items():
        print(f"  {name}: {status['state']} (failures: {status['failures']})")
