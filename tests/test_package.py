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


def load_settings():
    """The default settings file; its comments are whole lines starting with //."""
    text = (ROOT / 'Copy Path.sublime-settings').read_text(encoding='utf-8')
    return json.loads('\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('//')))


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
        artifact = ROOT / 'dist/Copy Path.sublime-package'
        self.assertEqual(artifact.read_bytes(), expected)
        self.assertEqual((ROOT / 'dist/Copy Path.sublime-package.sha256').read_text(encoding='utf-8'), hashlib.sha256(expected).hexdigest() + '  Copy Path.sublime-package\n')
    def test_native_resources(self):
        menu = json.loads((ROOT / 'Context.sublime-menu').read_text(encoding='utf-8'))
        self.assertEqual([item['caption'] for item in menu], ['-', 'Copy Element Path', 'Copy Element Path As'])
        direct = menu[1]
        self.assertEqual(direct['command'], 'copy_element_path')
        self.assertEqual(direct['args'], {'context': True})
        submenu = menu[2]
        # Only Linux asks the heading's command whether to show it; Windows and macOS always draw it.
        self.assertEqual(submenu['command'], 'copy_path_menu')
        self.assertNotIn('args', submenu)
        leaves = submenu['children']
        self.assertTrue(all(item.get('command') == 'copy_element_path' for item in leaves))
        self.assertEqual([item['args']['style'] for item in leaves],
                         ['jsonpath', 'pointer', 'xpath_attributes', 'xpath_positional', 'xpath_text'])
        self.assertTrue(all(item['args']['context'] for item in leaves))
        self.assertEqual([item['caption'] for item in leaves],
                         ['JSONPath', 'JSON Pointer', 'XPath – Prefer Attributes', 'XPath – Positional',
                          'XPath – Prefer Text'])
        for name in ['Main.sublime-menu', 'Default.sublime-commands']:
            json.loads((ROOT / name).read_text(encoding='utf-8'))
        load_settings()
    def test_no_em_dashes_in_captions(self):
        for name in ['Context.sublime-menu', 'Main.sublime-menu', 'Default.sublime-commands']:
            self.assertNotIn('—', (ROOT / name).read_text(encoding='utf-8'), name)
    def test_every_setting_is_documented_in_the_default_file(self):
        lines = (ROOT / 'Copy Path.sublime-settings').read_text(encoding='utf-8').splitlines()
        settings = load_settings()
        self.assertEqual(list(settings), ['format', 'json_path_style', 'xml_path_style', 'show_in_context_menu',
                                          'show_copy_path_as_submenu', 'max_file_chars'])
        for key in settings:
            index = next(i for i, line in enumerate(lines) if line.strip().startswith('"{}"'.format(key)))
            with self.subTest(key=key):
                self.assertTrue(lines[index - 1].strip().startswith('//'))
    def test_xpath_and_menu_defaults_are_shipped(self):
        settings = load_settings()
        self.assertIs(settings.get('show_in_context_menu'), True)
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

        main = json.loads((ROOT / 'Main.sublime-menu').read_text(encoding='utf-8'))
        self.assertEqual(list(settings_args(main)), [palette[0]['args']])
        # Package Control review: the context menu only holds actions on the clicked position.
        context = json.loads((ROOT / 'Context.sublime-menu').read_text(encoding='utf-8'))
        self.assertEqual(list(settings_args(context)), [])

    def test_user_settings_template_contains_no_settings(self):
        actions = json.loads((ROOT / 'Default.sublime-commands').read_text(encoding='utf-8'))
        default = next(item for item in actions if item['command'] == 'edit_settings')['args']['default']
        body = '\n'.join(line for line in default.splitlines() if not line.lstrip().startswith('//'))
        self.assertEqual(json.loads(body.replace('$0', '')), {})
        self.assertIn('$0', default)
