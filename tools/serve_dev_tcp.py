#!/usr/bin/env python3
"""Run ComicNest locally over loopback TCP.

Development only: authentication is disabled and a fixed demo user is used.
"""

import argparse
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "usr", "local", "comicnest")
DEV_ROOT = os.path.join(REPO_ROOT, ".devdata")
SHARE_ROOT = os.path.join(DEV_ROOT, "share", "comicnest")
LIBRARY_ROOT = os.path.join(SHARE_ROOT, "library")


def configure():
    os.environ["COMICNEST_ROOT"] = APP_ROOT
    os.environ["COMICNEST_WEBUI"] = os.path.join(REPO_ROOT, "webui")
    os.environ["COMICNEST_SHARE_ROOT"] = SHARE_ROOT
    os.environ["COMICNEST_DATA_DIR"] = os.path.join(DEV_ROOT, "appdata")
    os.environ["COMICNEST_LOG_DIR"] = os.path.join(DEV_ROOT, "logs")
    os.environ["COMICNEST_REQUIRE_AUTH"] = "false"
    os.environ["COMICNEST_REQUIRE_SYSTEM_USER"] = "false"
    os.environ["COMICNEST_SCAN_ON_START"] = "true"
    os.environ.setdefault("COMICNEST_LOG_LEVEL", "INFO")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset:
        shutil.rmtree(os.path.join(DEV_ROOT, "appdata"), ignore_errors=True)
        shutil.rmtree(LIBRARY_ROOT, ignore_errors=True)

    configure()
    sys.path.insert(0, APP_ROOT)
    sys.path.insert(0, os.path.join(APP_ROOT, "lib"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

    needs_seed = True
    if os.path.isdir(LIBRARY_ROOT):
        with os.scandir(LIBRARY_ROOT) as iterator:
            needs_seed = not any(True for _ in iterator)
    if needs_seed:
        from seed_demo import seed

        seed(LIBRARY_ROOT, reset=False)

    os.environ["COMICNEST_DEV_TCP"] = str(args.port)
    print("ComicNest dev server: http://127.0.0.1:%d/" % args.port)
    from lib.server import serve_forever

    serve_forever()


if __name__ == "__main__":
    main()
