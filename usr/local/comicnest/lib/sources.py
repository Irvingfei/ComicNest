"""Local and remote storage backends.

Every backend exposes the same small surface: list a directory, stat an entry,
read bytes, and download a file. Relative paths always use ``/`` and never start
with one; the scanner only ever asks for paths it discovered itself.
"""

import base64
import email.utils
import os
import posixpath
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

from . import secretstore as secrets
from .config import config
from .errors import (
    RemoteAuthFailed,
    RemoteUnavailable,
    SourceDenied,
    SourceInvalid,
    SourceUnavailable,
)
from .logging_setup import get_logger

log = get_logger("sources")

_DAV_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:"><d:prop>'
    b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/>"
    b"<d:getcontenttype/></d:prop></d:propfind>"
)
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class Entry:
    __slots__ = ("name", "is_dir", "size", "mtime")

    def __init__(self, name, is_dir=False, size=0, mtime=0.0):
        self.name = name
        self.is_dir = bool(is_dir)
        self.size = int(size or 0)
        self.mtime = float(mtime or 0)

    def __repr__(self):
        return "Entry(%r, dir=%r, size=%r)" % (self.name, self.is_dir, self.size)


def clean_rel(rel):
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        return ""
    pieces = []
    for piece in rel.split("/"):
        if piece in ("", "."):
            continue
        if piece == ".." or "\x00" in piece:
            raise SourceDenied("the path is outside the source")
        pieces.append(piece)
    return "/".join(pieces)


class LocalBackend:
    kind = "local"

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def _abs(self, rel):
        rel = clean_rel(rel)
        candidate = os.path.realpath(os.path.join(self.root, rel)) if rel else self.root
        try:
            common = os.path.commonpath([self.root, candidate])
        except ValueError:
            raise SourceDenied("the path is outside the source")
        if os.path.normcase(common) != os.path.normcase(self.root):
            raise SourceDenied("the path is outside the source")
        return candidate

    def local_path(self, rel):
        return self._abs(rel)

    def list_dir(self, rel):
        path = self._abs(rel)
        try:
            with os.scandir(path) as iterator:
                items = []
                for entry in iterator:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    items.append(
                        Entry(entry.name, entry.is_dir(follow_symlinks=False), stat.st_size, stat.st_mtime)
                    )
        except PermissionError:
            raise SourceDenied("the source denied access to %s" % (rel or "/"))
        except FileNotFoundError:
            raise SourceUnavailable("the source folder no longer exists")
        except OSError as exc:
            raise SourceUnavailable("the source could not be read: %s" % exc)
        return items

    def stat(self, rel):
        path = self._abs(rel)
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            return None
        except PermissionError:
            raise SourceDenied("the source denied access to %s" % rel)
        return Entry(posixpath.basename(path), os.path.isdir(path), stat.st_size, stat.st_mtime)

    def read_bytes(self, rel, offset=0, length=None):
        path = self._abs(rel)
        try:
            with open(path, "rb") as handle:
                if offset:
                    handle.seek(offset)
                return handle.read(length) if length else handle.read()
        except PermissionError:
            raise SourceDenied("the source denied access to %s" % rel)
        except FileNotFoundError:
            raise SourceUnavailable("the file no longer exists")
        except OSError as exc:
            raise SourceUnavailable("the file could not be read: %s" % exc)

    def download(self, rel, destination, progress=None):
        source = self._abs(rel)
        total = 0
        try:
            total = os.path.getsize(source)
        except OSError:
            pass
        done = 0
        try:
            with open(source, "rb") as reader, open(destination, "wb") as writer:
                while True:
                    chunk = reader.read(config.remote_chunk)
                    if not chunk:
                        break
                    writer.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except PermissionError:
            raise SourceDenied("the source denied access to %s" % rel)
        except OSError as exc:
            raise SourceUnavailable("the file could not be read: %s" % exc)


class WebDAVBackend:
    kind = "webdav"

    def __init__(self, root, username="", password="", timeout=None):
        parsed = urllib.parse.urlsplit(root)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise SourceInvalid("the WebDAV address must start with http:// or https://")
        if parsed.username or parsed.password:
            raise SourceInvalid("put the WebDAV credentials in the dedicated fields")
        self.base = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )
        self.base_path = parsed.path.rstrip("/") or "/"
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout or config.remote_timeout

    def local_path(self, rel):
        return None

    def _url(self, rel):
        rel = clean_rel(rel)
        quoted = "/".join(urllib.parse.quote(piece, safe="") for piece in rel.split("/") if piece)
        return self.base + ("/" + quoted if quoted else "")

    def _request(self, rel, method="GET", headers=None, data=None, range_header=""):
        request = urllib.request.Request(self._url(rel), data=data, method=method)
        request.add_header("User-Agent", config.user_agent)
        if self.username or self.password:
            token = base64.b64encode(
                ("%s:%s" % (self.username, self.password)).encode("utf-8")
            ).decode("ascii")
            request.add_header("Authorization", "Basic " + token)
        if range_header:
            request.add_header("Range", range_header)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            return urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RemoteAuthFailed("the WebDAV server rejected the credentials")
            if exc.code == 404:
                raise SourceUnavailable("the WebDAV path no longer exists")
            raise RemoteUnavailable("WebDAV returned HTTP %d" % exc.code)
        except urllib.error.URLError as exc:
            raise RemoteUnavailable("the WebDAV server could not be reached: %s" % exc.reason)
        except OSError as exc:
            raise RemoteUnavailable("the WebDAV server could not be reached: %s" % exc)

    def list_dir(self, rel):
        response = self._request(
            rel,
            method="PROPFIND",
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            data=_DAV_BODY,
        )
        try:
            payload = response.read()
        finally:
            response.close()
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise RemoteUnavailable("the WebDAV server returned an invalid listing: %s" % exc)
        base_rel = clean_rel(rel)
        entries = {}
        for node in root.iter():
            if _local(node.tag) != "response":
                continue
            href = None
            is_dir = False
            size = 0
            mtime = 0.0
            for child in node:
                name = _local(child.tag)
                if name == "href" and child.text:
                    href = child.text.strip()
                elif name == "propstat":
                    status = ""
                    prop = None
                    for item in child:
                        if _local(item.tag) == "status" and item.text:
                            status = item.text
                        elif _local(item.tag) == "prop":
                            prop = item
                    if prop is None or " 404 " in (" %s " % status):
                        continue
                    for item in prop:
                        key = _local(item.tag)
                        if key == "resourcetype":
                            if any(_local(inner.tag) == "collection" for inner in item):
                                is_dir = True
                        elif key == "getcontentlength" and item.text:
                            try:
                                size = int(item.text.strip())
                            except ValueError:
                                size = 0
                        elif key == "getlastmodified" and item.text:
                            try:
                                mtime = email.utils.parsedate_to_datetime(item.text).timestamp()
                            except (TypeError, ValueError):
                                mtime = 0.0
            if not href:
                continue
            relative = self._relative(href)
            if relative is None:
                continue
            # Collections normally carry a trailing slash in their href.
            relative = relative.rstrip("/")
            if not relative or relative == base_rel:
                continue
            if base_rel and not relative.startswith(base_rel + "/"):
                continue
            tail = relative[len(base_rel):].lstrip("/") if base_rel else relative
            if not tail or "/" in tail:
                continue
            entries[tail] = Entry(tail, is_dir, size, mtime)
        return list(entries.values())

    def _relative(self, href):
        absolute = urllib.parse.urljoin(self.base + "/", href)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.hostname != urllib.parse.urlsplit(self.base).hostname:
            return None
        path = urllib.parse.unquote(parsed.path)
        base = urllib.parse.unquote(self.base_path).rstrip("/")
        if path == base or path == base + "/":
            return ""
        if base and not path.startswith(base + "/"):
            return None
        return path[len(base):].lstrip("/") if base else path.lstrip("/")

    def stat(self, rel):
        response = self._request(
            rel,
            method="PROPFIND",
            headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
            data=_DAV_BODY,
        )
        size = 0
        mtime = 0.0
        is_dir = False
        try:
            payload = response.read()
        finally:
            response.close()
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError:
            return None
        for node in root.iter():
            key = _local(node.tag)
            if key == "collection":
                is_dir = True
            elif key == "getcontentlength" and node.text:
                try:
                    size = int(node.text.strip())
                except ValueError:
                    size = 0
            elif key == "getlastmodified" and node.text:
                try:
                    mtime = email.utils.parsedate_to_datetime(node.text).timestamp()
                except (TypeError, ValueError):
                    mtime = 0.0
        return Entry(posixpath.basename(clean_rel(rel)), is_dir, size, mtime)

    def read_bytes(self, rel, offset=0, length=None):
        range_header = ""
        if offset or length:
            end = "" if length is None else str(offset + length - 1)
            range_header = "bytes=%d-%s" % (offset, end)
        response = self._request(rel, headers={}, range_header=range_header)
        try:
            data = response.read() if length is None else response.read(length)
        finally:
            response.close()
        return data

    def download(self, rel, destination, progress=None):
        response = self._request(rel)
        total = 0
        try:
            raw = response.headers.get("Content-Length")
            total = int(raw) if raw else 0
        except (TypeError, ValueError):
            total = 0
        done = 0
        try:
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(config.remote_chunk)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        finally:
            response.close()


class SMBBackend:
    kind = "smb"

    def __init__(self, root, username="", password="", domain=""):
        try:
            import smbclient  # type: ignore
        except ImportError:
            raise SourceInvalid(
                "SMB support is not installed on this NAS (the smbprotocol package is missing)"
            )
        self._smbclient = smbclient
        host, port, share, base = _parse_smb(root)
        self.host = host
        self.port = port
        self.base = base
        self.unc_root = "\\\\%s\\%s" % (host, share)
        if base:
            self.unc_root += "\\" + base.replace("/", "\\")
        if domain and username:
            username = "%s\\%s" % (domain, username)
        try:
            smbclient.register_session(
                host,
                username=username or None,
                password=password or None,
                port=port,
            )
        except Exception as exc:  # smbprotocol raises its own hierarchy
            raise RemoteAuthFailed("the SMB server rejected the credentials: %s" % exc)

    def local_path(self, rel):
        return None

    def _unc(self, rel):
        rel = clean_rel(rel)
        path = self.unc_root
        if rel:
            path += "\\" + rel.replace("/", "\\")
        return path

    def list_dir(self, rel):
        smbclient = self._smbclient
        try:
            with smbclient.scandir(self._unc(rel), port=self.port) as iterator:
                items = []
                for entry in iterator:
                    if self.port == 445:
                        try:
                            stat = entry.stat()
                        except OSError:
                            continue
                    else:
                        # smbclient's directory entries do not carry the port
                        # override, so a non-default port stats the path directly.
                        try:
                            stat = smbclient.stat(
                                self._unc(posixpath.join(clean_rel(rel), entry.name)),
                                port=self.port,
                            )
                        except Exception:
                            continue
                    items.append(
                        Entry(
                            entry.name,
                            entry.is_dir(),
                            int(getattr(stat, "st_size", 0) or 0),
                            float(getattr(stat, "st_mtime", 0) or 0),
                        )
                    )
                return items
        except Exception as exc:
            raise _smb_error(exc, rel)

    def stat(self, rel):
        try:
            stat = self._smbclient.stat(self._unc(rel), port=self.port)
        except Exception:
            return None
        return Entry(
            posixpath.basename(clean_rel(rel)),
            bool(getattr(stat, "st_mode", 0) & 0o040000),
            int(getattr(stat, "st_size", 0) or 0),
            float(getattr(stat, "st_mtime", 0) or 0),
        )

    def read_bytes(self, rel, offset=0, length=None):
        try:
            with self._smbclient.open_file(self._unc(rel), mode="rb", port=self.port) as handle:
                if offset:
                    handle.seek(offset)
                return handle.read(length) if length else handle.read()
        except Exception as exc:
            raise _smb_error(exc, rel)

    def download(self, rel, destination, progress=None):
        entry = self.stat(rel)
        total = entry.size if entry else 0
        done = 0
        try:
            with self._smbclient.open_file(
                self._unc(rel), mode="rb", port=self.port
            ) as reader, open(destination, "wb") as writer:
                while True:
                    chunk = reader.read(config.remote_chunk)
                    if not chunk:
                        break
                    writer.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except Exception as exc:
            raise _smb_error(exc, rel)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_smb(root):
    raw = (root or "").strip()
    if raw.startswith("smb://"):
        parsed = urllib.parse.urlsplit(raw)
        if not parsed.hostname:
            raise SourceInvalid("the SMB address is missing a host")
        parts = [piece for piece in parsed.path.split("/") if piece]
        if not parts:
            raise SourceInvalid("the SMB address is missing a share name")
        try:
            port = parsed.port or 445
        except ValueError:
            raise SourceInvalid("the SMB address has an invalid port")
        return parsed.hostname, port, parts[0], "/".join(parts[1:])
    if raw.startswith("\\\\") or raw.startswith("//"):
        parts = [piece for piece in raw.replace("/", "\\").split("\\") if piece]
        if len(parts) < 2:
            raise SourceInvalid("the SMB path must name a share")
        return parts[0], 445, parts[1], "/".join(parts[2:])
    raise SourceInvalid("the SMB address must look like smb://host/share/path")


def _smb_error(exc, rel):
    text = str(exc)
    folded = text.lower()
    if "auth" in folded or "logon" in folded or "access denied" in folded:
        return RemoteAuthFailed("the SMB server rejected the credentials")
    if "not found" in folded or "no such" in folded:
        return SourceUnavailable("the SMB path no longer exists")
    return RemoteUnavailable("the SMB source could not be reached: %s" % text)


def backend_for(source):
    kind = (source.get("kind") or "").lower()
    password = secrets.get(source.get("secret_ref") or "")
    username = source.get("username") or ""
    options = {}
    try:
        import json

        options = json.loads(source.get("options") or "{}")
    except ValueError:
        options = {}
    if kind == "local":
        return LocalBackend(source["root"])
    if kind == "webdav":
        return WebDAVBackend(source["root"], username, password)
    if kind == "smb":
        return SMBBackend(source["root"], username, password, options.get("domain", ""))
    raise SourceInvalid("unknown source kind: %s" % kind)


def validate(kind, root, username="", password="", options=None):
    kind = (kind or "").lower()
    root = (root or "").strip()
    if not root:
        raise SourceInvalid("a source location is required")
    if kind == "local":
        real = os.path.realpath(root)
        if not os.path.isdir(real):
            raise SourceInvalid("the folder does not exist or is not a directory")
        data_root = os.path.realpath(config.data_dir)
        try:
            if os.path.commonpath([real, data_root]) == data_root:
                raise SourceInvalid("the application data folder cannot be used as a library")
        except ValueError:
            pass
        try:
            with os.scandir(real) as iterator:
                for _ in iterator:
                    break
        except PermissionError:
            raise SourceDenied("the folder cannot be read by the application")
        except OSError as exc:
            raise SourceInvalid("the folder cannot be read: %s" % exc)
        return real
    if kind == "webdav":
        backend = WebDAVBackend(root, username, password)
        backend.list_dir("")
        return backend.base
    if kind == "smb":
        backend = SMBBackend(root, username, password, (options or {}).get("domain", ""))
        backend.list_dir("")
        return root.rstrip("/")
    raise SourceInvalid("the source kind must be local, webdav or smb")
