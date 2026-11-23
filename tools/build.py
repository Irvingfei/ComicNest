#!/usr/bin/env python3
"""Build the TOS 7 ComicNest package.

Produces a Debian package laid out as the platform metadata parser expects:

    comicnest/
    +-- DEBIAN/
    |   +-- control, preinst, postinst, prerm, postrm
    +-- usr/local/comicnest/
        +-- config.ini, comicnest.lang, comicnest.env, webui.bz2
        +-- bin/comicnest-server
        +-- lib/*.py
        +-- vendor/7zip/7zz, License.txt
        +-- images/icons/comicnest.svg
        +-- init.d/comicnest.service

Usage:
    python tools/build.py                  # x86_64
    python tools/build.py --platform aarch64
    python tools/build.py --no-deb         # assemble the tree only
"""

import argparse
import bz2
import glob
import gzip
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ID = "comicnest"
BUILD_DIR = os.path.join(REPO_ROOT, "build")
DIST_DIR = os.path.join(REPO_ROOT, "dist")

SOURCE_APP_ROOT = os.path.join(REPO_ROOT, "usr", "local", APP_ID)
SOURCE_DEBIAN = os.path.join(REPO_ROOT, "DEBIAN")
SOURCE_WEBUI = os.path.join(REPO_ROOT, "webui")

TEXT_EXTENSIONS = (
    ".sh", ".py", ".ini", ".lang", ".service", ".conf",
    ".js", ".css", ".html", ".env", ".mjs", ".json", ".txt",
)
EXCLUDE_DIRS = {"__pycache__", ".git", ".github", "node_modules", ".workbuddy"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej", ".log", ".swp")
EXEC_NAMES = ("preinst", "postinst", "prerm", "postrm", "comicnest-server", "7zz")


def log(message):
    print("[build] %s" % message)


def read_version():
    with open(os.path.join(SOURCE_APP_ROOT, "config.ini"), "r", encoding="utf-8") as handle:
        return json.load(handle).get("version", "1.0.011")


def force_lf(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return False
    if b"\r\n" not in data:
        return False
    with open(path, "wb") as handle:
        handle.write(data.replace(b"\r\n", b"\n"))
    return True


def normalise_tree(root):
    converted = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if item not in EXCLUDE_DIRS]
        for name in files:
            if not name.endswith(TEXT_EXTENSIONS):
                continue
            if force_lf(os.path.join(base, name)):
                converted += 1
    if converted:
        log("normalised %d file(s) to LF" % converted)


def copy_tree(source, destination):
    copied = 0
    for base, dirs, files in os.walk(source):
        dirs[:] = sorted(item for item in dirs if item not in EXCLUDE_DIRS)
        relative = os.path.relpath(base, source)
        target_dir = destination if relative == "." else os.path.join(destination, relative)
        os.makedirs(target_dir, exist_ok=True)
        for name in sorted(files):
            if name.endswith(EXCLUDE_SUFFIXES):
                continue
            shutil.copy2(os.path.join(base, name), os.path.join(target_dir, name))
            copied += 1
    return copied


def pack_webui(source_dir, destination_bz2):
    if not os.path.isfile(os.path.join(source_dir, "index.html")):
        raise SystemExit("webui/index.html is required")
    entries = []
    for base, dirs, files in os.walk(source_dir):
        dirs[:] = sorted(item for item in dirs if item not in EXCLUDE_DIRS)
        for name in sorted(files):
            if name.endswith(EXCLUDE_SUFFIXES):
                continue
            path = os.path.join(base, name)
            entries.append((path, os.path.relpath(path, source_dir)))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for path, arcname in sorted(entries, key=lambda item: item[1]):
            info = archive.gettarinfo(path, arcname=arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            with open(path, "rb") as handle:
                archive.addfile(info, handle)
    with open(destination_bz2, "wb") as sink:
        sink.write(bz2.compress(buffer.getvalue(), compresslevel=9))
    log("webui.bz2: %d file(s), %d bytes" % (len(entries), os.path.getsize(destination_bz2)))


def syntax_check(root):
    failures = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if item not in EXCLUDE_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                failures.append("%s: %s" % (path, (result.stderr or "").strip()))
    if failures:
        for item in failures:
            log("SYNTAX ERROR %s" % item)
        raise SystemExit("python syntax check failed")
    log("python syntax check passed")


def _pillow_wheel(platform):
    wheels = sorted(
        glob.glob(
            os.path.join(SOURCE_APP_ROOT, "vendor", "wheels", platform, "*.whl")
        )
    )
    return wheels[0] if wheels else ""


def pillow_entries(platform):
    """Wheel-relative paths extracted into vendor/python."""
    wheel = _pillow_wheel(platform)
    if not wheel:
        return []
    entries = []
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith(("PIL/", "pillow.libs/")):
                entries.append(name.rstrip("/"))
    return entries


def bundle_pillow(payload_root, platform):
    wheel = _pillow_wheel(platform)
    if not wheel:
        log("WARNING: no Pillow wheel for %s; TIFF pages will need external Pillow" % platform)
        return
    target = os.path.join(payload_root, "vendor", "python")
    license_target = os.path.join(target, "licenses", "pillow-LICENSE")
    os.makedirs(os.path.dirname(license_target), exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename.startswith(("PIL/", "pillow.libs/")):
                archive.extract(info, target)
                extracted += 1
            elif info.filename.endswith("licenses/LICENSE"):
                with archive.open(info) as reader, open(license_target, "wb") as writer:
                    shutil.copyfileobj(reader, writer)
    log("bundled Pillow (%d file(s))" % extracted)


def copy_seven_zip(payload_root, platform):
    source = os.path.join(SOURCE_APP_ROOT, "vendor", "7zip", platform, "7zz")
    license_source = os.path.join(SOURCE_APP_ROOT, "vendor", "7zip", "License.txt")
    target_dir = os.path.join(payload_root, "vendor", "7zip")
    if not os.path.isfile(source):
        log("WARNING: vendor/7zip/%s/7zz is missing; RAR and 7z need an external 7-Zip" % platform)
        return
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(source, os.path.join(target_dir, "7zz"))
    if os.path.isfile(license_source):
        shutil.copy2(license_source, os.path.join(target_dir, "License.txt"))
    log("bundled 7-Zip for %s (%d bytes)" % (platform, os.path.getsize(source)))


def patch_platform(config_path, platform):
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["platform"] = platform
    with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_control(control_path, platform, version, installed_size):
    architecture = "amd64" if platform == "x86_64" else "arm64"
    with open(os.path.join(SOURCE_DEBIAN, "control"), "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    output = []
    for line in lines:
        if line.startswith("Architecture:"):
            output.append("Architecture: %s" % architecture)
        elif line.startswith("Version:"):
            output.append("Version: %s" % version)
        elif line.startswith("Installed-Size:"):
            output.append("Installed-Size: %d" % installed_size)
        else:
            output.append(line)
    with open(control_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(output) + "\n")


def make_executable(path):
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def measure_size(root):
    total = 0
    for base, dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return max(1, total // 1024)


def expected_files(root, platform):
    expected = set()

    def add(relative):
        expected.add(os.path.normcase(os.path.join(root, relative)))

    for name in ("preinst", "postinst", "prerm", "postrm"):
        add(os.path.join("DEBIAN", name))

    payload = os.path.join("usr", "local", APP_ID)
    for name in ("config.ini", "%s.lang" % APP_ID, "%s.env" % APP_ID, "webui.bz2"):
        add(os.path.join(payload, name))
    add(os.path.join(payload, "vendor", "7zip", "7zz"))
    add(os.path.join(payload, "vendor", "7zip", "License.txt"))

    for item in ("bin", "lib", "images", "init.d", "vendor/python"):
        source = os.path.join(SOURCE_APP_ROOT, item.replace("/", os.sep))
        if not os.path.isdir(source):
            continue
        for base, dirs, files in os.walk(source):
            dirs[:] = [entry for entry in dirs if entry not in EXCLUDE_DIRS]
            for name in files:
                if name.endswith(EXCLUDE_SUFFIXES):
                    continue
                relative = os.path.relpath(os.path.join(base, name), SOURCE_APP_ROOT)
                add(os.path.join(payload, relative))
    for entry in pillow_entries(platform):
        add(os.path.join(payload, "vendor", "python", entry.replace("/", os.sep)))
    add(os.path.join(payload, "vendor", "python", "licenses", "pillow-LICENSE"))
    return expected


def prune(root, expected):
    removed = 0
    for base, dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(base, name)
            if os.path.normcase(path) not in expected:
                try:
                    os.remove(path)
                    removed += 1
                except OSError:
                    pass
        for name in dirs:
            path = os.path.join(base, name)
            try:
                if not os.listdir(path):
                    os.rmdir(path)
            except OSError:
                pass
    if removed:
        log("removed %d stale file(s)" % removed)


def assemble(platform, version):
    root = os.path.join(BUILD_DIR, APP_ID)
    debian = os.path.join(root, "DEBIAN")
    payload_root = os.path.join(root, "usr", "local", APP_ID)
    os.makedirs(debian, exist_ok=True)
    os.makedirs(payload_root, exist_ok=True)
    log("assembling %s" % root)

    for name in ("preinst", "postinst", "prerm", "postrm"):
        target = os.path.join(debian, name)
        shutil.copy2(os.path.join(SOURCE_DEBIAN, name), target)
        make_executable(target)

    for item in ("bin", "lib", "images", "init.d"):
        source = os.path.join(SOURCE_APP_ROOT, item)
        if os.path.isdir(source):
            copy_tree(source, os.path.join(payload_root, item))

    for name in ("config.ini", "%s.lang" % APP_ID, "%s.env" % APP_ID):
        shutil.copy2(os.path.join(SOURCE_APP_ROOT, name), os.path.join(payload_root, name))

    copy_seven_zip(payload_root, platform)
    vendor_python = os.path.join(SOURCE_APP_ROOT, "vendor", "python")
    if os.path.isdir(vendor_python):
        count = copy_tree(vendor_python, os.path.join(payload_root, "vendor", "python"))
        log("bundled SMB support (%d file(s))" % count)
    bundle_pillow(payload_root, platform)
    patch_platform(os.path.join(payload_root, "config.ini"), platform)
    pack_webui(SOURCE_WEBUI, os.path.join(payload_root, "webui.bz2"))
    make_executable(os.path.join(payload_root, "bin", "comicnest-server"))

    expected = expected_files(root, platform)
    prune(root, expected)
    normalise_tree(os.path.join(root, "usr"))
    normalise_tree(debian)
    installed_size = measure_size(os.path.join(root, "usr"))
    write_control(os.path.join(debian, "control"), platform, version, installed_size)
    log("Installed-Size: %d KB" % installed_size)
    return root


def needs_exec(arcname):
    return arcname.rsplit("/", 1)[-1] in EXEC_NAMES


def manual_deb(root, output):
    def tar_bytes(source_root, skip_debian=False):
        def add_entries(archive):
            entries = []
            for base, dirs, files in os.walk(source_root):
                dirs[:] = sorted(item for item in dirs if item not in EXCLUDE_DIRS)
                if skip_debian and base == source_root:
                    dirs[:] = [item for item in dirs if item != "DEBIAN"]
                relative = os.path.relpath(base, source_root)
                if relative == ".":
                    relative = ""
                for name in dirs:
                    path = os.path.join(base, name)
                    arcname = "%s/%s" % (relative, name) if relative else name
                    entries.append((path, arcname, True))
                for name in sorted(files):
                    if name.endswith(EXCLUDE_SUFFIXES):
                        continue
                    path = os.path.join(base, name)
                    arcname = "%s/%s" % (relative, name) if relative else name
                    entries.append((path, arcname, False))
            for path, arcname, is_dir in sorted(entries, key=lambda item: item[1]):
                info = archive.gettarinfo(path, arcname="./" + arcname)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = 0
                if is_dir:
                    info.mode = 0o755
                    info.size = 0
                    archive.addfile(info)
                else:
                    info.mode = 0o755 if needs_exec(arcname) else 0o644
                    with open(path, "rb") as handle:
                        archive.addfile(info, handle)

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
            root_info = tarfile.TarInfo("./")
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o755
            root_info.uid = root_info.gid = 0
            root_info.uname = root_info.gname = "root"
            archive.addfile(root_info)
            add_entries(archive)
        return gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0)

    control_tar = tar_bytes(os.path.join(root, "DEBIAN"))
    data_tar = tar_bytes(root, skip_debian=True)

    def ar_entry(name, payload):
        header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, 0, 0, 0, "100644", len(payload))
        out = header.encode("ascii") + payload
        if len(payload) % 2:
            out += b"\n"
        return out

    with open(output, "wb") as handle:
        handle.write(b"!<arch>\n")
        handle.write(ar_entry("debian-binary", b"2.0\n"))
        handle.write(ar_entry("control.tar.gz", control_tar))
        handle.write(ar_entry("data.tar.gz", data_tar))
    return output


def build_deb(root, platform, version):
    os.makedirs(DIST_DIR, exist_ok=True)
    package = os.path.join(DIST_DIR, "%s_%s.deb" % (APP_ID, platform))
    dpkg = shutil.which("dpkg-deb")
    if dpkg:
        result = subprocess.run(
            [dpkg, "--build", "--root-owner-group", root, package],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SystemExit("dpkg-deb failed: %s" % (result.stderr or result.stdout))
        log("built with dpkg-deb")
    else:
        manual_deb(root, package)
        log("built with the bundled writer")

    digest = hashlib.sha256()
    with open(package, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    checksum = digest.hexdigest()
    with open(package + ".sha256", "w", encoding="ascii", newline="\n") as handle:
        handle.write("%s  %s\n" % (checksum, os.path.basename(package)))
    log("sha256 %s" % checksum)
    inspect(package)
    return package


def inspect(package):
    dpkg = shutil.which("dpkg-deb")
    if not dpkg:
        log("package written; verify the layout with dpkg-deb -c on a Debian host")
        return
    result = subprocess.run([dpkg, "-c", package], capture_output=True, text=True)
    listing = result.stdout or ""
    required = [
        "usr/local/%s/config.ini" % APP_ID,
        "usr/local/%s/%s.lang" % (APP_ID, APP_ID),
        "usr/local/%s/images/icons/%s.svg" % (APP_ID, APP_ID),
        "usr/local/%s/webui.bz2" % APP_ID,
        "usr/local/%s/bin/comicnest-server" % APP_ID,
        "usr/local/%s/init.d/comicnest.service" % APP_ID,
    ]
    missing = [item for item in required if item not in listing]
    if missing:
        raise SystemExit("package inspection failed: missing %s" % ", ".join(missing))
    log("package inspection passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the TOS 7 ComicNest package")
    parser.add_argument("--platform", choices=("x86_64", "aarch64"), default="x86_64")
    parser.add_argument("--no-deb", action="store_true")
    args = parser.parse_args(argv)

    normalise_tree(REPO_ROOT)
    syntax_check(SOURCE_APP_ROOT)
    version = read_version()
    log("version %s, platform %s" % (version, args.platform))
    root = assemble(args.platform, version)
    if args.no_deb:
        log("package tree ready at %s" % root)
        return 0
    package = build_deb(root, args.platform, version)
    log("done: %s" % package)
    return 0


if __name__ == "__main__":
    sys.exit(main())
