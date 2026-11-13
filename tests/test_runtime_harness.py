"""The runtime report must describe the archive that was actually installed."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_smoke', ROOT / 'tools/runtime_smoke.py')
assert spec is not None and spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeReportTests(unittest.TestCase):
    def setUp(self):
        self.digest = hashlib.sha256(b'candidate').hexdigest()
        self.temporary = tempfile.TemporaryDirectory(prefix='copy-path-report-')
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(self.temporary.name)
        expected = {
            'mouse_auto_json': '$.catalog[1].label',
            'mouse_pointer_json': '/a~1b/~0key/1/value',
            'mouse_xpath_xml_attribute': '/root[1]/item[2]/@id',
            'mouse_auto_xml': "/catalog/book[@id='b']",
            'mouse_text_xml': "/catalog/book[.='Title']",
            'incomplete_xml': '/catalog[1]/book[2]',
            'mouse_submenu_disabled': 'COPY_PATH_RUNTIME_SENTINEL_mouse_submenu_disabled',
            'mouse_context_disabled': 'COPY_PATH_RUNTIME_SENTINEL_mouse_context_disabled',
            'caret_multiple_unicode': '$.users[0].name\n$["\\u043a\\u043b\\u044e\\u0447"].emoji',
            'yaml_archive_import': '$.root.items[0].city',
            'malformed_preserves_clipboard': 'MALFORMED_CLIPBOARD_MUST_SURVIVE',
        }
        cases = []
        for name, clipboard in expected.items():
            state = {'text_sha256': self.digest, 'selections': [[0, 0]], 'change_count': 0}
            case = {'name': name, 'passed': True, 'source_preserved': True,
                    'expected_clipboard': clipboard, 'clipboard': clipboard,
                    'before': copy.deepcopy(state), 'after': copy.deepcopy(state)}
            if name.startswith('mouse_'):
                suffixes = ['context'] if name.startswith('mouse_auto_') else ['context', 'submenu']
                case['screenshots'] = []
                for suffix in suffixes:
                    filename = name + '-' + suffix + '.png'
                    data = b'synthetic screenshot fixture'
                    (self.evidence / filename).write_bytes(data)
                    case['screenshots'].append({'file': filename, 'sha256': hashlib.sha256(data).hexdigest()})
            if name == 'yaml_archive_import':
                case['yaml_imports_from_archive'] = True
                case['yaml_modules'] = {'CopyPath.copy_path_lib.vendor.yaml.parser': '/CopyPath.sublime-package/copy_path_lib/vendor/yaml/parser.py'}
            if name == 'malformed_preserves_clipboard':
                case['status_messages'] = ['Invalid JSON document.']
            if name == 'incomplete_xml':
                case['status_messages'] = ['Copied positional XPath from incomplete XML.']
            if name in ('mouse_submenu_disabled', 'mouse_context_disabled'):
                case['settings_open'] = True
            cases.append(case)
        self.report = {
            'passed': True,
            'platform': 'linux',
            'build': '4215',
            'sublime_archive_sha256': runtime.EXPECTED_SUBLIME_ARCHIVE_SHA256,
            'python': '3.14.6',
            'archive_sha256': self.digest,
            'installed_archive_sha256': self.digest,
            'archive_only': True,
            'plugin_module': '/Data/Installed Packages/CopyPath.sublime-package/copy_path.py',
            'probe_module': '/Data/Packages/CopyPathRuntimeProbe/runtime_driver.py',
            'cleanup_issues': [],
            'environment': {name: None for name in runtime.STRIPPED_EDITOR_ENV},
            'cases': cases,
        }

    def test_matching_installed_bytes_are_accepted(self):
        runtime.validate_runtime_report(self.report, self.digest)

    def test_new_acceptance_inventory_includes_styles_recovery_and_settings(self):
        for case in ('mouse_auto_xml', 'mouse_text_xml', 'incomplete_xml',
                     'mouse_submenu_disabled', 'mouse_context_disabled'):
            self.assertIn(case, runtime.REQUIRED_CASES)

    def test_recovery_without_visible_warning_is_not_accepted(self):
        # A matching positional clipboard alone cannot prove that recovery was disclosed.
        for case in self.report['cases']:
            if case['name'] == 'incomplete_xml':
                case['status_messages'] = []
        with self.assertRaisesRegex(RuntimeError, 'recovery'):
            runtime.validate_runtime_report(self.report, self.digest)

    def test_editor_archive_provenance_must_match_the_pinned_distribution(self):
        for value in [None, self.digest]:
            with self.subTest(value=value):
                report = copy.deepcopy(self.report)
                report['sublime_archive_sha256'] = value
                with self.assertRaisesRegex(RuntimeError, 'editor archive'):
                    runtime.validate_runtime_report(report, self.digest)

    def test_unchanged_clipboard_without_an_error_message_does_not_prove_rejection(self):
        case = next(c for c in self.report['cases'] if c['name'] == 'malformed_preserves_clipboard')
        for messages in [[], ['Copied 1 path.'], None]:
            with self.subTest(messages=messages):
                case['status_messages'] = messages
                with self.assertRaisesRegex(RuntimeError, 'malformed'):
                    runtime.validate_runtime_report(self.report, self.digest)

    def test_changed_or_missing_installed_bytes_are_rejected(self):
        for digest in [None, hashlib.sha256(b'other archive').hexdigest()]:
            with self.subTest(digest=digest):
                report = copy.deepcopy(self.report)
                report['installed_archive_sha256'] = digest
                with self.assertRaisesRegex(RuntimeError, 'installed archive'):
                    runtime.validate_runtime_report(report, self.digest)

    def test_wrong_embedded_python_is_rejected(self):
        for version in [None, '3.3.6', '3.8.12']:
            with self.subTest(version=version):
                report = copy.deepcopy(self.report)
                report['python'] = version
                with self.assertRaisesRegex(RuntimeError, 'Python 3.14'):
                    runtime.validate_runtime_report(report, self.digest)

    def test_missing_case_or_cleanup_failure_is_rejected(self):
        missing = copy.deepcopy(self.report)
        missing['cases'].pop()
        with self.assertRaisesRegex(RuntimeError, 'missing runtime cases'):
            runtime.validate_runtime_report(missing, self.digest)
        failed = copy.deepcopy(self.report)
        failed['cleanup_issues'] = ['editor still running']
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            runtime.validate_runtime_report(failed, self.digest)

    def test_duplicate_or_unexpected_cases_are_rejected(self):
        for name in ['mouse_auto_json', 'unexpected_case']:
            report = copy.deepcopy(self.report)
            extra = copy.deepcopy(report['cases'][0])
            extra['name'] = name
            report['cases'].append(extra)
            with self.assertRaisesRegex(RuntimeError, 'case'):
                runtime.validate_runtime_report(report, self.digest)

    def test_wrong_platform_is_rejected(self):
        report = copy.deepcopy(self.report)
        report['platform'] = 'windows'
        with self.assertRaisesRegex(RuntimeError, 'platform'):
            runtime.validate_runtime_report(report, self.digest)

    def test_self_consistent_wrong_clipboard_is_rejected(self):
        report = copy.deepcopy(self.report)
        report['cases'][0].update(clipboard='wrong', expected_clipboard='wrong')
        with self.assertRaisesRegex(RuntimeError, 'clipboard'):
            runtime.validate_runtime_report(report, self.digest)

    def test_source_changes_are_rejected(self):
        report = copy.deepcopy(self.report)
        report['cases'][0]['after']['selections'] = [[1, 1]]
        with self.assertRaisesRegex(RuntimeError, 'source'):
            runtime.validate_runtime_report(report, self.digest)

    def test_nonarchive_yaml_imports_are_rejected(self):
        report = copy.deepcopy(self.report)
        yaml = next(case for case in report['cases'] if case['name'] == 'yaml_archive_import')
        yaml['yaml_modules'] = {'yaml.parser': '/source-checkout/yaml/parser.py'}
        with self.assertRaisesRegex(RuntimeError, 'YAML'):
            runtime.validate_runtime_report(report, self.digest)

    def test_missing_screenshot_metadata_is_rejected(self):
        self.report['cases'][0]['screenshots'] = []
        with self.assertRaisesRegex(RuntimeError, 'screenshot'):
            runtime.validate_runtime_report(self.report, self.digest)

    def test_retained_screenshots_must_exist_and_match_their_hashes(self):
        runtime.validate_runtime_report(self.report, self.digest, evidence_dir=self.evidence)
        path = self.evidence / 'mouse_auto_json-context.png'
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'screenshot'):
            runtime.validate_runtime_report(self.report, self.digest, evidence_dir=self.evidence)
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'screenshot'):
            runtime.validate_runtime_report(self.report, self.digest, evidence_dir=self.evidence)
