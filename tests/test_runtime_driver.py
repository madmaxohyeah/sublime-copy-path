"""Probe completion must observe a real error, not an unchanged sentinel."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class DriverCompletionTests(unittest.TestCase):
    def setUp(self):
        self.queue = []
        self.forward = Mock()
        self.product = types.SimpleNamespace(_message=self.forward)
        sublime = types.SimpleNamespace(
            get_clipboard=lambda: 'sentinel',
            set_timeout=lambda callback, delay=0: self.queue.append(callback),
        )
        modules = {'sublime': sublime,
                   'sublime_plugin': types.SimpleNamespace(EventListener=object),
                   'CopyPath.copy_path': self.product}
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        path = Path(__file__).resolve().parents[1] / 'tools/runtime_driver.py'
        spec = importlib.util.spec_from_file_location('completion_probe', path)
        assert spec is not None and spec.loader is not None
        self.driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.driver)
        self.view = types.SimpleNamespace(is_valid=lambda: True, run_command=Mock())
        self.driver._current_view = self.view
        self.driver._snapshot = lambda view: {'clipboard': 'sentinel'}
        self.driver._response = Mock()
        self.clock = patch.object(self.driver.time, 'monotonic', return_value=0.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_preseeded_clipboard_cannot_complete_until_expected_error_is_forwarded(self):
        self.driver._run_command('request', {
            'expected_clipboard': 'sentinel', 'expected_status': 'Invalid JSON document.'})
        self.queue.pop(0)()
        self.driver._response.assert_not_called()
        self.product._message('Invalid JSON document.')
        self.queue.pop(0)()
        self.forward.assert_called_once_with('Invalid JSON document.')
        payload = self.driver._response.call_args[0][1]
        self.assertEqual(payload['status_messages'], ['Invalid JSON document.'])
        self.assertIs(self.product._message, self.forward)

    def test_timeout_restores_the_observer_and_returns_no_invented_message(self):
        self.driver._run_command('request', {
            'expected_clipboard': 'sentinel', 'expected_status': 'Invalid JSON document.',
            'timeout_ms': 10})
        self.driver.time.monotonic.return_value = 1.0
        self.queue.pop(0)()
        payload = self.driver._response.call_args[0][1]
        self.assertEqual(payload['status_messages'], [])
        self.assertIs(self.product._message, self.forward)

    def test_settings_detection_checks_the_separate_settings_window(self):
        self.assertTrue(hasattr(self.driver, '_settings_open'))
        original = types.SimpleNamespace(views=lambda: [])
        settings_view = types.SimpleNamespace(file_name=lambda: '/profile/Data/Packages/User/CopyPath.sublime-settings')
        separate = types.SimpleNamespace(views=lambda: [settings_view])
        self.driver.sublime.windows = lambda: [original, separate]
        self.assertTrue(self.driver._settings_open())
        settings_view.file_name = lambda: '/profile/Data/Packages/User/Other.sublime-settings'
        self.assertFalse(self.driver._settings_open())

    def test_command_exception_restores_the_original_message_function(self):
        self.view.run_command.side_effect = RuntimeError('command failed')
        with self.assertRaisesRegex(RuntimeError, 'command failed'):
            self.driver._run_command('request', {})
        self.assertIs(self.product._message, self.forward)
