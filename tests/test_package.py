import hashlib
import importlib.util
import io
import json
import pathlib
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builder', ROOT / 'tools/build_package.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackageTests(unittest.TestCase):
    def test_archive_is_deterministic_and_allowlisted(self):
        first = builder.package_bytes(ROOT)
        self.assertEqual(first, builder.package_bytes(ROOT))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(builder.PACKAGE_FILES))
            self.assertEqual(archive.read('.python-version'), b'3.8\n')
            for item in archive.infolist():
                self.assertEqual(item.date_time, (2020, 1, 1, 0, 0, 0))
                self.assertEqual(item.compress_type, zipfile.ZIP_STORED)
                self.assertNotIn('tests/', item.filename)
                self.assertNotIn('tools/', item.filename)
                self.assertNotIn('__pycache__', item.filename)
                self.assertEqual(archive.read(item.filename), (ROOT / item.filename).read_bytes())
    def test_committed_artifact_matches_source(self):
        expected = builder.package_bytes(ROOT)
        artifact = ROOT / 'dist/CopyPath.sublime-package'
        self.assertEqual(artifact.read_bytes(), expected)
        self.assertEqual((ROOT / 'dist/CopyPath.sublime-package.sha256').read_text(encoding='utf-8'), hashlib.sha256(expected).hexdigest() + '  CopyPath.sublime-package\n')
    def test_native_resources(self):
        menu = json.loads((ROOT / 'Context.sublime-menu').read_text(encoding='utf-8'))
        direct = next(item for item in menu if item.get('caption') == 'Copy Element Path')
        self.assertEqual(direct['command'], 'copy_element_path')
        self.assertTrue(direct['args']['context'])
        submenu = next(item for item in menu if item.get('caption') == 'Copy Path As')
        # Linux honors the heading's visibility check; Windows and macOS always show
        # submenu headings, so the Settings leaf below keeps the submenu non-empty there.
        self.assertEqual(submenu['command'], 'copy_path_menu')
        self.assertNotIn('args', submenu)
        leaves = [item for item in submenu['children'] if item.get('command') == 'copy_element_path']
        self.assertEqual([item['args']['style'] for item in leaves],
                         ['jsonpath', 'pointer', 'xpath_attributes', 'xpath_positional', 'xpath_text'])
        self.assertTrue(all(item['args']['context'] for item in leaves))
        self.assertEqual([item['caption'] for item in leaves[2:]],
                         ['XPath — Prefer Attributes', 'XPath — Positional', 'XPath — Prefer Text'])
        settings = submenu['children'][-1]
        self.assertEqual(settings['caption'], 'Settings…')
        self.assertEqual(settings['command'], 'edit_settings')
        self.assertEqual(settings['args']['base_file'], '${packages}/CopyPath/CopyPath.sublime-settings')
        for name in ['Main.sublime-menu', 'Default.sublime-commands', 'CopyPath.sublime-settings']:
            json.loads((ROOT / name).read_text(encoding='utf-8'))
    def test_xpath_and_menu_defaults_are_shipped(self):
        settings = json.loads((ROOT / 'CopyPath.sublime-settings').read_text(encoding='utf-8'))
        self.assertIs(settings.get('show_copy_path_as_submenu'), True)
        self.assertEqual(settings.get('xml_path_style'), 'attributes')
        actions = json.loads((ROOT / 'Default.sublime-commands').read_text(encoding='utf-8'))
        styles = [item.get('args', {}).get('style') for item in actions]
        for style in ('xpath_attributes', 'xpath_positional', 'xpath_text'):
            self.assertIn(style, styles)

    def test_settings_open_the_same_way_from_palette_and_menus(self):
        """Package Control review: settings must be reachable from the menu and the palette."""
        actions = json.loads((ROOT / 'Default.sublime-commands').read_text(encoding='utf-8'))
        palette = [item for item in actions if item['command'] == 'edit_settings']
        self.assertEqual([item['caption'] for item in palette], ['Preferences: Copy Path Settings'])

        def settings_args(items):
            for item in items:
                if item.get('command') == 'edit_settings':
                    yield item['args']
                yield from settings_args(item.get('children', []))

        for name in ('Main.sublime-menu', 'Context.sublime-menu'):
            menu = json.loads((ROOT / name).read_text(encoding='utf-8'))
            self.assertEqual(list(settings_args(menu)), [palette[0]['args']], name)
