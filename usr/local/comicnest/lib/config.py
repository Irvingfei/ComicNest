"""Runtime configuration for ComicNest.

Every option comes from the environment or from ``comicnest.env`` next to the
application. Nothing is written back to the package tree.
"""

import glob
import os

APP_ID = os.environ.get("COMICNEST_APP_ID", "comicnest")

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.environ.get("COMICNEST_ROOT") or os.path.dirname(_LIB_DIR)
if not os.path.isdir(os.path.join(_APP_ROOT, "lib")):
    _APP_ROOT = os.path.dirname(os.path.dirname(_LIB_DIR))

_ENV_FILE = os.path.join(_APP_ROOT, "comicnest.env")


def _load_env_file(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_FILE_ENV = _load_env_file(_ENV_FILE)


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self):
        env = lambda key, default="": os.environ.get(key) or _FILE_ENV.get(key, default)

        self.app_id = env("COMICNEST_APP_ID", APP_ID)
        self.app_root = _APP_ROOT
        self.lib_dir = _LIB_DIR

        prefix = env("COMICNEST_PROXY_PREFIX", "/%s/" % self.app_id)
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        if not prefix.endswith("/"):
            prefix += "/"
        self.proxy_prefix = prefix

        self.socket_path = env("COMICNEST_SOCKET", "/var/api/%s.sock" % self.app_id)
        self.socket_mode = int(env("COMICNEST_SOCKET_MODE", "660"), 8)
        self.dev_tcp = env("COMICNEST_DEV_TCP", "")

        self.webui_dir = env("COMICNEST_WEBUI", os.path.join(self.app_root, "webui"))
        self.data_dir = env("COMICNEST_DATA_DIR", os.path.join(self.app_root, "data"))
        self.db_path = env("COMICNEST_DB", os.path.join(self.data_dir, "library.db"))
        self.cache_dir = env("COMICNEST_CACHE_DIR", os.path.join(self.data_dir, "cache"))
        self.covers_dir = env("COMICNEST_COVERS_DIR", os.path.join(self.data_dir, "covers"))
        self.tmp_dir = env("COMICNEST_TMP_DIR", os.path.join(self.data_dir, "tmp"))
        self.secrets_path = env(
            "COMICNEST_SECRETS", os.path.join(self.data_dir, "secrets.json")
        )
        self.log_dir = env("COMICNEST_LOG_DIR", os.path.join(self.app_root, "logs"))

        self.log_level = env("COMICNEST_LOG_LEVEL", "INFO")
        self.log_to_file = _as_bool(env("COMICNEST_LOG_TO_FILE", "false"))

        # The application's own shared folder. ``share_root`` can be overridden
        # for development and for installations where the folder already exists.
        self.share_name = env("COMICNEST_SHARE_NAME", self.app_id)
        self.volume_glob = env("COMICNEST_VOLUME_GLOB", "/Volume*")
        self.share_root_override = env("COMICNEST_SHARE_ROOT", "")
        self.library_dirname = env("COMICNEST_LIBRARY_DIR", "library")

        self.page_extensions = tuple(
            ext if ext.startswith(".") else "." + ext
            for ext in (
                item.strip().lower()
                for item in env(
                    "COMICNEST_IMAGE_EXTENSIONS",
                    ".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif,.avif",
                ).split(",")
            )
            if ext
        )
        self.archive_extensions = tuple(
            ext if ext.startswith(".") else "." + ext
            for ext in (
                item.strip().lower()
                for item in env(
                    "COMICNEST_ARCHIVE_EXTENSIONS",
                    ".cbz,.cbr,.cb7,.zip,.rar,.7z,.tar",
                ).split(",")
            )
            if ext
        )
        self.pdf_extensions = (".pdf",)

        self.max_cache_bytes = int(
            float(env("COMICNEST_CACHE_GB", "8")) * 1024 * 1024 * 1024
        )
        self.remote_timeout = float(env("COMICNEST_REMOTE_TIMEOUT", "30"))
        self.remote_chunk = int(env("COMICNEST_REMOTE_CHUNK", str(1024 * 1024)))
        self.max_json_bytes = int(env("COMICNEST_MAX_JSON_MB", "8")) * 1024 * 1024
        self.user_agent = env("COMICNEST_USER_AGENT", "ComicNest/1.0")

        # ``seven_zip`` may point at a bundled binary. Otherwise the usual names
        # are looked up on PATH.
        self.seven_zip = env("COMICNEST_SEVEN_ZIP", "")

        self.require_auth = _as_bool(env("COMICNEST_REQUIRE_AUTH", "true"))
        self.env_verify_url = env("COMICNEST_VERIFY_URL", "")
        self.user_cookie = env("COMICNEST_USER_COOKIE", "tos_current_username")
        self.user_header = env("COMICNEST_USER_HEADER", "X-ComicNest-User")
        self.require_system_user = _as_bool(env("COMICNEST_REQUIRE_SYSTEM_USER", "true"))
        self.admin_users = tuple(
            item.strip()
            for item in env("COMICNEST_ADMIN_USERS", "").split(",")
            if item.strip()
        )
        self.admin_groups = tuple(
            item.strip()
            for item in env(
                "COMICNEST_ADMIN_GROUPS", "administrators,admin,wheel"
            ).split(",")
            if item.strip()
        )

        self.scan_on_start = _as_bool(env("COMICNEST_SCAN_ON_START", "true"))
        self.scan_workers = max(1, int(env("COMICNEST_SCAN_WORKERS", "1")))

    # ------------------------------------------------------------------ paths

    def share_root(self):
        if self.share_root_override:
            return self.share_root_override
        for volume in sorted(glob.glob(self.volume_glob)):
            candidate = os.path.join(volume, self.share_name)
            if os.path.isdir(candidate):
                return candidate
        return ""

    def library_root(self):
        share = self.share_root()
        return os.path.join(share, self.library_dirname) if share else ""

    def ensure_directories(self):
        for path in (
            self.data_dir,
            self.cache_dir,
            self.covers_dir,
            self.tmp_dir,
            os.path.dirname(self.db_path),
        ):
            if path:
                os.makedirs(path, exist_ok=True)

    def describe(self):
        return {
            "app_id": self.app_id,
            "app_root": self.app_root,
            "socket_path": self.socket_path,
            "db_path": self.db_path,
            "share_root": self.share_root() or "(not found)",
            "library_root": self.library_root() or "(not found)",
            "log_level": self.log_level,
        }


config = Config()
