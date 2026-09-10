"""Authentication, session, and CSRF controls for configuration routes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import ip_address
from logging import getLogger
from math import ceil
from time import monotonic
from typing import Final, cast
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from argon2.low_level import Type
from starlette.datastructures import FormData, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apasz_hub import settings
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL

CONFIG_PATH: Final = "/config"
CONFIG_LOGIN_PATH: Final = f"{CONFIG_PATH}/login"
CONFIG_LOGOUT_PATH: Final = f"{CONFIG_PATH}/logout"
CONFIG_PASSWORD_HASH_ENV: Final = settings.CONFIG_PASSWORD_HASH_ENV
CONFIG_SESSION_SECRET_ENV: Final = settings.CONFIG_SESSION_SECRET_ENV
PUBLIC_ORIGIN_ENV: Final = settings.PUBLIC_ORIGIN_ENV
CONFIG_COOKIE_SECURE_ENV: Final = settings.CONFIG_COOKIE_SECURE_ENV
CONFIG_PASSWORD_FORM_NAME: Final = "password"
CONFIG_CSRF_FORM_NAME: Final = "config-csrf-token"
CONFIG_CSRF_HEADER: Final = "X-CSRF-Token"
FETCH_SITE_HEADER: Final = "Sec-Fetch-Site"
SAME_ORIGIN_FETCH_SITE: Final = "same-origin"
CONFIG_SESSION_STATE_KEY: Final = "apasz_hub.config_session"
CONFIG_SESSION_COOKIE_NAME: Final = "__Host-apasz-config-session"
INSECURE_CONFIG_SESSION_COOKIE_NAME: Final = "apasz-config-session"
CONFIG_SESSION_TOKEN_BYTES: Final = 32
CONFIG_SESSION_IDLE_SECONDS: Final = 30 * 60
CONFIG_SESSION_ABSOLUTE_SECONDS: Final = 8 * 60 * 60
MAX_DNS_NAME_LENGTH: Final = 253
MAX_DNS_LABEL_LENGTH: Final = 63
LOGIN_FAILURE_LIMIT: Final = 5
LOGIN_FAILURE_WINDOW_SECONDS: Final = 15 * 60
LOGIN_TRACKED_CLIENT_LIMIT: Final = 2_048
MAX_LOGIN_PASSWORD_LENGTH: Final = 1024
MAX_LOGGED_SOURCE_METADATA_LENGTH: Final = 256
SAFE_METHODS: Final = frozenset(("GET", "HEAD", "OPTIONS", "TRACE"))
LOOPBACK_HOSTS: Final = frozenset(("127.0.0.1", "::1", "localhost"))
LOGGER = getLogger(__name__)

CONFIG_PASSWORD_HASHER: Final = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    type=Type.ID,
)


class ConfigSecurityConfigurationError(ValueError):
    """Raised when configuration authentication settings are incomplete or unsafe."""


class LoginResult(StrEnum):
    """The possible outcomes from one configuration-login attempt."""

    AUTHENTICATED = "authenticated"
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class RequestSourceValidation(StrEnum):
    """The trust level of optional browser request-source metadata."""

    MISSING = "missing"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, slots=True)
class ConfigSecuritySettings:
    """Validated secret and deployment settings for configuration access."""

    password_hash: str = field(repr=False)
    session_secret: bytes = field(repr=False)
    public_origin: str
    cookie_secure: bool


@dataclass(frozen=True, slots=True)
class ConfigSession:
    """The small request-facing portion of an authenticated admin session."""

    csrf_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """The result of a login check, including an optional new session."""

    result: LoginResult
    settings: ConfigSecuritySettings | None = None
    session_id: str | None = field(default=None, repr=False)
    retry_after_seconds: int | None = None


@dataclass(slots=True)
class _StoredSession:
    """Server-side session state keyed by an HMAC of its browser token."""

    csrf_token: str = field(repr=False)
    idle_expires_at: float
    absolute_expires_at: float


@dataclass(slots=True)
class _LoginFailure:
    """A fixed-window login-failure counter for one direct client."""

    count: int
    expires_at: float


class _LoginRateLimiter:
    """Keep expensive password checks bounded after repeated failures."""

    def __init__(self) -> None:
        self._failures: dict[str, _LoginFailure] = {}

    def allow(self, client: str, now: float) -> tuple[bool, int | None]:
        """Return whether a client may attempt another password verification."""

        self._discard_expired(now)
        failure = self._failures.get(client)
        if failure is None:
            return True, None
        if failure.count < LOGIN_FAILURE_LIMIT:
            return True, None
        return False, max(1, ceil(failure.expires_at - now))

    def record_failure(self, client: str, now: float) -> None:
        """Record one failed password verification for a client."""

        self._discard_expired(now)
        failure = self._failures.get(client)
        if failure is None:
            self._discard_soonest_expiring_client_if_full()
            self._failures[client] = _LoginFailure(
                count=1,
                expires_at=now + LOGIN_FAILURE_WINDOW_SECONDS,
            )
            return
        failure.count += 1

    def clear(self, client: str) -> None:
        """Clear failures after a valid password verification."""

        self._failures.pop(client, None)

    def reset(self) -> None:
        """Forget counters when authentication configuration changes."""

        self._failures.clear()

    def _discard_expired(self, now: float) -> None:
        """Prevent expired failures from consuming the bounded tracker."""

        expired_clients = tuple(
            client
            for client, failure in self._failures.items()
            if failure.expires_at <= now
        )
        for client in expired_clients:
            del self._failures[client]

    def _discard_soonest_expiring_client_if_full(self) -> None:
        """Bound memory under a distributed failed-login flood."""

        if len(self._failures) < LOGIN_TRACKED_CLIENT_LIMIT:
            return
        client = min(
            self._failures,
            key=lambda candidate: self._failures[candidate].expires_at,
        )
        del self._failures[client]


class ConfigAccess:
    """Validate configuration credentials and hold short-lived server-side sessions."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._environment = environment
        self._clock = clock
        self._lock = threading.Lock()
        self._settings: ConfigSecuritySettings | None = None
        self._configuration_error: str | None = None
        self._sessions: dict[bytes, _StoredSession] = {}
        self._rate_limiter = _LoginRateLimiter()

    def settings(self) -> ConfigSecuritySettings | None:
        """Return validated settings, or ``None`` when access must stay closed."""

        with self._lock:
            return self._current_settings()

    def authenticate(self, session_id: str | None) -> ConfigSession | None:
        """Look up and refresh an unexpired session supplied by the browser."""

        if session_id is None or not _is_session_token(session_id):
            return None
        with self._lock:
            settings = self._current_settings()
            if settings is None:
                return None
            now = self._clock()
            self._discard_expired_sessions(now)
            key = _session_key(settings.session_secret, session_id)
            session = self._sessions.get(key)
            if session is None:
                return None
            session.idle_expires_at = min(
                now + CONFIG_SESSION_IDLE_SECONDS,
                session.absolute_expires_at,
            )
            return ConfigSession(csrf_token=session.csrf_token)

    def login(self, client: str, password: str) -> LoginOutcome:
        """Verify one password, rate-limit failures, and mint a new session."""

        with self._lock:
            settings = self._current_settings()
            if settings is None:
                return LoginOutcome(LoginResult.UNAVAILABLE)
            now = self._clock()
            allowed, retry_after_seconds = self._rate_limiter.allow(client, now)
            if not allowed:
                return LoginOutcome(
                    LoginResult.RATE_LIMITED,
                    settings=settings,
                    retry_after_seconds=retry_after_seconds,
                )

            if not _password_matches(settings.password_hash, password):
                self._rate_limiter.record_failure(client, now)
                return LoginOutcome(LoginResult.INVALID, settings=settings)

            self._rate_limiter.clear(client)
            self._discard_expired_sessions(now)
            session_id = secrets.token_urlsafe(CONFIG_SESSION_TOKEN_BYTES)
            self._sessions[_session_key(settings.session_secret, session_id)] = (
                _StoredSession(
                    csrf_token=secrets.token_urlsafe(CONFIG_SESSION_TOKEN_BYTES),
                    idle_expires_at=now + CONFIG_SESSION_IDLE_SECONDS,
                    absolute_expires_at=now + CONFIG_SESSION_ABSOLUTE_SECONDS,
                )
            )
            return LoginOutcome(
                LoginResult.AUTHENTICATED,
                settings=settings,
                session_id=session_id,
            )

    def logout(self, session_id: str | None) -> None:
        """Invalidate a browser session immediately when it is known."""

        if session_id is None or not _is_session_token(session_id):
            return
        with self._lock:
            settings = self._current_settings()
            if settings is not None:
                self._sessions.pop(
                    _session_key(settings.session_secret, session_id),
                    None,
                )

    def _current_settings(self) -> ConfigSecuritySettings | None:
        """Refresh environment-backed settings and revoke sessions after rotation."""

        try:
            settings = load_config_security_settings(self._environment)
            configuration_error = None
        except ConfigSecurityConfigurationError as error:
            settings = None
            configuration_error = str(error)
        if configuration_error != self._configuration_error:
            self._configuration_error = configuration_error
            if configuration_error is not None:
                LOGGER.error(
                    "Configuration access is disabled: %s", configuration_error
                )
        if settings != self._settings:
            self._settings = settings
            self._sessions.clear()
            self._rate_limiter.reset()
        return settings

    def _discard_expired_sessions(self, now: float) -> None:
        """Drop sessions that reached either their idle or absolute expiry."""

        expired_keys = tuple(
            key
            for key, session in self._sessions.items()
            if session.idle_expires_at <= now or session.absolute_expires_at <= now
        )
        for key in expired_keys:
            del self._sessions[key]


CONFIG_ACCESS = ConfigAccess()


class ConfigAccessMiddleware:
    """Require an authenticated session for every configuration resource."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if cast(str, scope["type"]) != "http" or not _is_config_path(scope):
            await self._app(scope, receive, send)
            return

        async def send_without_cache(message: Message) -> None:
            if cast(str, message["type"]) == "http.response.start":
                headers = MutableHeaders(
                    raw=cast(list[tuple[bytes, bytes]], message["headers"]),
                )
                headers["Cache-Control"] = NO_STORE_CACHE_CONTROL
            await send(message)

        settings = CONFIG_ACCESS.settings()
        if settings is None:
            await _send_response(
                PlainTextResponse(
                    "Configuration access is unavailable.",
                    status_code=503,
                ),
                scope,
                receive,
                send_without_cache,
            )
            return

        request = Request(scope, receive)
        method = cast(str, scope["method"])
        session = CONFIG_ACCESS.authenticate(
            request.cookies.get(_session_cookie_name(settings)),
        )
        if session is not None:
            _set_request_session(scope, session)

        request_source = _request_source_validation(request, settings)
        if (
            _is_unsafe_method(method)
            and request_source is RequestSourceValidation.UNTRUSTED
        ):
            _log_rejected_request_source(request)
            await _send_response(
                PlainTextResponse("Invalid configuration request.", status_code=403),
                scope,
                receive,
                send_without_cache,
            )
            return

        path = cast(str, scope["path"])
        if path == CONFIG_LOGIN_PATH:
            await self._app(scope, receive, send_without_cache)
            return

        if session is None:
            if method in SAFE_METHODS:
                await _send_response(
                    RedirectResponse(CONFIG_LOGIN_PATH, status_code=303),
                    scope,
                    receive,
                    send_without_cache,
                )
            else:
                await _send_response(
                    PlainTextResponse(
                        "Configuration authentication is required.",
                        status_code=401,
                    ),
                    scope,
                    receive,
                    send_without_cache,
                )
            return

        await self._app(scope, receive, send_without_cache)


def load_config_security_settings(
    environment: Mapping[str, str] | None = None,
) -> ConfigSecuritySettings | None:
    """Load the validated configuration-auth settings, or keep access closed."""

    try:
        application_settings = settings.load_settings(environment)
    except settings.SettingsValidationError as error:
        raise ConfigSecurityConfigurationError(str(error)) from error

    password_hash_secret = application_settings.config_password_hash
    session_secret_value = application_settings.config_session_secret
    if password_hash_secret is None and session_secret_value is None:
        return None
    if password_hash_secret is None or session_secret_value is None:
        raise ConfigSecurityConfigurationError(
            "CONFIG_PASSWORD_HASH and CONFIG_SESSION_SECRET must be supplied together."
        )

    password_hash = password_hash_secret.get_secret_value()
    session_secret = session_secret_value.get_secret_value()
    if not password_hash.startswith("$argon2id$"):
        raise ConfigSecurityConfigurationError(
            "Configuration password hash must use Argon2id."
        )
    try:
        CONFIG_PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (Argon2Error, InvalidHashError) as error:
        raise ConfigSecurityConfigurationError(
            "Configuration password hash is not a valid Argon2 hash."
        ) from error
    normalised_origin = _normalise_origin(application_settings.public_origin)
    cookie_secure = application_settings.config_cookie_secure
    _validate_cookie_transport(normalised_origin, cookie_secure)
    return ConfigSecuritySettings(
        password_hash=password_hash,
        session_secret=_decode_session_secret(session_secret),
        public_origin=normalised_origin,
        cookie_secure=cookie_secure,
    )


async def configuration_form(request: Request) -> FormData:
    """Read a CSRF-protected form from an authenticated configuration request."""

    session = session_from_request(request)
    form = await request.form()
    form_token = form.get(CONFIG_CSRF_FORM_NAME)
    header_token = request.headers.get(CONFIG_CSRF_HEADER)
    if not isinstance(form_token, str) or not _tokens_match(
        session.csrf_token,
        form_token,
    ):
        raise HTTPException(status_code=403, detail="Invalid configuration request.")
    if header_token is not None and not _tokens_match(
        session.csrf_token,
        header_token,
    ):
        raise HTTPException(status_code=403, detail="Invalid configuration request.")
    return form


def session_from_request(request: Request) -> ConfigSession:
    """Return middleware-authenticated session state or fail closed."""

    state = request.scope.get("state")
    if not isinstance(state, dict):
        raise HTTPException(
            status_code=401, detail="Configuration authentication required."
        )
    state_values = cast(dict[str, object], state)
    session = state_values.get(CONFIG_SESSION_STATE_KEY)
    if not isinstance(session, ConfigSession):
        raise HTTPException(
            status_code=401, detail="Configuration authentication required."
        )
    return session


def configuration_client(request: Request) -> str:
    """Return the direct peer identity used for local login throttling."""

    client = request.client
    return "unknown" if client is None else client.host


def set_configuration_session_cookie(
    response: Response,
    outcome: LoginOutcome,
) -> None:
    """Attach the authenticated session cookie to a successful login response."""

    if (
        outcome.result is not LoginResult.AUTHENTICATED
        or outcome.settings is None
        or outcome.session_id is None
    ):
        raise ValueError(
            "Only an authenticated login outcome can set a session cookie."
        )
    response.set_cookie(
        key=_session_cookie_name(outcome.settings),
        value=outcome.session_id,
        max_age=CONFIG_SESSION_ABSOLUTE_SECONDS,
        path="/",
        secure=outcome.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_configuration_session_cookie(
    response: Response,
    settings: ConfigSecuritySettings,
) -> None:
    """Expire the current deployment's configuration-session cookie."""

    response.delete_cookie(
        key=_session_cookie_name(settings),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def configuration_session_cookie_name(settings: ConfigSecuritySettings) -> str:
    """Return the cookie name used by the active deployment configuration."""

    return _session_cookie_name(settings)


def _decode_session_secret(value: str) -> bytes:
    """Decode a URL-safe base64 secret with at least 256 bits of entropy."""

    unpadded_value = value.rstrip("=")
    if (
        not unpadded_value
        or len(value) - len(unpadded_value) > 2
        or not all(
            character.isascii() and (character.isalnum() or character in "-_")
            for character in unpadded_value
        )
    ):
        raise ConfigSecurityConfigurationError(
            "Configuration session secret must be URL-safe base64."
        )
    try:
        encoded = value.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        secret = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ConfigSecurityConfigurationError(
            "Configuration session secret must be URL-safe base64."
        ) from error
    if len(secret) < CONFIG_SESSION_TOKEN_BYTES:
        raise ConfigSecurityConfigurationError(
            "Configuration session secret must contain at least 32 bytes."
        )
    return secret


def _normalise_origin(value: str) -> str:
    """Validate and canonicalise one exact browser origin for CSRF checks."""

    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ConfigSecurityConfigurationError(
            "Configuration public origin is invalid."
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as error:
        raise ConfigSecurityConfigurationError(
            "Configuration public origin is invalid."
        ) from error
    scheme = parsed.scheme.casefold()
    if (
        scheme not in {"http", "https"}
        or hostname is None
        or parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigSecurityConfigurationError(
            "Configuration public origin must be an http or https origin only."
        )
    host = _normalise_hostname(hostname)
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def _normalise_hostname(hostname: str) -> str:
    """Return a canonical IP address or a valid IDNA DNS hostname."""

    if "%" in hostname:
        raise ConfigSecurityConfigurationError(
            "Configuration public origin is invalid."
        )
    try:
        return ip_address(hostname).compressed
    except ValueError:
        pass
    try:
        host = hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise ConfigSecurityConfigurationError(
            "Configuration public origin is invalid."
        ) from error
    if not _is_dns_hostname(host):
        raise ConfigSecurityConfigurationError(
            "Configuration public origin is invalid."
        )
    return host


def _is_dns_hostname(value: str) -> bool:
    """Whether an ASCII hostname is a conventional DNS name."""

    return len(value) <= MAX_DNS_NAME_LENGTH and all(
        _is_dns_label(label) for label in value.split(".")
    )


def _is_dns_label(value: str) -> bool:
    """Whether one DNS label is within the hostname grammar."""

    return (
        0 < len(value) <= MAX_DNS_LABEL_LENGTH
        and value[0].isalnum()
        and value[-1].isalnum()
        and all(
            character.isascii() and (character.isalnum() or character == "-")
            for character in value
        )
    )


def _validate_cookie_transport(origin: str, cookie_secure: bool) -> None:
    """Allow insecure development cookies only over an explicit loopback origin."""

    parsed = urlsplit(origin)
    if cookie_secure and parsed.scheme == "https":
        return
    if (
        not cookie_secure
        and parsed.scheme == "http"
        and parsed.hostname in LOOPBACK_HOSTS
    ):
        return
    raise ConfigSecurityConfigurationError(
        "Configuration cookies must use HTTPS unless local loopback development "
        "explicitly disables them."
    )


def _password_matches(password_hash: str, password: str) -> bool:
    """Verify a bounded supplied password against the configured Argon2id hash."""

    if len(password) > MAX_LOGIN_PASSWORD_LENGTH:
        return False
    try:
        return CONFIG_PASSWORD_HASHER.verify(password_hash, password)
    except Argon2Error, InvalidHashError:
        return False


def _session_key(secret: bytes, session_id: str) -> bytes:
    """Return a server-only index for an opaque browser session identifier."""

    return hmac.new(secret, session_id.encode("ascii"), hashlib.sha256).digest()


def _is_session_token(value: str) -> bool:
    """Whether a cookie value has the expected URL-safe opaque-token shape."""

    return (
        CONFIG_SESSION_TOKEN_BYTES <= len(value) <= 128
        and value.isascii()
        and all(character.isalnum() or character in "-_" for character in value)
    )


def _session_cookie_name(settings: ConfigSecuritySettings) -> str:
    """Use a host-prefixed cookie whenever HTTPS-only operation is enabled."""

    return (
        CONFIG_SESSION_COOKIE_NAME
        if settings.cookie_secure
        else INSECURE_CONFIG_SESSION_COOKIE_NAME
    )


def _tokens_match(expected: str, supplied: str) -> bool:
    """Compare CSRF values without a content-dependent early exit."""

    return hmac.compare_digest(expected.encode(), supplied.encode())


def _is_config_path(scope: Scope) -> bool:
    """Return whether an HTTP request targets the configuration route subtree."""

    path = cast(str, scope["path"])
    return path == CONFIG_PATH or path.startswith(f"{CONFIG_PATH}/")


def _is_unsafe_method(method: str) -> bool:
    """Return whether an HTTP method needs browser-origin validation."""

    return method.upper() not in SAFE_METHODS


def _request_source_validation(
    request: Request,
    settings: ConfigSecuritySettings,
) -> RequestSourceValidation:
    """Classify Origin and optional browser-controlled Fetch Metadata."""

    origin = request.headers.get("origin")
    fetch_site = request.headers.get(FETCH_SITE_HEADER)
    if origin is None:
        return _fetch_site_validation(fetch_site)
    if origin == "null":
        fetch_validation = _fetch_site_validation(fetch_site)
        return (
            RequestSourceValidation.UNTRUSTED
            if fetch_validation is RequestSourceValidation.MISSING
            else fetch_validation
        )
    try:
        if not hmac.compare_digest(
            _normalise_origin(origin),
            settings.public_origin,
        ):
            return RequestSourceValidation.UNTRUSTED
    except ConfigSecurityConfigurationError:
        return RequestSourceValidation.UNTRUSTED

    if fetch_site is None:
        return RequestSourceValidation.TRUSTED
    return _fetch_site_validation(fetch_site)


def _fetch_site_validation(fetch_site: str | None) -> RequestSourceValidation:
    """Classify optional Fetch Metadata while permitting an absent header."""

    if fetch_site is None:
        return RequestSourceValidation.MISSING
    if hmac.compare_digest(fetch_site.casefold(), SAME_ORIGIN_FETCH_SITE):
        return RequestSourceValidation.TRUSTED
    return RequestSourceValidation.UNTRUSTED


def _log_rejected_request_source(request: Request) -> None:
    """Record bounded source metadata without exposing form data or cookies."""

    LOGGER.warning(
        "Rejected configuration request source metadata: origin=%r, sec_fetch_site=%r.",
        _bounded_source_metadata(request.headers.get("origin")),
        _bounded_source_metadata(request.headers.get(FETCH_SITE_HEADER)),
    )


def _bounded_source_metadata(value: str | None) -> str | None:
    """Bound a client-controlled source field before including it in a log entry."""

    if value is None or len(value) <= MAX_LOGGED_SOURCE_METADATA_LENGTH:
        return value
    return f"{value[:MAX_LOGGED_SOURCE_METADATA_LENGTH - 1]}…"


def _set_request_session(scope: Scope, session: ConfigSession) -> None:
    """Attach authenticated state for the downstream route handler."""

    state = cast(dict[str, object], scope.setdefault("state", {}))
    state[CONFIG_SESSION_STATE_KEY] = session


async def _send_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """Render a short-circuit middleware response through the configured sender."""

    await response(scope, receive, send)
