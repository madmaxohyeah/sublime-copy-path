import unittest
from dataclasses import is_dataclass
from copy_path_lib.engine import detect_format, resolve, resolve_many, resolve_with_status
from copy_path_lib.model import PathError


class DetectionTests(unittest.TestCase):
    def test_filename_families(self):
        for name, kind in [('a.JSON', 'json'), ('a.jsonc', 'jsonc'), ('a.svg', 'xml'),
                           ('a.plist', 'xml'), ('a.xhtml', 'xml'), ('a.yml', 'yaml'),
                           ('Preferences.sublime-settings', 'jsonc')]:
            self.assertEqual(detect_format(name, ''), kind)
        for name in ['a.html', 'a.toml', 'a.txt', None]:
            self.assertIsNone(detect_format(name, ''))
    def test_scope_and_override(self):
        self.assertEqual(detect_format(None, 'source.json'), 'json')
        self.assertEqual(detect_format('a.json', 'source.json.comments'), 'jsonc')
        self.assertEqual(detect_format('a.txt', 'text.xml'), 'xml')
        self.assertEqual(detect_format('a.json', 'source.yaml'), 'yaml')
        self.assertEqual(detect_format(None, '', 'xml'), 'xml')
        self.assertIsNone(detect_format('a.json', 'text.html.basic'))
        self.assertIsNone(detect_format('a.json', 'source.python'))
        with self.assertRaises(PathError): detect_format(None, '', 'unknown')
    def test_xhtml_uses_xml_with_the_target_editors_default_html_scope(self):
        for filename in ['sample.xhtml', 'sample.XHTML']:
            self.assertEqual(detect_format(filename, 'text.html.basic'), 'xml')
        for filename in ['sample.html', 'sample.htm', 'sample.shtml', None]:
            self.assertIsNone(detect_format(filename, 'text.html.basic'))
        self.assertIsNone(detect_format('sample.xhtml', 'source.python'))
        self.assertEqual(detect_format('sample.xhtml', 'text.html.basic', 'json'), 'json')
    def test_sublime_4215_json_resources_accept_comments_and_trailing_commas(self):
        # From the official 4215 JSON.sublime-syntax extension manifest.
        extensions = (
            'sublime-build', 'sublime-color-scheme', 'sublime-commands',
            'sublime-completions', 'sublime-file-icons', 'sublime-keymap',
            'sublime-macro', 'sublime-menu', 'sublime-mousemap', 'sublime-project',
            'sublime-settings', 'sublime-theme', 'sublime-merge-theme',
            'sublime-workspace', 'hidden-color-scheme', 'sublime_session',
        )
        for extension in extensions:
            for scope in ['source.json', 'text.plain']:
                with self.subTest(extension=extension, scope=scope):
                    kind = detect_format('sample.' + extension, scope)
                    self.assertEqual(kind, 'jsonc')
                    self.assertEqual(resolve_many('{/*a*/"x":1,}', [8], kind), ['$.x'])
        for filename in ['sample.json', 'sample.ipynb', 'sample.gltf', 'sample.avsc', None]:
            self.assertEqual(detect_format(filename, 'source.json'), 'json')
        self.assertEqual(detect_format(None, 'source.json', 'jsonc'), 'jsonc')
    def test_bounds_before_parser(self):
        for points in [[], [0] * 33, [-1], [4], [True], [1.5]]:
            with self.assertRaises(PathError): resolve_many('{}', points, 'json')
        with self.assertRaises(PathError): resolve_many('{}', [0], 'toml')
        with self.assertRaises(PathError): resolve_many('{}', [0], 'json', 'xpath')


class ResolutionTests(unittest.TestCase):
    def test_resolve_and_deduplicate(self):
        text = '{"a": [10, 20], "b": "x"}'
        self.assertEqual(resolve_many(text, [text.index('10'), text.index('20'), text.index('10')], 'json'), ['$.a[0]', '$.a[1]'])
        self.assertEqual(resolve_many(text, [text.index('"x"')], 'json', 'pointer'), ['/b'])
    def test_jsonc_dispatch(self):
        self.assertEqual(resolve_many('{/*a*/"x":1,}', [8], 'jsonc'), ['$.x'])
    def test_xml_dispatch(self):
        self.assertEqual(resolve_many('<r><x/></r>', [4], 'xml'), ['/r/x'])

    def test_xml_xpath_styles_and_legacy_alias(self):
        text = '<catalog><book id="a"/><book id="b">Title</book></catalog>'
        point = text.index('Title')

        self.assertEqual(resolve_many(text, [point], 'xml'), ["/catalog/book[@id='b']"])
        self.assertEqual(
            resolve_many(text, [point], 'xml', 'xpath_attributes'),
            ["/catalog/book[@id='b']"],
        )
        self.assertEqual(
            resolve_many(text, [point], 'xml', 'xpath_positional'),
            ['/catalog[1]/book[2]'],
        )
        self.assertEqual(
            resolve_many(text, [point], 'xml', 'xpath'),
            ['/catalog[1]/book[2]'],
        )
        self.assertEqual(
            resolve_many(text, [point], 'xml', 'xpath_text'),
            ["/catalog/book[.='Title']"],
        )

    def test_recovery_status_and_compatibility_wrappers(self):
        text = '<catalog><book id="a"/><book id="b">Title</book>'
        point = text.index('Title')

        result = resolve_with_status(text, [point], 'xml')

        self.assertEqual(result.paths, ['/catalog[1]/book[2]'])
        self.assertTrue(result.recovered)
        self.assertEqual(resolve_many(text, [point], 'xml'), result.paths)
        self.assertEqual(resolve(text, point, 'xml'), result.paths[0])

    def test_resolution_status_is_a_dataclass_and_non_xml_is_not_recovered(self):
        points = [6]

        result = resolve_with_status('{"a": 1}', points, 'json')

        self.assertTrue(is_dataclass(result))
        self.assertEqual(result.paths, ['$.a'])
        self.assertFalse(result.recovered)
        self.assertEqual(points, [6])

    def test_recovery_is_atomic_for_multiple_carets(self):
        text = '<r><done/> trailing'

        with self.assertRaisesRegex(PathError, 'complete XML element'):
            resolve_with_status(
                text,
                [text.index('<done'), text.index('trailing')],
                'xml',
            )

    def test_malformed_tail_is_never_recovered_even_for_an_earlier_selection(self):
        invalid = [
            '<r><done/>&undefined;',
            '<r><done/><broken',
            '<r><done></r>',
        ]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(PathError):
                    resolve_with_status(text, [text.index('<done')], 'xml')

    def test_xml_rejects_non_xpath_engine_styles_before_resolution(self):
        for style in ['attributes', 'positional', 'text', 'jsonpath', 'pointer', 'unknown']:
            with self.subTest(style=style):
                with self.assertRaises(PathError):
                    resolve_many('<r/>', [1], 'xml', style)
    def test_yaml_dispatch(self):
        self.assertEqual(resolve_many('a:\n  b: yes\n', [9], 'yaml'), ['$.a.b'])


class ReviewRegressionTests(unittest.TestCase):
    def test_caret_after_a_value_copies_that_value(self):
        text = '{"n": 42, "s": "Ada", "o": {"x": [1]}}'
        for end, expected in [(text.index('42') + 2, '$.n'), (text.index('"Ada"') + 5, '$.s'),
                              (text.index('[1]') + 3, '$.o.x'), (text.index('[1]') + 2, '$.o.x[0]')]:
            with self.subTest(end=end):
                self.assertEqual(resolve(text, end, 'json'), expected)
        yaml = 'server:\n  port: 8080\n'
        self.assertEqual(resolve(yaml, yaml.index('8080') + 4, 'yaml'), '$.server.port')

    def test_caret_between_siblings_still_selects_the_next_one(self):
        self.assertEqual(resolve('[1,2]', 3, 'json'), '$[1]')
        self.assertEqual(resolve('[1, 2]', 3, 'json'), '$')
        xml = '<r><a>t</a><b/></r>'
        self.assertEqual(resolve(xml, xml.index('<b/>'), 'xml', 'xpath_positional'), '/r[1]/b[1]')
        yaml = 'a:\n  x: 1\nb: 2\n'
        self.assertEqual(resolve(yaml, yaml.index('b:'), 'yaml'), '$.b')

    def test_multiline_paths_need_a_single_caret(self):
        text = '{"a\\nb": 1, "c": 2}'
        self.assertEqual(resolve(text, text.index('1'), 'json', 'pointer'), '/a\nb')
        with self.assertRaises(PathError):
            resolve_many(text, [text.index('1'), text.index('2')], 'json', 'pointer')
        self.assertEqual(resolve_many(text, [text.index('1'), text.index('2')], 'json', 'jsonpath'),
                         ['$["a\\nb"]', '$.c'])
        xml = '<r xmlns:x="u&#10;v"><x:a/><x:a/></r>'
        with self.assertRaises(PathError):
            resolve_many(xml, [xml.index('<x:a/>') + 1, xml.rindex('<x:a/>') + 1], 'xml')

    def test_unpaired_surrogate_is_refused(self):
        text = '{"\\ud800": 1}'
        with self.assertRaises(PathError):
            resolve(text, text.index('1'), 'json', 'pointer')
        self.assertEqual(resolve(text, text.index('1'), 'json'), '$["\\ud800"]')

    def test_json_scope_family_is_exact(self):
        self.assertEqual(detect_format(None, 'source.json.sublime.settings'), 'json')
        for scope in ['source.json5', 'source.jsonnet', 'source.jsonl']:
            with self.subTest(scope=scope):
                self.assertIsNone(detect_format('a.x', scope))

    def test_yaml_non_specific_tag_key_is_a_string(self):
        self.assertEqual(resolve('! a: x\n', 5, 'yaml'), '$.a')
