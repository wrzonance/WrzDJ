"""Login lockout logic with escalating cooldowns.

NOTE: LockoutManager uses an in-memory dict protected by threading.Lock.
In a multi-worker deployment each process would hold its own independent
lockout state, so an attacker could bypass lockouts by hitting different
workers. The API therefore runs as exactly one worker (pinned in
``scripts/start.sh``); a shared store (Redis / DB) must replace this dict
before that pin is raised. State is also lost on restart.
"""

import time
from dataclasses import dataclass
from threading import Lock


@dataclass
class FailedAttempt:
    """Track failed login attempts for a key."""

    count: int = 0
    first_failure: float = 0.0
    lockout_until: float = 0.0


class LockoutManager:
    """Track failed login attempts and manage lockouts.

    Escalation policy:
    - 5 failures: 5 minute lockout
    - 10 failures: 30 minute lockout
    """

    THRESHOLD_1 = 5
    LOCKOUT_1_SECONDS = 5 * 60  # 5 minutes

    THRESHOLD_2 = 10
    LOCKOUT_2_SECONDS = 30 * 60  # 30 minutes

    # Clean up entries older than 1 hour
    CLEANUP_INTERVAL = 60 * 60

    def __init__(self) -> None:
        self._attempts: dict[str, FailedAttempt] = {}
        self._lock = Lock()
        self._last_cleanup = time.time()

    def _make_key(self, ip: str | None, username: str | None) -> str:
        """Create a composite key from IP and username."""
        # Track by both IP and username to prevent:
        # - One IP trying many usernames
        # - One username being tried from many IPs
        parts = []
        if ip:
            parts.append(f"ip:{ip}")
        if username:
            parts.append(f"user:{username.lower()}")
        return "|".join(parts) if parts else "unknown"

    def _cleanup_old_entries(self) -> None:
        """Remove expired lockout entries."""
        now = time.time()
        if now - self._last_cleanup < 60:  # Only cleanup every minute
            return

        self._last_cleanup = now
        expired_keys = []
        for key, attempt in self._attempts.items():
            # Remove if lockout expired and no recent failures
            expired = attempt.lockout_until < now
            old = (now - attempt.first_failure) > self.CLEANUP_INTERVAL
            if expired and old:
                expired_keys.append(key)

        for key in expired_keys:
            del self._attempts[key]

    def is_locked_out(self, ip: str | None, username: str | None) -> tuple[bool, int]:
        """Check if a key is currently locked out.

        Returns:
            Tuple of (is_locked, seconds_remaining)
        """
        with self._lock:
            self._cleanup_old_entries()

            # Check both IP-based and username-based lockouts
            keys_to_check = []
            if ip:
                keys_to_check.append(f"ip:{ip}")
            if username:
                keys_to_check.append(f"user:{username.lower()}")

            now = time.time()
            max_remaining = 0

            for key in keys_to_check:
                attempt = self._attempts.get(key)
                if attempt and attempt.lockout_until > now:
                    remaining = int(attempt.lockout_until - now)
                    max_remaining = max(max_remaining, remaining)

            return (max_remaining > 0, max_remaining)

    def record_failure(self, ip: str | None, username: str | None) -> tuple[bool, int]:
        """Record a failed login attempt.

        Returns:
            Tuple of (is_now_locked, lockout_seconds)
        """
        with self._lock:
            now = time.time()
            keys_to_update = []
            if ip:
                keys_to_update.append(f"ip:{ip}")
            if username:
                keys_to_update.append(f"user:{username.lower()}")

            lockout_seconds = 0

            for key in keys_to_update:
                if key not in self._attempts:
                    self._attempts[key] = FailedAttempt(
                        count=1,
                        first_failure=now,
                        lockout_until=0.0,
                    )
                else:
                    attempt = self._attempts[key]
                    # Reset if lockout has expired
                    if attempt.lockout_until > 0 and attempt.lockout_until < now:
                        attempt.count = 1
                        attempt.first_failure = now
                        attempt.lockout_until = 0.0
                    else:
                        attempt.count += 1

                    # Check thresholds
                    if attempt.count >= self.THRESHOLD_2:
                        attempt.lockout_until = now + self.LOCKOUT_2_SECONDS
                        lockout_seconds = max(lockout_seconds, self.LOCKOUT_2_SECONDS)
                    elif attempt.count >= self.THRESHOLD_1:
                        attempt.lockout_until = now + self.LOCKOUT_1_SECONDS
                        lockout_seconds = max(lockout_seconds, self.LOCKOUT_1_SECONDS)

            return (lockout_seconds > 0, lockout_seconds)

    def record_success(self, ip: str | None, username: str | None) -> None:
        """Clear lockout state after successful login."""
        with self._lock:
            keys_to_clear = []
            if ip:
                keys_to_clear.append(f"ip:{ip}")
            if username:
                keys_to_clear.append(f"user:{username.lower()}")

            for key in keys_to_clear:
                if key in self._attempts:
                    del self._attempts[key]


# Global lockout manager instance
lockout_manager = LockoutManager()
