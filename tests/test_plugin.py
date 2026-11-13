"""Tests fake only the editor boundary; parser tests use real documents."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Settings(dict):
    def set(self, key, value):
        self[key] = value


class Region:
    def __init__(self, a, b=None):
        self.a, self.b = a, a if b is None else b


class View:
    def __init__(self, view_id=1):
        self.text = '{"a":1,"b":2}'
        self.selections = [Region(5)]
        self.config = Settings()
        self.version = 0
        self.valid = True
        self.scope = 'source.json'
        self.filename = None
        self.widget = None
        self.active = self
        self.view_id = view_id
        self.host_window = types.SimpleNamespace(active_view=lambda: self.active)
    def id(self): return self.view_id
    def size(self): return len(self.text)
    def change_count(self): return self.version
    def sel(self): return self.selections
    def substr(self, region): return self.text[region.a:region.b]
    def settings(self): return self.config
    def syntax(self): return types.SimpleNamespace(scope=self.scope)
    def file_name(self): return self.filename
    def element(self): return self.widget
    def window_to_text(self, coords): return int(coords[0])
    def is_valid(self): return self.valid
    def window(self): return self.host_window


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.clipboard = 'previous'
        self.messages = []
        self.async_queue = []
        self.ui_queue = []
        self.settings = Settings()
        sublime = types.ModuleType('sublime')
        sublime.Region = Region
        sublime.load_settings = lambda name: self.settings
        sublime.set_clipboard = lambda value: setattr(self, 'clipboard', value)
        sublime.status_message = self.messages.append
        sublime.set_timeout_async = lambda fn, delay=0: self.async_queue.append(fn)
        sublime.set_timeout = lambda fn, delay=0: self.ui_queue.append(fn)
        sublime.active_window = lambda: self.active_window
        plugin = types.ModuleType('sublime_plugin')
        class TextCommand:
            def __init__(self, view): self.view = view
        plugin.TextCommand = TextCommand
        plugin.EventListener = object
        package = types.ModuleType('CopyPath')
        package.__path__ = [str(ROOT)]
        self.patcher = patch.dict(sys.modules, {'sublime': sublime, 'sublime_plugin': plugin, 'CopyPath': package})
        self.patcher.start()
        spec = importlib.util.spec_from_file_location('CopyPath.copy_path', ROOT / 'copy_path.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.view = View()
        self.active_window = self.view.window()
        self.command = self.module.CopyElementPathCommand(self.view)
        self.calls = []
        def resolver(text, points, kind, style):
            self.calls.append((text, points, kind, style))
            return types.SimpleNamespace(paths=['P' + str(point) for point in dict.fromkeys(points)], recovered=False)
        self.module.resolve_with_status = resolver
    def tearDown(self): self.patcher.stop()
    def flush(self):
        while self.async_queue: self.async_queue.pop(0)()
        while self.ui_queue: self.ui_queue.pop(0)()
    def test_mouse_overrides_caret_without_edit(self):
        self.assertTrue(self.command.want_event())
        before = self.view.text, [(r.a, r.b) for r in self.view.sel()]
        self.command.run(None, event={'x': 10, 'y': 15}, context=True)
        self.assertEqual(self.clipboard, 'previous')
        self.flush()
        self.assertEqual(self.clipboard, 'P10')
        self.assertEqual(before, (self.view.text, [(r.a, r.b) for r in self.view.sel()]))
    def test_palette_uses_all_active_selection_ends(self):
        self.view.selections = [Region(10, 2), Region(0, 9), Region(2)]
        self.command.run(None, event={'modifier_keys': {}}, style='pointer')
        self.flush()
        self.assertEqual(self.clipboard, 'P2\nP9')
        self.assertEqual(self.calls[0][3], 'pointer')
    def test_failures_preserve_clipboard(self):
        def fail(*args): raise self.module.PathError('Invalid JSON.')
        self.module.resolve_with_status = fail
        self.command.run(None)
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
        self.assertIn('Invalid JSON.', self.messages[-1])
    def test_unexpected_failure_is_source_neutral(self):
        def fail(*args): raise RuntimeError('SECRET_SOURCE')
        self.module.resolve_with_status = fail
        self.command.run(None)
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
        self.assertNotIn('SECRET_SOURCE', ' '.join(self.messages))
    def test_stale_edit_selection_view_and_tab(self):
        for mutate in [lambda: setattr(self.view, 'version', 1),
                       lambda: setattr(self.view, 'selections', [Region(2)]),
                       lambda: setattr(self.view, 'valid', False),
                       lambda: setattr(self.view, 'active', None),
                       lambda: setattr(self.view, 'scope', 'source.yaml')]:
            self.view = View()
            self.active_window = self.view.window()
            self.command = self.module.CopyElementPathCommand(self.view)
            self.command.run(None)
            self.async_queue.pop(0)()
            mutate()
            self.flush()
            self.assertEqual(self.clipboard, 'previous')
    def test_latest_request_wins(self):
        self.command.run(None, event={'x': 2, 'y': 0})
        self.async_queue.pop(0)()
        self.command.run(None, event={'x': 9, 'y': 0})
        self.flush()
        self.assertEqual(self.clipboard, 'P9')
    def test_newest_request_wins_across_windows_even_after_focus_returns(self):
        self.command.run(None, event={'x': 2, 'y': 0})
        self.async_queue.pop(0)()
        older_finish = self.ui_queue.pop(0)
        other = View(view_id=2)
        self.active_window = other.window()
        self.module.CopyElementPathCommand(other).run(None, event={'x': 9, 'y': 0})
        self.flush()
        self.assertEqual(self.clipboard, 'P9')
        self.active_window = self.view.window()
        older_finish()
        self.assertEqual(self.clipboard, 'P9')
    def test_inactive_window_cannot_change_the_clipboard(self):
        self.command.run(None)
        self.async_queue.pop(0)()
        self.active_window = View(view_id=2).window()
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
    def test_failed_new_request_in_other_window_invalidates_old_result(self):
        self.command.run(None)
        self.async_queue.pop(0)()
        other = View(view_id=2)
        self.active_window = other.window()
        self.settings['max_file_chars'] = 2
        self.module.CopyElementPathCommand(other).run(None)
        self.active_window = self.view.window()
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
    def test_target_host_xhtml_and_json_resources_are_visible_and_resolve(self):
        from copy_path_lib.engine import resolve_with_status
        self.module.resolve_with_status = resolve_with_status
        cases = [
            ('sample.xhtml', 'text.html.basic', '<html><p>text</p></html>', 9, '/html/p'),
            ('sample.sublime-completions', 'source.json', '{/*comment*/"a":1,}', 16, '$.a'),
        ]
        for filename, scope, text, point, expected in cases:
            with self.subTest(filename=filename):
                self.view.filename, self.view.scope, self.view.text = filename, scope, text
                self.view.selections = [Region(point)]
                self.assertTrue(self.command.is_visible())
                self.command.run(None)
                self.flush()
                self.assertEqual(self.clipboard, expected)
    def test_size_is_checked_before_reading_buffer(self):
        self.settings['max_file_chars'] = 2
        self.view.substr = lambda region: self.fail('oversized text must not be copied')
        self.command.run(None)
        self.flush()
        self.assertFalse(self.calls)
        self.assertEqual(self.clipboard, 'previous')
    def test_settings_validation_and_xml_style(self):
        self.settings.update(max_file_chars=True, json_path_style=['pointer'], format={'x': 1})
        self.command.run(None)
        self.flush()
        self.assertEqual(self.calls[-1][2:], ('json', 'jsonpath'))
        self.settings['json_path_style'] = 'pointer'
        self.view.scope = 'text.xml'
        self.command.run(None)
        self.flush()
        self.assertEqual(self.calls[-1][2:], ('xml', 'xpath_attributes'))
    def test_submenu_setting_hides_only_explicit_context_copy_choices(self):
        self.settings['show_copy_path_as_submenu'] = False
        self.assertTrue(self.command.is_visible(context=True))
        self.assertFalse(self.command.is_visible(style='pointer', context=True))
        self.assertFalse(self.command.is_enabled(style='pointer', context=True))
        self.assertTrue(self.command.is_visible(style='pointer'))
    def test_visibility_matrix_preserves_palette_for_all_xml_styles(self):
        self.view.scope = 'text.xml'
        for outer in (True, False):
            for submenu in (True, False):
                self.settings.update(show_in_context_menu=outer, show_copy_path_as_submenu=submenu)
                self.assertEqual(self.command.is_visible(context=True), outer)
                for style in ('xpath_attributes', 'xpath_positional', 'xpath_text', 'xpath'):
                    with self.subTest(outer=outer, submenu=submenu, style=style):
                        self.assertEqual(self.command.is_visible(style=style, context=True), outer and submenu)
                        self.assertTrue(self.command.is_visible(style=style))
                self.assertFalse(self.command.is_visible(style='jsonpath'))
    def test_invalid_view_format_falls_back_to_global_format(self):
        self.view.scope = 'text.plain'
        self.settings['format'] = 'yaml'
        self.view.config['copy_path_format'] = 'yml'
        self.assertTrue(self.command.is_visible())
        self.assertEqual(self.module._config(self.view).format, 'yaml')
        self.view.config['copy_path_format'] = 'json'
        self.assertEqual(self.module._config(self.view).format, 'json')
    def test_bad_visibility_and_xml_settings_use_safe_defaults(self):
        self.view.scope = 'text.xml'
        for bad in ('false', 0, 1, None, [], {}):
            self.settings.update(show_in_context_menu=bad, show_copy_path_as_submenu=bad, xml_path_style=bad)
            self.assertTrue(self.command.is_visible(style='xpath_attributes', context=True))
            self.command.run(None)
            self.flush()
            self.assertEqual(self.calls[-1][3], 'xpath_attributes')
    def test_xml_preferences_and_explicit_choices_are_independent(self):
        self.view.scope = 'text.xml'
        for preferred in ('attributes', 'positional', 'text'):
            self.settings['xml_path_style'] = preferred
            self.command.run(None)
            self.flush()
            self.assertEqual(self.calls[-1][3], 'xpath_' + preferred)
            for explicit in ('xpath_attributes', 'xpath_positional', 'xpath_text', 'xpath'):
                self.command.run(None, style=explicit)
                self.flush()
                self.assertEqual(self.calls[-1][3], explicit)
                self.assertEqual(self.settings['xml_path_style'], preferred)
    def test_xml_preference_does_not_change_json_default(self):
        self.settings.update(xml_path_style='text', json_path_style='pointer')
        self.command.run(None)
        self.flush()
        self.assertEqual(self.calls[-1][3], 'pointer')
    def test_recovery_metadata_reaches_status_bar(self):
        result = types.SimpleNamespace(paths=['/catalog[1]/book[2]'], recovered=True)
        self.module.resolve_with_status = lambda *args: result
        self.command.run(None)
        self.flush()
        self.assertEqual(self.clipboard, '/catalog[1]/book[2]')
        self.assertEqual(self.messages[-1], 'Copy Path: Copied positional XPath from incomplete XML.')
    def test_stale_recovery_result_neither_copies_nor_reports_success(self):
        result = types.SimpleNamespace(paths=['/catalog[1]/book[2]'], recovered=True)
        self.module.resolve_with_status = lambda *args: result
        self.command.run(None)
        self.async_queue.pop(0)()
        self.view.version += 1
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
        self.assertFalse(self.messages)
    def test_multicaret_xml_paths_keep_one_physical_line_per_path(self):
        from copy_path_lib.engine import resolve_with_status
        self.module.resolve_with_status = resolve_with_status
        self.view.scope = 'text.xml'
        for text, style, expected in [
            ('<r><x id="a&#10;b"/><x id="c"/></r>', 'xpath_attributes',
             "/r/x[1]/@id\n/r/x[@id='c']/@id"),
            ('<r><x>a\nb</x><x>c</x></r>', 'xpath_text',
             "/r/x[1]\n/r/x[.='c']"),
        ]:
            with self.subTest(style=style):
                self.view.text = text
                needle = 'id=' if style == 'xpath_attributes' else '<x>'
                self.view.selections = [Region(text.index(needle)), Region(text.rindex(needle))]
                self.command.run(None, style=style)
                self.flush()
                self.assertEqual(self.clipboard, expected)
                self.assertEqual(len(self.clipboard.splitlines()), 2)
    def test_visibility_and_style_applicability_are_cheap(self):
        self.view.substr = lambda region: self.fail('menus must not parse the buffer')
        self.assertTrue(self.command.is_visible())
        self.assertFalse(self.command.is_visible(style='xpath'))
        self.settings['show_in_context_menu'] = False
        self.assertFalse(self.command.is_visible(context=True))
        self.assertTrue(self.command.is_visible())
        self.view.scope = 'source.python'
        self.assertFalse(self.command.is_visible())
        self.view.config['copy_path_format'] = 'yaml'
        self.assertTrue(self.command.is_visible())
        self.view.widget = 'find:input'
        self.assertFalse(self.command.is_visible())
    def test_copy_path_as_heading_follows_document_type(self):
        menu = self.module.CopyPathMenuCommand(self.view)
        self.view.substr = lambda region: self.fail('menus must not parse the buffer')
        for scope, expected in (('source.json', True), ('source.yaml', True), ('text.xml', True), ('source.python', False)):
            with self.subTest(scope=scope):
                self.view.scope = scope
                self.assertIs(menu.is_visible(), expected)
        self.view.scope = 'source.json'
        self.settings['show_copy_path_as_submenu'] = False
        self.assertTrue(menu.is_visible())  # Settings stays reachable inside the heading.
        self.settings['show_in_context_menu'] = False
        self.assertTrue(menu.is_visible())  # Settings stays reachable to re-enable copying.
        self.view.widget = 'find:input'
        self.assertFalse(menu.is_visible())
        self.assertIsNone(menu.run(None))
    def test_closed_view_releases_request(self):
        self.command.run(None)
        self.module.CopyPathLifecycle().on_close(self.view)
        self.flush()
        self.assertEqual(self.clipboard, 'previous')
    def test_empty_pointer_is_copied_not_suppressed(self):
        self.module.resolve_with_status = lambda *args: types.SimpleNamespace(paths=[''], recovered=False)
        self.command.run(None, style='pointer')
        self.flush()
        self.assertEqual(self.clipboard, '')
        self.assertIn('root', self.messages[-1])
