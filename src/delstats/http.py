from __future__ import annotations

import time
from typing import Any

import requests


class DelHttpError(RuntimeError):
    pass


class DelHttpClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        backoff_seconds: float = 0.75,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "del-event-lab/0.1 (+private research project)"
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise DelHttpError(
                        f"Temporary HTTP {response.status_code} for {url}"
                    )
                return response
            except (requests.RequestException, DelHttpError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.backoff_seconds * (2**attempt))

        raise DelHttpError(f"Request failed for {url}: {last_error}")

    def get_json(self, url: str) -> Any:
        response = self.get(url)
        if response.status_code != 200:
            raise DelHttpError(f"HTTP {response.status_code} for {url}")
        try:
            return response.json()
        except ValueError as exc:
            raise DelHttpError(f"Invalid JSON from {url}") from exc
