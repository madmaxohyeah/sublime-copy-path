import unittest
from copy_path_lib.model import Document, Span, PathError, check_text, check_depth, add_span
from copy_path_lib.paths import render, xpath_literal

class ModelTests(unittest.TestCase):
    def test_deepest_half_open_and_eof(self):
        doc = Document(10, 'json', [Span(0, 10, ()), Span(2, 7, ('a',)), Span(3, 5, ('a', 0))])
        self.assertEqual(doc.path_at(3), ('a', 0))
        self.assertEqual(doc.path_at(5), ('a',))
        self.assertEqual(doc.path_at(7), ())
        self.assertEqual(doc.path_at(10), ())
        for point in [-1, 11, True, 1.5]:
            with self.assertRaises(PathError): doc.path_at(point)
    def test_recovered_documents_reject_points_outside_complete_spans(self):
        doc = Document(
            20,
            'xml',
            [Span(5, 10, ('root[1]', 'child[1]'))],
            recovered=True,
        )

        self.assertEqual(doc.path_at(7), ('root[1]', 'child[1]'))
        for point in [0, 4, 10, 19, 20]:
            with self.subTest(point=point):
                with self.assertRaisesRegex(PathError, 'complete XML element'):
                    doc.path_at(point)

    def test_bounds(self):
        with self.assertRaises(PathError): check_text('x' * 2000001)
        with self.assertRaises(PathError): check_depth(129)
        with self.assertRaises(PathError): add_span([None]*50000, 0, 1, ())
    def test_jsonpath(self):
        self.assertEqual(render(('users', 0, 'first name', 'a"b'), 'json', 'auto'), r'$.users[0]["first name"]["a\"b"]')
        self.assertEqual(render(('', 'a/b~c'), 'json', 'pointer'), '//a~1b~0c')
        self.assertEqual(render((), 'json', 'pointer'), '')
        self.assertEqual(render((), 'yaml', 'auto'), '$')
        self.assertEqual(render(('0',), 'json', 'jsonpath'), '$["0"]')
    def test_xpath(self):
        self.assertEqual(render(('root[1]', 'item[2]', '@id'), 'xml', 'auto'), '/root[1]/item[2]/@id')
        self.assertEqual(render((), 'xml', 'xpath'), '/')
        self.assertEqual(xpath_literal('abc'), "'abc'")
        self.assertEqual(xpath_literal("a'b"), '"' + "a'b" + '"')
        self.assertTrue(xpath_literal("a'" + '"b').startswith('concat('))
        for kind, style in [('xml', 'pointer'), ('json', 'xpath'), ('json', 'unknown')]:
            with self.assertRaises(PathError): render((), kind, style)
        with self.assertRaises(PathError):
            render((), 'xml', [])
