"""Real Sublime Text probe for the CopyPath installed-archive smoke test.

This file is copied into a separate ``CopyPathRuntimeProbe`` package in a fresh
portable Sublime profile. It is never included in ``CopyPath.sublime-package``.
The host harness communicates through small JSON request/response files so the
only UI automation needed for product behavior is the native context menu.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import sublime
import sublime_plugin


OUTPUT = Path(os.environ.get("COPY_PATH_RUNTIME_EVIDENCE", ".")).resolve()
CONTROL = OUTPUT / "control.json"
RESPONSES = OUTPUT / "responses"
READY = OUTPUT / "driver-ready.json"
POLL_MS = 40
START_DEADLINE = time.monotonic() + 60.0

_last_request = None
_current_view = None
_stopped = False
_selection_events = []


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def _selections(view):
    return [[region.a, region.b] for region in view.sel()]


def _text(view):
    return view.substr(sublime.Region(0, view.size()))


def _package_modules():
    result = {}
    for name, module in sorted(sys.modules.items()):
        if name == "CopyPath" or name.startswith("CopyPath."):
            location = getattr(module, "__file__", None)
            if location:
                result[name] = location
    return result


def _settings_open():
    return any(
        (item.file_name() or '').replace('\\', '/').endswith('/Packages/User/CopyPath.sublime-settings')
        for window in sublime.windows() for item in window.views()
    )


def _snapshot(view=None):
    view = view or _current_view
    if view is None or not view.is_valid():
        return {
            "active": False,
            "clipboard": sublime.get_clipboard(),
            "monotonic": time.monotonic(),
            "selection_events": list(_selection_events),
            "package_modules": _package_modules(),
        }
    text = _text(view)
    syntax = view.syntax()
    return {
        "active": bool(view.window() and view.window().active_view() == view),
        "view_id": view.id(),
        "name": view.name(),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_length": len(text),
        "selections": _selections(view),
        "change_count": view.change_count(),
        "clipboard": sublime.get_clipboard(),
        "syntax": syntax.scope if syntax else None,
        "settings_open": _settings_open(),
        "monotonic": time.monotonic(),
        "selection_events": list(_selection_events),
        "package_modules": _package_modules(),
    }


def _geometry(view, offsets):
    targets = []
    for offset in offsets:
        x, y = view.text_to_window(offset)
        targets.append(
            {
                "offset": offset,
                "x": x + view.em_width() / 2.0,
                "y": y + view.line_height() / 2.0,
            }
        )
    return {
        "targets": targets,
        "line_height": view.line_height(),
        "em_width": view.em_width(),
        "viewport_extent": list(view.viewport_extent()),
    }


def _response(request_id, payload):
    body = {"id": request_id, "ok": True}
    body.update(payload)
    _atomic_json(RESPONSES / (str(request_id) + ".json"), body)


def _error_response(request_id):
    _atomic_json(
        RESPONSES / (str(request_id) + ".json"),
        {"id": request_id, "ok": False, "error": traceback.format_exc()},
    )


def _setup(request_id, request):
    global _current_view, _selection_events
    window = _current_view.window() if _current_view is not None and _current_view.is_valid() else sublime.active_window()
    if window is None:
        raise RuntimeError("Sublime has no active window")
    # The probe only ever drives this disposable test profile.
    for other in sublime.windows():
        if other != window:
            for previous in other.views():
                previous.set_scratch(True)
            other.run_command('close_window')
    window.bring_to_front()
    for previous in list(window.views()):
        previous.set_scratch(True)
        previous.close()
    window.set_layout({'cols': [0.0, 1.0], 'rows': [0.0, 1.0], 'cells': [[0, 0, 1, 1]]})
    settings = sublime.load_settings('CopyPath.sublime-settings')
    for key in ('show_in_context_menu', 'show_copy_path_as_submenu', 'xml_path_style'):
        settings.erase(key)
    for key, value in request.get('settings', {}).items():
        settings.set(key, value)
    view = window.new_file()
    _current_view = view
    _selection_events = []
    view.set_scratch(True)
    view.set_name(request.get("title", "CopyPath Runtime Acceptance"))
    view.settings().set("font_size", 18)
    view.settings().set("word_wrap", False)
    syntax = request["syntax"]
    view.assign_syntax(syntax)
    view.run_command("append", {"characters": request["text"]})
    view.sel().clear()
    for a, b in request["selections"]:
        view.sel().add(sublime.Region(a, b))
    window.focus_view(view)
    sublime.status_message("")
    offsets = request.get("target_offsets", [])
    if offsets:
        view.show(offsets[0], True)
    sublime.set_clipboard(request.get("clipboard", "COPY_PATH_RUNTIME_SENTINEL"))

    def finish_setup():
        payload = _snapshot(view)
        payload.update(_geometry(view, offsets))
        _response(request_id, payload)

    sublime.set_timeout(finish_setup, 250)


def _run_command(request_id, request):
    view = _current_view
    if view is None or not view.is_valid():
        raise RuntimeError("No runtime view is active")
    arguments = {}
    style = request.get("style")
    if style is not None:
        arguments["style"] = style
    plugin = importlib.import_module("CopyPath.copy_path")
    original_message = plugin._message
    status_messages = []

    def observe_message(message):
        status_messages.append(message)
        original_message(message)

    plugin._message = observe_message
    try:
        view.run_command("copy_element_path", arguments)
    except Exception:
        plugin._message = original_message
        raise
    expected = request.get("expected_clipboard")
    expected_status = request.get("expected_status")
    settle_ms = int(request.get("settle_ms", 0))
    timeout_ms = int(request.get("timeout_ms", 6000))
    started = time.monotonic()

    def check():
        elapsed_ms = int((time.monotonic() - started) * 1000)
        clipboard = sublime.get_clipboard()
        status_ready = expected_status is None or expected_status in status_messages
        if (expected is not None and clipboard == expected and status_ready
                and elapsed_ms >= settle_ms) or elapsed_ms >= timeout_ms:
            plugin._message = original_message
            payload = _snapshot(view)
            payload["elapsed_ms"] = elapsed_ms
            payload["expected_clipboard"] = expected
            payload["status_messages"] = list(status_messages)
            _response(request_id, payload)
        else:
            sublime.set_timeout(check, 40)

    sublime.set_timeout(check, max(40, settle_ms))


def _dispatch(request):
    request_id = request["id"]
    operation = request.get("operation")
    if operation == "setup":
        _setup(request_id, request)
    elif operation == "snapshot":
        _response(request_id, _snapshot())
    elif operation == "geometry":
        view = _current_view
        if view is None or not view.is_valid():
            raise RuntimeError("No runtime view is active")
        payload = _snapshot(view)
        payload.update(_geometry(view, request.get("target_offsets", [])))
        _response(request_id, payload)
    elif operation == "run_command":
        _run_command(request_id, request)
    elif operation == "close":
        view = _current_view
        payload = _snapshot(view)
        if view is not None and view.is_valid():
            view.close()
        _response(request_id, payload)
    else:
        raise RuntimeError("Unknown runtime probe operation: {!r}".format(operation))


def _poll_control():
    global _last_request
    if _stopped:
        return
    try:
        if CONTROL.is_file():
            request = json.loads(CONTROL.read_text(encoding="utf-8"))
            request_id = request.get("id")
            if request_id is not None and request_id != _last_request:
                _last_request = request_id
                try:
                    _dispatch(request)
                except Exception:
                    _error_response(request_id)
    finally:
        sublime.set_timeout(_poll_control, POLL_MS)


def _write_ready():
    try:
        plugin = importlib.import_module("CopyPath.copy_path")
        archive = Path(sublime.installed_packages_path()) / "CopyPath.sublime-package"
        unpacked = Path(sublime.packages_path()) / "CopyPath"
        metadata = {
            "ready": True,
            "build": sublime.version(),
            "python": sys.version,
            "platform": sublime.platform(),
            "archive": str(archive),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archive_only": archive.is_file() and not unpacked.exists(),
            "plugin_module": getattr(plugin, "__file__", None),
            "probe_module": __file__,
            "installed_packages": sublime.installed_packages_path(),
            "packages": sublime.packages_path(),
            "environment": {
                name: os.environ.get(name)
                for name in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH")
            },
            "monotonic": time.monotonic(),
        }
    except Exception:
        if time.monotonic() < START_DEADLINE:
            sublime.set_timeout(_write_ready, 200)
            return
        metadata = {
            "ready": False,
            "build": sublime.version(),
            "python": sys.version,
            "error": traceback.format_exc(),
        }
    _atomic_json(READY, metadata)
    _poll_control()


class CopyPathRuntimeSelectionListener(sublime_plugin.EventListener):
    def on_selection_modified(self, view):
        if _current_view is None or view.id() != _current_view.id():
            return
        text = _text(view)
        _selection_events.append(
            {
                "monotonic": time.monotonic(),
                "selections": _selections(view),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        del _selection_events[:-32]


def plugin_loaded():
    if os.environ.get("COPY_PATH_RUNTIME_EVIDENCE"):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        RESPONSES.mkdir(parents=True, exist_ok=True)
        sublime.set_timeout(_write_ready, 500)


def plugin_unloaded():
    global _stopped
    _stopped = True
