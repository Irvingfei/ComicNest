"""Platform authentication and identity.

The TOS proxy injects the session and CSRF cookies. Following the iframe
contract used by MarkNest, the WebUI copies them into the headers the platform
expects. Identity comes from the ``tos_current_username`` cookie or the
``X-ComicNest-User`` header; it is client-supplied, which is a platform property
rather than something this application can prove.
"""

import http.client
import re
import unicodedata
import urllib.parse
from http.cookies import SimpleCookie

from .config import config
from .errors import AuthRequired, Forbidden, IdentityRequired
from .logging_setup import get_logger

log = get_logger("auth")

SESSION_COOKIE = "TMSESSNAME"
CSRF_COOKIE = "X-Csrf-Token"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=\-]{8,256}$")
_USER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_cookie_header(raw):
    result = {}
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip().strip('"')
    return result


def _cookie_value(headers, name):
    custom = parse_cookie_header(headers.get("Cookie") or "")
    if custom.get(name):
        return custom[name]
    parsed = SimpleCookie()
    try:
        parsed.load(headers.get("Cookie") or "")
    except Exception:
        return ""
    morsel = parsed.get(name)
    return morsel.value if morsel else ""


def verify(headers):
    """Validate the platform session, or raise :class:`AuthRequired`."""
    if not config.require_auth:
        return {"session": "", "token": "", "enforced": False}

    custom = parse_cookie_header(headers.get("Cookie") or "")
    parsed = SimpleCookie()
    try:
        parsed.load(headers.get("Cookie") or "")
    except Exception:
        parsed = SimpleCookie()

    session = custom.get(SESSION_COOKIE) or (parsed.get(SESSION_COOKIE).value if parsed.get(SESSION_COOKIE) else "")
    cookie_token = custom.get(CSRF_COOKIE) or (parsed.get(CSRF_COOKIE).value if parsed.get(CSRF_COOKIE) else "")
    header_token = (headers.get("X-Csrf-Token") or "").strip()
    token = header_token or cookie_token

    if not session or not token:
        raise AuthRequired("missing platform session credentials")
    if not _SAFE_TOKEN.match(token):
        raise AuthRequired("malformed CSRF token")
    if cookie_token and cookie_token != header_token:
        raise AuthRequired("CSRF token mismatch")
    if config.env_verify_url and not _verify_remote(config.env_verify_url, session, token):
        raise AuthRequired("platform session is no longer valid")
    return {"session": session, "token": token, "enforced": True}


def _verify_remote(url, session, token):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return True
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    try:
        connection = connection_class(parsed.hostname, port, timeout=5)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "application/json",
                    "X-Csrf-Token": token,
                    "Cookie": "%s=%s; %s=%s" % (SESSION_COOKIE, session, CSRF_COOKIE, token),
                },
            )
            response = connection.getresponse()
            response.read()
            return response.status < 400
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return True


def claimed_user(headers):
    if config.user_header:
        claimed = (headers.get(config.user_header) or "").strip()
        if claimed:
            return claimed
    return _cookie_value(headers, config.user_cookie)


def resolve_identity(headers):
    name = claimed_user(headers)
    if not name and not config.require_auth:
        return "tester"
    if not name:
        raise IdentityRequired("your TOS user could not be determined")
    name = unicodedata.normalize("NFC", name)
    if not _USER_NAME.match(name) or name in (".", ".."):
        raise IdentityRequired("the TOS user name is not usable")
    if config.require_system_user:
        _require_system_user(name)
    return name


def _require_system_user(name):
    try:
        import pwd  # type: ignore
    except ImportError:
        return
    try:
        pwd.getpwnam(name)
    except KeyError:
        raise IdentityRequired("no such TOS user")
    except OSError as exc:
        raise IdentityRequired("the TOS user could not be verified: %s" % exc)


def is_admin(name):
    if not config.require_auth:
        return True
    if name in config.admin_users:
        return True
    try:
        import grp  # type: ignore
        import pwd  # type: ignore
        import os
    except ImportError:
        return False
    try:
        entry = pwd.getpwnam(name)
        groups = set(os.getgrouplist(name, entry.pw_gid))
        for gid in groups:
            try:
                group = grp.getgrgid(gid)
            except KeyError:
                continue
            if group.gr_name in config.admin_groups:
                return True
    except (KeyError, OSError):
        return False
    return False


def require_admin(name):
    if not is_admin(name):
        raise Forbidden("only a TOS administrator can change sources")


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "same-origin",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Csrf-Token, Cookie, X-ComicNest-User",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin, Access-Control-Request-Headers",
    }
