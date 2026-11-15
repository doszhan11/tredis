import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tredis.ai import AI  # noqa: E402
from tredis.config import Config  # noqa: E402
from tredis.service import Service  # noqa: E402
from tests.fakes import FakeAnthropic, FakeDB  # noqa: E402

TZ = ZoneInfo("Asia/Almaty")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=TZ)


class Clock:
    def __init__(self, now):
        self.now = now


class Env:
    def __init__(self, *responses, budget=50.0, error=None, free=3, test_mode=False):
        self.cfg = Config(admin_ids=frozenset({111}), payment_contact="@tredis_pay",
                          monthly_budget_usd=budget, free_msgs_day=free, test_mode=test_mode)
        self.db = FakeDB()
        self.db.today = NOW.astimezone(timezone.utc).date()
        self.client = FakeAnthropic(*responses, error=error)
        self.notified = []
        self.clock = Clock(NOW)

        async def notify(text):
            self.notified.append(text)

        self.ai = AI(self.client, self.cfg, self.db, notify)
        self.svc = Service(self.db, self.ai, self.cfg)
        self.svc.now = lambda: self.clock.now


@pytest.fixture
def env():
    return Env()


@pytest.fixture
def make_env():
    return Env
