"""로그인 실패 횟수 제한.

uvicorn 워커가 1개라 메모리에 기록해도 충분하다 (재시작하면 초기화).
"""

import time
from collections import defaultdict, deque


class LoginLimiter:
    def __init__(self, window_seconds: int = 15 * 60):
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> deque[float]:
        q = self._failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked_for(self, key: str, limit: int) -> int:
        """막혀 있으면 남은 초, 아니면 0."""
        q = self._recent(key)
        if len(q) < limit:
            return 0
        return max(1, int(q[-limit] + self.window - time.monotonic()))

    def fail(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_limiter = LoginLimiter()

# 아이디별 5회, 접속 IP별 20회 (15분 기준)
USER_LIMIT = 5
IP_LIMIT = 20
