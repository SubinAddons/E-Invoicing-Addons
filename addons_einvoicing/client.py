"""Bounded HTTP client. Write failures with ambiguous outcomes are never retried here."""
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from addons_einvoicing.domain import signature

SANDBOX = "https://api-sandbox.ae.ardentaxit.tax"
MAX_RESPONSE = 16 * 1024 * 1024


class APIError(Exception):
    def __init__(self, message, status=0, uncertain=False, retry_after=60, detail=None):
        super().__init__(message)
        self.status, self.uncertain, self.retry_after = status, uncertain, retry_after
        self.detail = detail or {}


def validate_base_url(value, environment):
    url = urlparse(value)
    if url.scheme != "https" or url.username or url.password or url.port not in {None, 443} or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("API base must be an HTTPS origin without path, credentials, query or custom port")
    if environment == "Sandbox":
        if value.rstrip("/") != SANDBOX:
            raise ValueError("Sandbox must use the documented sandbox API origin")
    elif environment == "Production":
        if not url.hostname or not url.hostname.endswith(".ae.ardentaxit.tax") or url.hostname in {"docs.ae.ardentaxit.tax", "app.ae.ardentaxit.tax", "api-sandbox.ae.ardentaxit.tax"}:
            raise ValueError("Enter the production API origin confirmed by ArdentaxIT")
    else:
        raise ValueError("Unknown environment")
    return value.rstrip("/")


def expiry_seconds(value):
    if isinstance(value, (float, int)):
        timestamp = value / 1000 if value > 100_000_000_000 else value
    else:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if not date.tzinfo:
            date = date.replace(tzinfo=timezone.utc)
        timestamp = date.timestamp()
    return max(0, int(timestamp - time.time() - 60))


class Client:
    def __init__(self, connection, cache, session=None):
        self.connection = connection
        self.cache = cache
        self.base = validate_base_url(connection.api_base_url, connection.environment)
        self.session = session or requests.Session()
        self.secret = connection.get_password("client_secret")
        self.identity = hashlib.sha256(f"{self.base}|{connection.client_id}".encode()).hexdigest()
        # Secret rotation invalidates old tokens without exposing the secret in cache keys.
        self.token_key = "ardentax:token:" + hashlib.sha256(f"{self.identity}|{self.secret}".encode()).hexdigest()

    def _http(self, method, path, headers, params=None, payload=None):
        write = method in {"POST", "PUT"}
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Relative API path required")
        try:
            with self.session.request(method, self.base + path, params=params, json=payload,
                                      headers=headers, timeout=(10, 40), allow_redirects=False,
                                      stream=True) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise APIError("Response exceeded 16 MB", uncertain=write)
                    chunks.append(chunk)
                body = b"".join(chunks)
                if not 200 <= response.status_code < 300:
                    code = response.status_code
                    try:
                        delay = max(1, min(3600, int(response.headers.get("Retry-After", "60"))))
                    except ValueError:
                        delay = 60
                    # Preserve only validation errors in the protected audit record, never headers/tokens.
                    detail = {}
                    if code in {400, 422}:
                        try:
                            detail = json.loads(body).get("errors", {})
                        except (ValueError, AttributeError):
                            pass
                    raise APIError(f"ArdentaxIT returned HTTP {code}", code,
                                   uncertain=write and code not in {400, 401, 403, 413, 422, 429},
                                   retry_after=delay, detail=detail)
                return body, response.headers.get("Content-Type", "")
        except requests.RequestException as exc:
            # Requests exception strings may contain URLs/credentials. Do not propagate them.
            raise APIError("ArdentaxIT connection failed or timed out", uncertain=write) from None

    def token(self, refresh=False):
        if refresh:
            self.cache.delete_value(self.token_key)
        cached = self.cache.get_value(self.token_key)
        if cached:
            return cached
        with self.cache.lock(self.token_key + ":lock", timeout=60, blocking_timeout=2):
            cached = self.cache.get_value(self.token_key)
            if cached:
                return cached
            headers = {"X-HMAC-Signature": signature(self.secret, self.connection.client_id.encode()),
                       "X-API-Version": self.connection.api_version}
            body, _ = self._http("GET", "/auth/token", headers, {"client_id": self.connection.client_id})
            try:
                data = json.loads(body)
                token = data.get("token") or data.get("access_token")
                ttl = expiry_seconds(data["expires_at"]) if data.get("expires_at") is not None else min(86400, int(data["expires_in"]) - 60)
                if not isinstance(token, str) or not token or ttl <= 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise APIError("Unexpected token response; expected token and valid expires_at or expires_in") from None
            self.cache.set_value(self.token_key, token, expires_in_sec=ttl)
            return token

    def _reserve(self, path):
        # Coordinate all workers/connections sharing this account, conservatively below 60/min.
        family = path.split("/")[2] if path.startswith("/api/") else "auth"
        bucket = f"ardentax:rate:{self.identity}:{family}:{int(time.time() // 60)}"
        with self.cache.lock(bucket + ":lock", timeout=5, blocking_timeout=2):
            used = int(self.cache.get_value(bucket) or 0)
            if used >= 45:
                raise APIError("Local account throttle; retry later", 429, retry_after=65)
            self.cache.set_value(bucket, used + 1, expires_in_sec=120)

    def request(self, method, path, payload=None, params=None, binary=False):
        for attempt in range(2):
            token = self.token(refresh=attempt == 1)
            self._reserve(path)
            try:
                body, content_type = self._http(method, path,
                    {"Authorization": f"Bearer {token}", "X-API-Version": self.connection.api_version,
                     "Content-Type": "application/json"}, params, payload)
            except APIError as exc:
                if exc.status == 401 and attempt == 0:
                    continue
                raise
            if binary:
                return body, content_type
            try:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError()
                return data
            except ValueError:
                raise APIError("Unexpected API response body", uncertain=method in {"POST", "PUT"}) from None

