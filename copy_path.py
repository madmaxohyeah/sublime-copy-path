"""Sublime Text adapter; all source parsing is off the UI thread."""
import itertools
import math
from collections import namedtuple

import sublime
import sublime_plugin

from .copy_path_lib.engine import FORMATS, detect_format, resolve_with_status
from .copy_path_lib.model import MAX_CARETS, MAX_CHARS, PathError

_REQUEST_IDS = itertools.count()
_pending = {}
_Config = namedtuple('_Config', 'format json_style xml_style limit context_menu submenu')


def _valid_format(value):
    return isinstance(value, str) and value in ('auto',) + FORMATS


def _config(view):
    """Validated settings; any malformed value falls back to its default."""
    settings = sublime.load_settings('CopyPath.sublime-settings')
    # A view/project copy_path_format overrides the global format; an invalid
    # value at either level is ignored instead of hiding a valid global one.
    override = view.settings().get('copy_path_format')
    if not _valid_format(override):
        override = settings.get('format', 'auto')
        if not _valid_format(override):
            override = 'auto'
    style = settings.get('json_path_style', 'jsonpath')
    if not isinstance(style, str) or style not in ('jsonpath', 'pointer'):
        style = 'jsonpath'
    xml_style = settings.get('xml_path_style', 'attributes')
    if not isinstance(xml_style, str) or xml_style not in ('attributes', 'positional', 'text'):
        xml_style = 'attributes'
    limit = settings.get('max_file_chars', MAX_CHARS)
    if type(limit) is not int or not 1 <= limit <= MAX_CHARS:
        limit = MAX_CHARS
    visible = settings.get('show_in_context_menu', True)
    if type(visible) is not bool:
        visible = True
    submenu = settings.get('show_copy_path_as_submenu', True)
    if type(submenu) is not bool:
        submenu = True
    return _Config(override, style, xml_style, limit, visible, submenu)


def _format(view, config=None):
    """Document kind for this view (json, jsonc, xml, yaml) or None if unsupported."""
    syntax = view.syntax()
    override = (config or _config(view)).format
    return detect_format(view.file_name(), syntax.scope if syntax else '', override)


def _selections(view):
    return tuple((region.a, region.b) for region in view.sel())


def _message(message):
    sublime.status_message('Copy Path: ' + message)


class CopyPathMenuCommand(sublime_plugin.TextCommand):
    """Visibility check for the Copy Path As submenu heading; running it does nothing.

    Linux hides the heading outside JSON, YAML and XML files. In supported files
    it stays even when show_in_context_menu is false, so Settings... remains
    reachable to turn copying back on. Windows and macOS always show submenu
    headings, so Settings... also keeps the submenu from being empty there.
    """

    def run(self, edit):
        pass

    def is_visible(self):
        return bool(not self.view.element() and _format(self.view) is not None)


class CopyElementPathCommand(sublime_plugin.TextCommand):
    """Copy the path at the clicked point (context menu) or at every caret (palette).

    ``context`` is true only for context-menu entries, so the visibility
    settings never hide Command Palette actions. Parsing runs on the async
    thread; a newer request, an edit, a selection change or a tab switch
    discards the result instead of overwriting the clipboard late.
    """

    def want_event(self):
        return True

    def is_visible(self, style='auto', event=None, context=False):
        config = _config(self.view)
        if self.view.element() or (context and not config.context_menu):
            return False
        if context and style != 'auto' and not config.submenu:
            return False
        kind = _format(self.view, config)
        if kind is None:
            return False
        return style in (('auto', 'xpath', 'xpath_attributes', 'xpath_positional', 'xpath_text')
                         if kind == 'xml' else ('auto', 'jsonpath', 'pointer'))

    def is_enabled(self, style='auto', event=None, context=False):
        return self.is_visible(style, event, context)

    def run(self, edit, style='auto', event=None, context=False):
        view = self.view
        token = next(_REQUEST_IDS)
        view_id = view.id()
        # The clipboard is global: a newer request in ANY view supersedes all others.
        _pending.clear()
        _pending[view_id] = token  # Even a failed new request invalidates an old one.
        try:
            config = _config(view)
            kind = _format(view, config)
            if kind is None or view.element():
                raise PathError('Choose JSON, JSONC, XML or YAML syntax first.')
            if view.size() > config.limit:
                raise PathError('Document exceeds the configured {}-character limit.'.format(config.limit))
            selections = _selections(view)
            if isinstance(event, dict) and all(
                type(event.get(key)) in (int, float) and math.isfinite(event[key])
                for key in ('x', 'y')
            ):
                points = [view.window_to_text((event['x'], event['y']))]
            else:
                if not selections or len(selections) > MAX_CARETS:
                    raise PathError('Choose between 1 and {} carets.'.format(MAX_CARETS))
                # The active end of each selection; the engine attaches a caret
                # that ends a value (e.g. after a double-click) to that value.
                points = [end for _, end in selections]
            if style == 'auto':
                style = 'xpath_' + config.xml_style if kind == 'xml' else config.json_style
            version = view.change_count()
            text = view.substr(sublime.Region(0, view.size()))
        except PathError as error:
            _pending.pop(view_id, None)
            _message(str(error))
            return

        def finish(result, error):
            if _pending.get(view_id) != token:
                return
            _pending.pop(view_id, None)
            if (not view.is_valid() or view.change_count() != version
                    or _selections(view) != selections or not view.window()
                    or sublime.active_window() != view.window()
                    or view.window().active_view() != view or _format(view) != kind):
                return
            if error is not None:
                _message(error)
                return
            sublime.set_clipboard('\n'.join(result.paths))
            if result.recovered:
                _message('Copied positional XPath from incomplete XML.')
            elif result.paths == ['']:
                _message('Copied document root (empty JSON Pointer).')
            else:
                _message('Copied {} path{}.'.format(len(result.paths), '' if len(result.paths) == 1 else 's'))

        def work():
            if _pending.get(view_id) != token:
                return
            try:
                result = resolve_with_status(text, points, kind, style)
            except PathError as error:
                message = str(error)
                sublime.set_timeout(lambda: finish(None, message))
            except Exception:
                # Never log the document or parser exception, which may include source.
                sublime.set_timeout(lambda: finish(None, 'Unable to resolve this document safely.'))
            else:
                sublime.set_timeout(lambda: finish(result, None))

        sublime.set_timeout_async(work)


class CopyPathLifecycle(sublime_plugin.EventListener):
    def on_close(self, view):
        _pending.pop(view.id(), None)


def plugin_unloaded():
    _pending.clear()
