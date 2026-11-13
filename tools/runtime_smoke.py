#!/usr/bin/env python3
"""Exercise CopyPath's installed archive in isolated Sublime Text 4215.

The runner accepts the official Linux tarball and the already-built
``dist/CopyPath.sublime-package``. It extracts Sublime into a disposable
portable directory, refuses any pre-existing ``Data`` directory, installs only
the exact package archive, and copies the probe into a separate test package.

Linux dependencies are documented in ``tools/Dockerfile.runtime``. The editor
runs under a private Xvfb display; no live user desktop or profile is touched.
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BUILD = "4215"
EXPECTED_SUBLIME_ARCHIVE_SHA256 = (
    "c153f418d3ab26b90ecce8c02a82e4e961025ed7a65f7e25060a5457d43e88d9"
)
STRIPPED_EDITOR_ENV = ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH")
REQUIRED_CASES = (
    "mouse_auto_json",
    "mouse_pointer_json",
    "mouse_xpath_xml_attribute",
    "mouse_auto_xml",
    "mouse_text_xml",
    "incomplete_xml",
    "mouse_submenu_disabled",
    "mouse_context_disabled",
    "caret_multiple_unicode",
    "yaml_archive_import",
    "malformed_preserves_clipboard",
)
MENU_ROW_HEIGHT = 26
EXPECTED_CLIPBOARDS = {
    "mouse_auto_json": "$.catalog[1].label",
    "mouse_pointer_json": "/a~1b/~0key/1/value",
    "mouse_xpath_xml_attribute": "/root[1]/item[2]/@id",
    "mouse_auto_xml": "/catalog/book[@id='b']",
    "mouse_text_xml": "/catalog/book[.='Title']",
    "incomplete_xml": "/catalog[1]/book[2]",
    "mouse_submenu_disabled": "COPY_PATH_RUNTIME_SENTINEL_mouse_submenu_disabled",
    "mouse_context_disabled": "COPY_PATH_RUNTIME_SENTINEL_mouse_context_disabled",
    "caret_multiple_unicode": '$.users[0].name\n$["\\u043a\\u043b\\u044e\\u0447"].emoji',
    "yaml_archive_import": "$.root.items[0].city",
    "malformed_preserves_clipboard": "MALFORMED_CLIPBOARD_MUST_SURVIVE",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_editor_env(base, display, evidence):
    environment = dict(base)
    for name in STRIPPED_EDITOR_ENV:
        environment.pop(name, None)
    environment["DISPLAY"] = display
    environment["COPY_PATH_RUNTIME_EVIDENCE"] = str(Path(evidence))
    return environment


def extract_sublime_archive(archive_path, destination):
    archive_path = Path(archive_path).resolve()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(str(archive_path), "r:xz") as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeError("Sublime archive is empty")
        roots = {PurePosixPath(member.name).parts[0] for member in members if member.name}
        if roots != {"sublime_text"}:
            raise RuntimeError("archive must contain one sublime_text root")
        for member in members:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] != "sublime_text"
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise RuntimeError("unsafe tar member: {}".format(member.name))
        if sys.version_info >= (3, 12):
            archive.extractall(str(destination), filter="fully_trusted")
        else:
            archive.extractall(str(destination))
    sublime_dir = destination / "sublime_text"
    binary = sublime_dir / "sublime_text"
    if not binary.is_file():
        raise RuntimeError("archive did not contain the sublime_text root binary")
    return sublime_dir


def prepare_profile(sublime_dir, package_archive, driver_path, evidence):
    del evidence  # Kept in the signature to make the profile/evidence binding explicit.
    sublime_dir = Path(sublime_dir).resolve()
    package_archive = Path(package_archive).resolve()
    driver_path = Path(driver_path).resolve()
    data = sublime_dir / "Data"
    if data.exists():
        raise RuntimeError("refusing existing Data directory: {}".format(data))
    installed = data / "Installed Packages"
    probe = data / "Packages" / "CopyPathRuntimeProbe"
    user = data / "Packages" / "User"
    installed.mkdir(parents=True)
    probe.mkdir(parents=True)
    user.mkdir(parents=True)
    shutil.copyfile(str(package_archive), str(installed / "CopyPath.sublime-package"))
    shutil.copyfile(str(driver_path), str(probe / "runtime_driver.py"))
    preferences = {
        "animation_enabled": False,
        "font_size": 18,
        "hardware_acceleration": "none",
        "hot_exit": False,
        "remember_open_files": False,
        "show_rel_path": False,
        "update_check": False,
        "word_wrap": False,
    }
    (user / "Preferences.sublime-settings").write_text(
        json.dumps(preferences, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return data


def menu_row_point(box, row, row_height=MENU_ROW_HEIGHT):
    left, top, right, bottom = box
    x = (left + right) // 2
    y = top + row * row_height + row_height // 2
    if row < 0 or not (left <= x < right and top <= y < bottom):
        raise ValueError("menu row is outside the detected menu box")
    return x, y


def adjust_window_target(target, frame_extents):
    """Translate Sublime client coordinates for xdotool's framed window origin."""
    left, _right, top, _bottom = frame_extents
    return int(round(target["x"] + left)), int(round(target["y"] + top))


def validate_runtime_report(report, expected_archive_sha256, evidence_dir=None):
    if report.get("passed") is not True:
        raise RuntimeError(report.get("error", "runtime report did not pass"))
    if report.get("build") != EXPECTED_BUILD:
        raise RuntimeError("expected Sublime {}, got {}".format(EXPECTED_BUILD, report.get("build")))
    if report.get("platform") != "linux":
        raise RuntimeError("runtime platform must be linux")
    if report.get("sublime_archive_sha256") != EXPECTED_SUBLIME_ARCHIVE_SHA256:
        raise RuntimeError("editor archive checksum does not match the pinned distribution")
    if report.get("archive_sha256") != expected_archive_sha256:
        raise RuntimeError("installed archive checksum does not match the candidate")
    if report.get("installed_archive_sha256") != expected_archive_sha256:
        raise RuntimeError("actual installed archive checksum does not match the candidate")
    python_version = report.get("python")
    if not isinstance(python_version, str) or not python_version.startswith("3.14."):
        raise RuntimeError("expected the Python 3.14 plugin host")
    if report.get("archive_only") is not True:
        raise RuntimeError("runtime did not load the archive-only installation")
    if "CopyPath.sublime-package" not in (report.get("plugin_module") or ""):
        raise RuntimeError("plugin module was not loaded from the installed archive")
    probe_module = report.get("probe_module") or ""
    if "CopyPathRuntimeProbe" not in probe_module or "CopyPath.sublime-package" in probe_module:
        raise RuntimeError("runtime driver was not isolated in the separate probe package")
    if report.get("cleanup_issues"):
        raise RuntimeError("runtime process cleanup failed: {}".format(report["cleanup_issues"]))
    environment = report.get("environment", {})
    leaked = [name for name in STRIPPED_EDITOR_ENV if environment.get(name) is not None]
    if leaked:
        raise RuntimeError("editor child inherited loader variables: {}".format(", ".join(leaked)))
    cases = {case.get("name"): case for case in report.get("cases", [])}
    missing = [name for name in REQUIRED_CASES if name not in cases]
    if missing:
        raise RuntimeError("missing runtime cases: {}".format(", ".join(missing)))
    if len(cases) != len(report["cases"]) or set(cases) != set(REQUIRED_CASES):
        raise RuntimeError("runtime case names must be unique and exactly match the acceptance set")
    failed = [
        name
        for name in REQUIRED_CASES
        if cases[name].get("passed") is not True
        or cases[name].get("source_preserved") is not True
    ]
    if failed:
        raise RuntimeError("failed runtime cases: {}".format(", ".join(failed)))
    for name, case in cases.items():
        expected = EXPECTED_CLIPBOARDS[name]
        if case.get("clipboard") != expected or case.get("expected_clipboard") != expected:
            raise RuntimeError("incorrect runtime clipboard: {}".format(name))
        before = dict(case.get("before", {}))
        before.update(case.get("menu_open") or {})
        after = case.get("after", {})
        for field in ("text_sha256", "selections", "change_count"):
            if field not in before or field not in after or before[field] != after[field]:
                raise RuntimeError("runtime source/selection changed: {}".format(name))
        if name.startswith("mouse_"):
            suffixes = ("context",) if name.startswith("mouse_auto_") else ("context", "submenu")
            expected_files = [name + "-" + suffix + ".png" for suffix in suffixes]
            screenshots = case.get("screenshots", [])
            if [shot.get("file") for shot in screenshots] != expected_files:
                raise RuntimeError("missing or unexpected runtime screenshots: {}".format(name))
            for shot in screenshots:
                digest = shot.get("sha256", "")
                if not isinstance(digest, str) or len(digest) != 64 or any(
                    char not in "0123456789abcdef" for char in digest
                ):
                    raise RuntimeError("invalid screenshot checksum")
                if evidence_dir is not None:
                    path = Path(evidence_dir) / shot["file"]
                    if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
                        raise RuntimeError("retained screenshot missing or changed: {}".format(shot["file"]))
    yaml_case = cases["yaml_archive_import"]
    if cases["malformed_preserves_clipboard"].get("status_messages") != ["Invalid JSON document."]:
        raise RuntimeError("malformed-document rejection was not observed")
    if cases['incomplete_xml'].get('status_messages') != ['Copied positional XPath from incomplete XML.']:
        raise RuntimeError('XML recovery warning was not observed')
    for name in ('mouse_submenu_disabled', 'mouse_context_disabled'):
        if cases[name].get('settings_open') is not True:
            raise RuntimeError('Settings menu did not open package settings')
    modules = yaml_case.get("yaml_modules", {})
    if (yaml_case.get("yaml_imports_from_archive") is not True
            or "CopyPath.copy_path_lib.vendor.yaml.parser" not in modules
            or not all(isinstance(path, str) and "CopyPath.sublime-package/" in path
                       for path in modules.values())):
        raise RuntimeError("YAML modules were not imported from the installed archive")


def run_self_tests():
    """Focused safety regressions that need no Sublime installation."""
    checks = []

    original = {
        "PATH": "/bin",
        "LD_LIBRARY_PATH": "unsafe-ld",
        "PYTHONHOME": "unsafe-home",
        "PYTHONPATH": "unsafe-path",
        "KEEP_ME": "yes",
    }
    environment = build_editor_env(original, ":71", Path("/evidence"))
    assert environment["DISPLAY"] == ":71"
    assert environment["COPY_PATH_RUNTIME_EVIDENCE"] == str(Path("/evidence"))
    assert environment["KEEP_ME"] == "yes"
    assert all(name not in environment for name in STRIPPED_EDITOR_ENV)
    assert original["LD_LIBRARY_PATH"] == "unsafe-ld"
    checks.append("editor environment confinement")

    assert menu_row_point((410, 270, 670, 510), 0, 26) == (540, 283)
    assert adjust_window_target({"x": 415.4, "y": 188.6}, (1, 1, 22, 5)) == (416, 211)
    checks.append("native menu and frame geometry")

    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        sublime_dir = temporary_root / "sublime_text"
        sublime_dir.mkdir()
        package = temporary_root / "candidate.zip"
        package.write_bytes(b"archive")
        driver = temporary_root / "runtime_driver.py"
        driver.write_text("# probe\n", encoding="utf-8")
        evidence = temporary_root / "evidence"
        evidence.mkdir()
        data = prepare_profile(sublime_dir, package, driver, evidence)
        assert sorted(path.name for path in (data / "Installed Packages").iterdir()) == [
            "CopyPath.sublime-package"
        ]
        assert not (data / "Packages" / "CopyPath").exists()
        try:
            prepare_profile(sublime_dir, package, driver, evidence)
        except RuntimeError as error:
            assert "existing Data" in str(error)
        else:
            raise AssertionError("existing portable Data directory was accepted")
    checks.append("fresh archive-only portable profile")

    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "bad.tar.xz"
        with tarfile.open(str(archive_path), "w:xz") as archive:
            payload = b"bad"
            member = tarfile.TarInfo("sublime_text/../../escape")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        try:
            extract_sublime_archive(archive_path, temporary_root / "out")
        except RuntimeError as error:
            assert "unsafe tar member" in str(error)
        else:
            raise AssertionError("tar traversal member was accepted")
        assert not (temporary_root / "escape").exists()
    checks.append("official archive extraction confinement")

    digest = hashlib.sha256(b"archive").hexdigest()
    report = {
        "passed": True,
        "platform": "linux",
        "build": EXPECTED_BUILD,
        "sublime_archive_sha256": EXPECTED_SUBLIME_ARCHIVE_SHA256,
        "archive_sha256": digest,
        "installed_archive_sha256": digest,
        "python": "3.14.6",
        "environment": {name: None for name in STRIPPED_EDITOR_ENV},
        "archive_only": True,
        "plugin_module": "/portable/Data/Installed Packages/CopyPath.sublime-package/copy_path.py",
        "probe_module": "/portable/Data/Packages/CopyPathRuntimeProbe/runtime_driver.py",
        "cleanup_issues": [],
        "cases": [
            {"name": name, "passed": True, "source_preserved": True,
             "clipboard": EXPECTED_CLIPBOARDS[name],
             "expected_clipboard": EXPECTED_CLIPBOARDS[name],
             "before": {"text_sha256": digest, "selections": [[0, 0]], "change_count": 0},
             "after": {"text_sha256": digest, "selections": [[0, 0]], "change_count": 0}}
            for name in REQUIRED_CASES
        ],
    }
    for case in report["cases"]:
        name = case["name"]
        if name.startswith("mouse_"):
            suffixes = ("context",) if name.startswith("mouse_auto_") else ("context", "submenu")
            case["screenshots"] = [
                {"file": name + "-" + suffix + ".png", "sha256": digest}
                for suffix in suffixes
            ]
        if name == "yaml_archive_import":
            case["yaml_imports_from_archive"] = True
            case["yaml_modules"] = {
                "CopyPath.copy_path_lib.vendor.yaml.parser":
                    "/CopyPath.sublime-package/copy_path_lib/vendor/yaml/parser.py"
            }
        if name == "malformed_preserves_clipboard":
            case["status_messages"] = ["Invalid JSON document."]
        if name == 'incomplete_xml':
            case['status_messages'] = ['Copied positional XPath from incomplete XML.']
        if name in ('mouse_submenu_disabled', 'mouse_context_disabled'):
            case['settings_open'] = True
    validate_runtime_report(report, digest)
    broken = dict(report)
    broken["cleanup_issues"] = ["editor did not stop"]
    try:
        validate_runtime_report(broken, digest)
    except RuntimeError as error:
        assert "cleanup" in str(error)
    else:
        raise AssertionError("cleanup failure was accepted")
    checks.append("runtime report fail-closed validation")

    print("PASS: {} runtime harness self-tests".format(len(checks)))
    for check in checks:
        print("- " + check)
    return 0


class ProcessGroup(object):
    def __init__(self):
        self.processes = []

    def add(self, process):
        self.processes.append(process)
        return process

    def cleanup(self):
        issues = []
        for process in reversed(self.processes):
            if process.poll() is not None:
                continue
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    issues.append("pid {} did not stop".format(process.pid))
        return issues


class ControlClient(object):
    def __init__(self, protocol_dir, editor):
        self.protocol_dir = Path(protocol_dir)
        self.control = self.protocol_dir / "control.json"
        self.responses = self.protocol_dir / "responses"
        self.editor = editor
        self.counter = 0

    def request(self, operation, timeout=8.0, optional=False, **payload):
        self.counter += 1
        request_id = "{:04d}-{}".format(self.counter, uuid.uuid4().hex[:8])
        request = {"id": request_id, "operation": operation}
        request.update(payload)
        temporary = self.control.with_name(self.control.name + ".tmp")
        temporary.write_text(
            json.dumps(request, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(str(temporary), str(self.control))
        response_path = self.responses / (request_id + ".json")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if response_path.is_file():
                response = json.loads(response_path.read_text(encoding="utf-8"))
                if not response.get("ok"):
                    raise RuntimeError(response.get("error", "runtime probe request failed"))
                return response
            if self.editor.poll() is not None:
                raise RuntimeError("Sublime exited during runtime probe")
            time.sleep(0.04)
        if optional:
            return None
        raise RuntimeError("timed out waiting for runtime probe operation {}".format(operation))


def _run_xdotool(display, arguments, timeout=5.0):
    environment = dict(os.environ)
    environment["DISPLAY"] = display
    completed = subprocess.run(
        ["xdotool"] + list(arguments),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "xdotool {} failed: {}".format(" ".join(arguments), completed.stderr.strip())
        )
    return completed.stdout.strip()


def _find_window(display):
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        for search in (
            ["search", "--onlyvisible", "--name", "CopyPath Runtime"],
            ["search", "--onlyvisible", "--class", "sublime_text"],
        ):
            try:
                output = _run_xdotool(display, search)
            except RuntimeError:
                continue
            ids = [line.strip() for line in output.splitlines() if line.strip()]
            if ids:
                return ids[-1]
        time.sleep(0.1)
    raise RuntimeError("unable to locate the isolated Sublime window")


def _activate_window(display, window_id):
    _run_xdotool(display, ["windowactivate", "--sync", window_id])
    _run_xdotool(display, ["windowmove", "--sync", window_id, "80", "70"])
    _run_xdotool(display, ["windowsize", "--sync", window_id, "1180", "820"])
    _run_xdotool(display, ["windowactivate", "--sync", window_id])


def _mouse_location(display):
    output = _run_xdotool(display, ["getmouselocation", "--shell"])
    values = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return int(values["X"]), int(values["Y"])


def _window_frame_extents(display, window_id):
    """Read EWMH left/right/top/bottom decorations without xprop."""
    library_name = ctypes.util.find_library("X11") or "libX11.so.6"
    library = ctypes.cdll.LoadLibrary(library_name)
    library.XOpenDisplay.argtypes = [ctypes.c_char_p]
    library.XOpenDisplay.restype = ctypes.c_void_p
    library.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    library.XInternAtom.restype = ctypes.c_ulong
    library.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    library.XGetWindowProperty.restype = ctypes.c_int
    library.XFree.argtypes = [ctypes.c_void_p]
    library.XCloseDisplay.argtypes = [ctypes.c_void_p]
    connection = library.XOpenDisplay(display.encode("ascii"))
    if not connection:
        return (0, 0, 0, 0)
    property_data = ctypes.POINTER(ctypes.c_ubyte)()
    try:
        atom = library.XInternAtom(connection, b"_NET_FRAME_EXTENTS", 1)
        if not atom:
            return (0, 0, 0, 0)
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        item_count = ctypes.c_ulong()
        remaining = ctypes.c_ulong()
        status = library.XGetWindowProperty(
            connection,
            ctypes.c_ulong(int(window_id)),
            atom,
            0,
            4,
            0,
            0,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(item_count),
            ctypes.byref(remaining),
            ctypes.byref(property_data),
        )
        if status != 0 or actual_format.value != 32 or item_count.value < 4:
            return (0, 0, 0, 0)
        values = ctypes.cast(property_data, ctypes.POINTER(ctypes.c_ulong))
        return tuple(int(values[index]) for index in range(4))
    finally:
        if property_data:
            library.XFree(property_data)
        library.XCloseDisplay(connection)


def _capture_screenshot(display, destination):
    try:
        from PIL import ImageGrab
    except ImportError as error:
        raise RuntimeError("Pillow ImageGrab is required for menu evidence") from error
    image = ImageGrab.grab(xdisplay=display)
    image.save(str(destination), format="PNG")
    return destination


def _is_menu_light(pixel):
    red, green, blue = pixel[:3]
    return min(red, green, blue) >= 180 and max(red, green, blue) - min(red, green, blue) <= 45


def _scan_light_extent(image, y, start_x, max_width=520):
    pixels = image.convert("RGB")
    width, height = pixels.size
    if not (0 <= y < height):
        raise RuntimeError("menu scan line is outside the screenshot")
    beginning = None
    last_light = None
    gap = 0
    limit = min(width, start_x + max_width)
    for x in range(max(0, start_x), limit):
        if _is_menu_light(pixels.getpixel((x, y))):
            if beginning is None:
                beginning = x
            last_light = x
            gap = 0
        elif beginning is not None:
            gap += 1
            if gap > 55:
                break
    if beginning is None or last_light is None or last_light - beginning < 100:
        raise RuntimeError("unable to detect native menu extent at y={}".format(y))
    return beginning, last_light + 1


def _detect_root_menu(screenshot, anchor):
    from PIL import Image

    image = Image.open(str(screenshot))
    anchor_x, anchor_y = anchor
    errors = []
    for delta_y in (78, 104, 130, 156):
        try:
            left, right = _scan_light_extent(image, anchor_y + delta_y, anchor_x - 3)
        except RuntimeError as error:
            errors.append(str(error))
            continue
        if left <= anchor_x + 12 and right >= anchor_x + 150:
            return (anchor_x, anchor_y, right, min(image.height, anchor_y + 420))
    raise RuntimeError("unable to detect root context menu: {}".format("; ".join(errors)))


def _detect_submenu(screenshot, root_box, parent_row, row_count):
    from PIL import Image

    image = Image.open(str(screenshot))
    root_left, root_top, root_right, _ = root_box
    del root_left
    submenu_top = root_top + parent_row * MENU_ROW_HEIGHT
    scan_y = submenu_top + MENU_ROW_HEIGHT // 2
    left, right = _scan_light_extent(image, scan_y, root_right - 4)
    if left < root_right - 8:
        left = root_right - 2
    return (left, submenu_top, right, submenu_top + row_count * MENU_ROW_HEIGHT)


def _click_absolute(display, point, button=1):
    x, y = point
    _run_xdotool(display, ["mousemove", "--sync", str(x), str(y)])
    _run_xdotool(display, ["click", str(button)])


def _right_click_target(display, window_id, target):
    frame_extents = _window_frame_extents(display, window_id)
    x, y = adjust_window_target(target, frame_extents)
    _run_xdotool(
        display,
        ["mousemove", "--sync", "--window", window_id, str(x), str(y)],
    )
    anchor = _mouse_location(display)
    _run_xdotool(display, ["click", "3"])
    return anchor, frame_extents


def _case_state(response):
    return {
        "text_sha256": response["text_sha256"],
        "selections": response["selections"],
        "change_count": response["change_count"],
        "clipboard": response["clipboard"],
    }


def _wait_for_clipboard(client, expected, timeout=7.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.request("snapshot", timeout=2.0)
        if last.get("clipboard") == expected:
            return last
        time.sleep(0.08)
    raise RuntimeError(
        "clipboard did not become {!r}; last value was {!r}".format(
            expected, None if last is None else last.get("clipboard")
        )
    )


def _selection_at_menu(events, setup, menu_action_time):
    candidates = [
        event
        for event in events
        if isinstance(event.get("monotonic"), (int, float))
        and event["monotonic"] <= menu_action_time
    ]
    if not candidates:
        return {
            "selections": setup["selections"],
            "text_sha256": setup["text_sha256"],
            "source": "setup-state-no-right-click-selection-event",
        }
    selected = candidates[-1]
    return {
        "selections": selected["selections"],
        "text_sha256": selected["text_sha256"],
        "source": "selection-event-after-menu-open",
    }


def _setup_case(client, title, text, syntax, selections, target_offsets, clipboard, settings=None):
    return client.request(
        "setup",
        title=title,
        text=text,
        syntax=syntax,
        selections=selections,
        target_offsets=target_offsets,
        clipboard=clipboard,
        settings=settings or {},
        timeout=10.0,
    )


def _native_case(
    client,
    display,
    window_id,
    output,
    name,
    text,
    syntax,
    selections,
    target_offset,
    expected,
    menu_style,
    settings=None,
):
    sentinel = "COPY_PATH_RUNTIME_SENTINEL_{}".format(name)
    setup = _setup_case(
        client,
        "CopyPath Runtime — {}".format(name),
        text,
        syntax,
        selections,
        [target_offset],
        sentinel,
        settings=settings,
    )
    _activate_window(display, window_id)
    geometry = client.request("geometry", target_offsets=[target_offset])
    target = geometry["targets"][0]
    anchor, frame_extents = _right_click_target(display, window_id, target)
    time.sleep(0.45)
    root_name = "{}-context.png".format(name)
    root_path = output / root_name
    _capture_screenshot(display, root_path)
    root_box = _detect_root_menu(root_path, anchor)
    menu_snapshot = client.request("snapshot", timeout=0.45, optional=True)

    submenu_path = None
    submenu_box = None
    if menu_style == "auto":
        action_point = menu_row_point(root_box, 0)
    else:
        parent_row = 0 if settings and settings.get('show_in_context_menu') is False else 1
        parent_point = menu_row_point(root_box, parent_row)
        _run_xdotool(
            display,
            ["mousemove", "--sync", str(parent_point[0]), str(parent_point[1])],
        )
        time.sleep(0.45)
        submenu_name = "{}-submenu.png".format(name)
        submenu_path = output / submenu_name
        _capture_screenshot(display, submenu_path)
        if menu_style == "pointer":
            submenu_box = _detect_submenu(submenu_path, root_box, 1, 2)
            action_point = menu_row_point(submenu_box, 1)
        elif menu_style in ('xpath', 'xpath_text'):
            submenu_box = _detect_submenu(submenu_path, root_box, 1, 4)
            action_point = menu_row_point(submenu_box, 1 if menu_style == 'xpath' else 2)
        elif menu_style == 'settings':
            submenu_box = _detect_submenu(submenu_path, root_box, parent_row, 1)
            action_point = menu_row_point(submenu_box, 0)
        else:
            raise RuntimeError("unsupported native menu style {}".format(menu_style))
    menu_action_time = time.monotonic()
    _click_absolute(display, action_point)
    after = _wait_for_clipboard(client, expected)
    if menu_style == 'settings':
        deadline = time.monotonic() + 5.0
        while not after.get('settings_open') and time.monotonic() < deadline:
            time.sleep(0.08)
            after = client.request('snapshot')
        if not after.get('settings_open'):
            raise RuntimeError('Settings menu did not open package settings')
    events = after.get("selection_events", [])
    menu_state = None
    if (
        menu_snapshot is not None
        and menu_snapshot.get("monotonic", math.inf) <= menu_action_time
    ):
        menu_state = {
            "selections": menu_snapshot["selections"],
            "text_sha256": menu_snapshot["text_sha256"],
            "source": "live-snapshot-while-menu-open",
        }
    if menu_state is None:
        menu_state = _selection_at_menu(events, setup, menu_action_time)
    source_preserved = (
        after["text_sha256"] == menu_state["text_sha256"]
        and after["selections"] == menu_state["selections"]
        and after["change_count"] == setup["change_count"]
    )
    screenshots = [
        {
            "file": root_name,
            "sha256": sha256_file(root_path),
            "kind": "root-context-menu",
        }
    ]
    if submenu_path is not None:
        screenshots.append(
            {
                "file": submenu_path.name,
                "sha256": sha256_file(submenu_path),
                "kind": "submenu",
            }
        )
    return {
        "name": name,
        "passed": after["clipboard"] == expected and source_preserved,
        "expected_clipboard": expected,
        "clipboard": after["clipboard"],
        "source_preserved": source_preserved,
        "before": _case_state(setup),
        "menu_open": menu_state,
        "after": _case_state(after),
        "right_click_changed_selection": setup["selections"] != menu_state["selections"],
        "event_target": {"offset": target_offset, "window": target, "screen": list(anchor)},
        "window_frame_extents": list(frame_extents),
        "root_menu_box": list(root_box),
        "submenu_box": None if submenu_box is None else list(submenu_box),
        "menu_action_screen": list(action_point),
        "screenshots": screenshots,
        "settings_open": after.get('settings_open', False),
    }


def _command_case(
    client,
    name,
    text,
    syntax,
    selections,
    expected,
    style="auto",
    settle_ms=0,
    expected_status=None,
):
    sentinel = "COPY_PATH_RUNTIME_SENTINEL_{}".format(name)
    setup = _setup_case(
        client,
        "CopyPath Runtime — {}".format(name),
        text,
        syntax,
        selections,
        [],
        sentinel,
    )
    response = client.request(
        "run_command",
        style=style,
        expected_clipboard=expected,
        expected_status=expected_status,
        settle_ms=settle_ms,
        timeout_ms=6500,
        timeout=9.0,
    )
    source_preserved = (
        setup["text_sha256"] == response["text_sha256"]
        and setup["selections"] == response["selections"]
        and setup["change_count"] == response["change_count"]
    )
    return {
        "name": name,
        "passed": response["clipboard"] == expected and source_preserved
                  and (expected_status is None or expected_status in response.get('status_messages', [])),
        "expected_clipboard": expected,
        "clipboard": response["clipboard"],
        "source_preserved": source_preserved,
        "before": _case_state(setup),
        "after": _case_state(response),
        "elapsed_ms": response.get("elapsed_ms"),
        "package_modules": response.get("package_modules", {}),
        "status_messages": response.get('status_messages', []),
    }


def _wait_for_json(path, editor, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if editor.poll() is not None:
            raise RuntimeError("Sublime exited before the runtime driver became ready")
        time.sleep(0.08)
    raise RuntimeError("timed out waiting for {}".format(path.name))


def _start_xvfb(log_handle, processes):
    read_fd, write_fd = os.pipe()
    try:
        xvfb = processes.add(
            subprocess.Popen(
                [
                    "Xvfb",
                    "-displayfd",
                    str(write_fd),
                    "-screen",
                    "0",
                    "1440x1000x24",
                    "-nolisten",
                    "tcp",
                ],
                pass_fds=(write_fd,),
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )
        )
    finally:
        os.close(write_fd)
    readable, _, _ = select.select([read_fd], [], [], 10.0)
    if not readable:
        os.close(read_fd)
        raise RuntimeError("Xvfb did not allocate a display")
    with os.fdopen(read_fd, "r", encoding="ascii") as pipe:
        display_number = pipe.readline().strip()
    if not display_number or xvfb.poll() is not None:
        raise RuntimeError("Xvfb failed to start")
    return ":" + display_number


def run_acceptance(args):
    package_archive = args.archive.resolve()
    sublime_archive = args.sublime_archive.resolve()
    driver = (ROOT / "tools" / "runtime_driver.py").resolve()
    if not package_archive.is_file():
        raise RuntimeError("candidate archive is missing: {}".format(package_archive))
    if package_archive.name != "CopyPath.sublime-package":
        raise RuntimeError("candidate archive must be named CopyPath.sublime-package")
    if not driver.is_file():
        raise RuntimeError("runtime driver is missing: {}".format(driver))
    if not sublime_archive.is_file():
        raise RuntimeError("official Sublime archive is missing: {}".format(sublime_archive))
    sublime_sha256 = sha256_file(sublime_archive)
    if sublime_sha256 != EXPECTED_SUBLIME_ARCHIVE_SHA256:
        raise RuntimeError(
            "Sublime archive checksum mismatch: expected {}, got {}".format(
                EXPECTED_SUBLIME_ARCHIVE_SHA256, sublime_sha256
            )
        )
    package_sha256 = sha256_file(package_archive)
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("refusing to reuse existing evidence directory: {}".format(output))
    output.mkdir(parents=True)

    temporary_parent = args.work_root.resolve() if args.work_root else Path(os.environ.get("TMPDIR", tempfile.gettempdir()))
    temporary_parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="copy-path-runtime-", dir=str(temporary_parent)))
    protocol = work / "protocol"
    protocol.mkdir()
    home = work / "home"
    home.mkdir()
    processes = ProcessGroup()
    cleanup_issues = []
    report = {
        "passed": False,
        "expected_build": EXPECTED_BUILD,
        "archive_sha256": package_sha256,
        "sublime_archive_sha256": sublime_sha256,
        "cases": [],
    }
    try:
        sublime_dir = extract_sublime_archive(sublime_archive, work / "portable")
        prepare_profile(sublime_dir, package_archive, driver, protocol)
        binary = sublime_dir / "sublime_text"
        log_path = output / "editor.log"
        with log_path.open("w", encoding="utf-8") as log:
            display = _start_xvfb(log, processes)
            desktop_env = dict(os.environ)
            desktop_env["DISPLAY"] = display
            desktop_env["HOME"] = str(home)
            processes.add(
                subprocess.Popen(
                    ["openbox", "--sm-disable"],
                    env=desktop_env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            )
            editor_env = build_editor_env(desktop_env, display, protocol)
            editor = processes.add(
                subprocess.Popen(
                    [str(binary), "--multiinstance"],
                    env=editor_env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            )
            ready = _wait_for_json(protocol / "driver-ready.json", editor, args.startup_timeout)
            if ready.get("ready") is not True:
                raise RuntimeError(ready.get("error", "runtime driver did not become ready"))
            client = ControlClient(protocol, editor)

            json_text = (
                "{\n"
                "  \"caret\": \"elsewhere\",\n"
                "  \"catalog\": [\n"
                "    {\"id\": 1, \"label\": \"first\"},\n"
                "    {\"id\": 2, \"label\": \"東京😀\"}\n"
                "  ]\n"
                "}\n"
            )
            caret = json_text.index("elsewhere")
            target = json_text.index("東京")
            first_setup = _setup_case(
                client,
                "CopyPath Runtime — bootstrap",
                json_text,
                "Packages/JSON/JSON.sublime-syntax",
                [[caret, caret]],
                [target],
                "COPY_PATH_RUNTIME_BOOTSTRAP",
            )
            del first_setup
            window_id = _find_window(display)
            _activate_window(display, window_id)

            report["cases"].append(
                _native_case(
                    client,
                    display,
                    window_id,
                    output,
                    "mouse_auto_json",
                    json_text,
                    "Packages/JSON/JSON.sublime-syntax",
                    [[caret, caret]],
                    target,
                    "$.catalog[1].label",
                    "auto",
                )
            )

            pointer_text = (
                "{\n"
                "  \"caret\": \"elsewhere\",\n"
                "  \"a/b\": {\"~key\": [0, {\"value\": \"target\"}]}\n"
                "}\n"
            )
            report["cases"].append(
                _native_case(
                    client,
                    display,
                    window_id,
                    output,
                    "mouse_pointer_json",
                    pointer_text,
                    "Packages/JSON/JSON.sublime-syntax",
                    [[pointer_text.index("elsewhere"), pointer_text.index("elsewhere")]],
                    pointer_text.index("target"),
                    "/a~1b/~0key/1/value",
                    "pointer",
                )
            )

            xml_text = (
                "<root>\n"
                "  <item id=\"first\"/>\n"
                "  <item id=\"second\">value</item>\n"
                "</root>\n"
            )
            report["cases"].append(
                _native_case(
                    client,
                    display,
                    window_id,
                    output,
                    "mouse_xpath_xml_attribute",
                    xml_text,
                    "Packages/XML/XML.sublime-syntax",
                    [[xml_text.index("value"), xml_text.index("value")]],
                    xml_text.index("second"),
                    "/root[1]/item[2]/@id",
                    "xpath",
                )
            )

            books = '<catalog><book id="a"/><book id="b">Title</book></catalog>'
            for name, style in [('mouse_auto_xml', 'auto'), ('mouse_text_xml', 'xpath_text')]:
                report['cases'].append(_native_case(
                    client, display, window_id, output, name, books,
                    'Packages/XML/XML.sublime-syntax', [[1, 1]], books.index('Title'),
                    EXPECTED_CLIPBOARDS[name], style))
            incomplete = books[:-len('</catalog>')]
            point = incomplete.index('Title')
            report['cases'].append(_command_case(
                client, 'incomplete_xml', incomplete, 'Packages/XML/XML.sublime-syntax',
                [[point, point]], EXPECTED_CLIPBOARDS['incomplete_xml'],
                expected_status='Copied positional XPath from incomplete XML.'))

            unicode_text = (
                '{"users":[{"name":"Åsa"},{"name":"李"}],'
                '"ключ":{"emoji":"😀"}}'
            )
            unicode_expected = '$.users[0].name\n$["\\u043a\\u043b\\u044e\\u0447"].emoji'
            unicode_case = _command_case(
                client,
                "caret_multiple_unicode",
                unicode_text,
                "Packages/JSON/JSON.sublime-syntax",
                [
                    [unicode_text.index("Åsa"), unicode_text.index("Åsa")],
                    [unicode_text.index("😀"), unicode_text.index("😀")],
                ],
                unicode_expected,
            )
            report["cases"].append(unicode_case)

            yaml_text = "root:\n  items:\n    - name: Ada\n      city: Zürich\n"
            yaml_case = _command_case(
                client,
                "yaml_archive_import",
                yaml_text,
                "Packages/YAML/YAML.sublime-syntax",
                [[yaml_text.index("Zürich"), yaml_text.index("Zürich")]],
                "$.root.items[0].city",
            )
            yaml_modules = yaml_case.get("package_modules", {})
            yaml_paths = {
                name: path
                for name, path in yaml_modules.items()
                if "yaml" in name.lower()
            }
            yaml_case["yaml_modules"] = yaml_paths
            yaml_case["yaml_imports_from_archive"] = bool(yaml_paths) and all(
                "CopyPath.sublime-package" in path for path in yaml_paths.values()
            )
            yaml_case["passed"] = yaml_case["passed"] and yaml_case["yaml_imports_from_archive"]
            report["cases"].append(yaml_case)

            malformed_text = '{"a": [1,}\n'
            malformed_sentinel = "MALFORMED_CLIPBOARD_MUST_SURVIVE"
            setup = _setup_case(
                client,
                "CopyPath Runtime — malformed_preserves_clipboard",
                malformed_text,
                "Packages/JSON/JSON.sublime-syntax",
                [[malformed_text.index("1"), malformed_text.index("1")]],
                [],
                malformed_sentinel,
            )
            after = client.request(
                "run_command",
                style="auto",
                expected_clipboard=malformed_sentinel,
                expected_status="Invalid JSON document.",
                settle_ms=900,
                timeout_ms=3000,
                timeout=5.0,
            )
            malformed_case = {
                    "passed": after["clipboard"] == malformed_sentinel
                    and after.get("status_messages") == ["Invalid JSON document."]
                    and setup["text_sha256"] == after["text_sha256"]
                    and setup["selections"] == after["selections"]
                    and setup["change_count"] == after["change_count"],
                    "expected_clipboard": malformed_sentinel,
                    "clipboard": after["clipboard"],
                    "source_preserved": setup["text_sha256"] == after["text_sha256"]
                    and setup["selections"] == after["selections"]
                    and setup["change_count"] == after["change_count"],
                    "before": _case_state(setup),
                    "after": _case_state(after),
                    "elapsed_ms": after.get("elapsed_ms"),
                    "name": "malformed_preserves_clipboard",
                    "status_messages": after.get("status_messages", []),
                }
            report["cases"].append(malformed_case)
            for name, settings in [
                ('mouse_submenu_disabled', {'show_copy_path_as_submenu': False}),
                ('mouse_context_disabled', {'show_in_context_menu': False}),
            ]:
                report['cases'].append(_native_case(
                    client, display, window_id, output, name, books,
                    'Packages/XML/XML.sublime-syntax', [[1, 1]], books.index('Title'),
                    EXPECTED_CLIPBOARDS[name], 'settings', settings=settings))
            client.request("close", timeout=3.0)

            report.update(
                {
                    "build": ready["build"],
                    "python": ready["python"],
                    "platform": ready["platform"],
                    "archive_only": ready["archive_only"],
                    "plugin_module": ready["plugin_module"],
                    "probe_module": ready["probe_module"],
                    "environment": ready["environment"],
                    "installed_archive": ready["archive"],
                    "installed_archive_sha256": ready["archive_sha256"],
                    "display": display,
                    "window_id": window_id,
                }
            )
            failed = [case["name"] for case in report["cases"] if not case.get("passed")]
            if failed:
                raise RuntimeError("runtime assertions failed: {}".format(", ".join(failed)))
            report["passed"] = True
    except Exception as error:
        report["error"] = "{}: {}".format(type(error).__name__, error)
        raise
    finally:
        cleanup_issues.extend(processes.cleanup())
        report["cleanup_issues"] = cleanup_issues
        if cleanup_issues:
            report["passed"] = False
            report.setdefault("error", "runtime process cleanup failed")
        if args.keep_work:
            report["work_directory"] = str(work)
        (output / "runtime.json").write_text(
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.keep_work:
            shutil.rmtree(str(work), ignore_errors=True)
    validate_runtime_report(report, package_sha256, evidence_dir=output)
    return report


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "dist" / "CopyPath.sublime-package",
        help="exact CopyPath.sublime-package candidate",
    )
    parser.add_argument(
        "--sublime-archive",
        type=Path,
        help="official sublime_text_build_4215_x64.tar.xz",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--keep-work", action="store_true", help="retain disposable profile for debugging")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    if args.self_test:
        return run_self_tests()
    if args.sublime_archive is None or args.output is None:
        print("FAIL: --sublime-archive and --output are required", file=sys.stderr)
        return 2
    try:
        report = run_acceptance(args)
    except Exception as error:
        print("FAIL: {}".format(error), file=sys.stderr)
        return 1
    print(
        "PASS: Sublime {} / Python {} / {} cases / {}".format(
            report["build"],
            report["python"].split()[0],
            len(report["cases"]),
            report["archive_sha256"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
