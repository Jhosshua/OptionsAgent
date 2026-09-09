"""Keep the entire suite offline, even when run inside a configured service."""
from urllib.parse import urlparse

import pytest
import requests

# Load dotenv before fixtures clear inherited production notification credentials.
from harness import env as _environment  # noqa: F401


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch):
    for key in ('DISCORD_WEBHOOK_URL', 'NOTIFY_DISCORD_TOKEN', 'NOTIFY_DISCORD_CHANNEL'):
        monkeypatch.delenv(key, raising=False)
    original = requests.sessions.Session.request

    def offline_request(self, method, url, *args, **kwargs):
        if urlparse(str(url)).hostname not in ('127.0.0.1', 'localhost', '::1'):
            pytest.fail('Unit test attempted an external HTTP request; install a fake adapter')
        return original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, 'request', offline_request)
