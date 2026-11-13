import unittest

from copy_path_lib.json_parser import parse
from copy_path_lib.model import (
    MAX_CHARS,
    MAX_DEPTH,
    MAX_SPANS,
    Document,
    PathError,
    Span,
)


class JsonParserTests(unittest.TestCase):
    def assert_path(self, document, text, marker, expected, offset=0):
        point = text.index(marker) + offset
        self.assertEqual(document.path_at(point), expected)

    def test_property_spans_cover_keys_colons_and_values(self):
        text = ' { "a" : 1 , "b": [2, 3] } '
        document = parse(text)

        self.assertIsInstance(document, Document)
        self.assertEqual(document.length, len(text))
        self.assertEqual(document.kind, "json")
        self.assertEqual(
            set(document.spans),
            {
                Span(text.index("{"), text.rindex("}") + 1, ()),
                Span(text.index('"a"'), text.index("1") + 1, ("a",)),
                Span(text.index('"b"'), text.index("]") + 1, ("b",)),
                Span(text.index("2"), text.index("2") + 1, ("b", 0)),
                Span(text.index("3"), text.index("3") + 1, ("b", 1)),
            },
        )
        self.assert_path(document, text, '"a"', ("a",))
        self.assert_path(document, text, ":", ("a",))
        self.assertEqual(document.path_at(text.index(":") - 1), ("a",))
        self.assertEqual(document.path_at(text.index("1") - 1), ("a",))
        self.assert_path(document, text, "1", ("a",))
        self.assertEqual(document.path_at(text.index(",", text.index("1"))), ())
        self.assertEqual(document.path_at(text.index(" ", text.index("1") + 1)), ())
        self.assertEqual(document.path_at(text.index("[")), ("b",))
        self.assertEqual(document.path_at(text.index(",", text.index("2"))), ("b",))
        self.assertEqual(document.path_at(text.index("]")), ("b",))
        self.assertEqual(document.path_at(len(text)), ())

    def test_nested_array_and_object_punctuation_use_container_paths(self):
        text = '{"items":[ {"name":"x", "ok":true}, 2 ]}'
        document = parse(text)

        self.assert_path(document, text, '"items"', ("items",))
        self.assertEqual(document.path_at(text.index("[")), ("items",))
        self.assertEqual(document.path_at(text.index("{", 1)), ("items", 0))
        self.assert_path(document, text, '"name"', ("items", 0, "name"))
        self.assert_path(document, text, '"x"', ("items", 0, "name"))
        self.assert_path(document, text, '"ok"', ("items", 0, "ok"))
        self.assert_path(document, text, "true", ("items", 0, "ok"))
        inner_comma = text.index(",", text.index('"x"'))
        outer_comma = text.index(",", text.index("true"))
        self.assertEqual(document.path_at(inner_comma), ("items", 0))
        self.assertEqual(document.path_at(outer_comma), ("items",))
        self.assertEqual(document.path_at(text.index("2")), ("items", 1))

    def test_escaped_keys_are_decoded_for_paths_and_duplicates(self):
        text = r'{"a\/b~c\"":{"\u2603":true}}'
        document = parse(text)

        self.assert_path(document, text, r'"a\/b~c\""', ('a/b~c"',))
        self.assert_path(document, text, r'"\u2603"', ('a/b~c"', "☃"))
        snowman_key = next(span.path for span in document.spans if len(span.path) == 2)
        self.assertEqual(snowman_key, ('a/b~c"', "☃"))

        with self.assertRaises(PathError):
            parse(r'{"a":1,"\u0061":2}')

    def test_unicode_offsets_are_codepoints_and_bom_is_accepted_at_start(self):
        text = '\ufeff {"é":"🙂","target":42}'
        document = parse(text)

        self.assertEqual(document.length, len(text))
        self.assert_path(document, text, '"é"', ("é",))
        self.assert_path(document, text, '"🙂"', ("é",))
        self.assert_path(document, text, '"target"', ("target",))
        self.assertEqual(document.path_at(text.index("42") + 1), ("target",))
        self.assertEqual(document.path_at(0), ())

        with self.assertRaises(PathError):
            parse('{"x":\ufeff 1}')

    def test_top_level_scalars_and_strict_numbers_are_valid(self):
        values = [
            '"text"',
            "true",
            "false",
            "null",
            "0",
            "-0",
            "12",
            "-12.34e+5",
            "6.022E23",
        ]
        for text in values:
            with self.subTest(text=text):
                document = parse(text)
                self.assertEqual(document.spans, [Span(0, len(text), ())])
                self.assertEqual(document.path_at(0), ())
                self.assertEqual(document.path_at(len(text)), ())

    def test_malformed_or_trailing_input_is_rejected(self):
        invalid = [
            "",
            " ",
            '{"a":}',
            "[1,]",
            '{"a":1,}',
            "{} []",
            "true false",
            "nul",
            "+1",
            ".1",
            "01",
            "-01",
            "1.",
            "1e",
            "1e+",
            "NaN",
            "Infinity",
            "-Infinity",
            '"unterminated',
            '"bad\\xescape"',
            '"line\nbreak"',
            "[1,,2]",
            '{"a" 1}',
        ]
        for text in invalid:
            with self.subTest(text=repr(text)):
                with self.assertRaises(PathError):
                    parse(text)

    def test_string_escape_rules_are_strict(self):
        parse(r'["\"","\\","\/","\b","\f","\n","\r","\t","\u0041"]')

        invalid = [
            r'["\v"]',
            r'["\0"]',
            r'["\u12"]',
            r'["\uZZZZ"]',
            '["\x00"]',
        ]
        for text in invalid:
            with self.subTest(text=repr(text)):
                with self.assertRaises(PathError):
                    parse(text)

    def test_duplicate_decoded_keys_are_rejected_per_object(self):
        for text in ['{"a":1,"a":2}', r'{"a":1,"\u0061":2}']:
            with self.subTest(text=text):
                with self.assertRaises(PathError):
                    parse(text)

        parse('{"left":{"a":1},"right":{"a":2}}')

    def test_jsonc_comments_and_trailing_commas_are_opt_in(self):
        text = """{
// before property
"items": [1, /* between elements */ 2,],
"flag": /* before value */ true,
}
// after root
"""
        document = parse(text, comments=True)

        self.assertEqual(document.path_at(text.index("// before")), ())
        self.assertEqual(document.path_at(text.index("/* between")), ("items",))
        self.assertEqual(document.path_at(text.index("/* before value")), ("flag",))
        self.assertEqual(document.path_at(text.index("1")), ("items", 0))
        self.assertEqual(document.path_at(text.index("2", text.index("/* between"))), ("items", 1))
        self.assertEqual(document.path_at(text.index("true")), ("flag",))
        self.assertEqual(document.path_at(text.index("// after root")), ())

        with self.assertRaises(PathError):
            parse(text)
        with self.assertRaises(PathError):
            parse("[1,]")
        with self.assertRaises(PathError):
            parse('{"a":1,}')

    def test_jsonc_does_not_treat_comment_markers_inside_strings_as_comments(self):
        text = r'{"url":"https://example.test/a//b","block":"/* literal */",}'
        document = parse(text, comments=True)

        self.assert_path(document, text, "https://", ("url",))
        self.assert_path(document, text, "//b", ("url",))
        self.assert_path(document, text, "/* literal */", ("block",))

    def test_jsonc_rejects_unterminated_or_misplaced_comments(self):
        invalid = [
            "/*",
            "[1, /*",
            "[1 / 2]",
            '{"a"/\n:1}',
        ]
        for text in invalid:
            with self.subTest(text=repr(text)):
                with self.assertRaises(PathError):
                    parse(text, comments=True)

    def test_depth_limit_is_enforced(self):
        accepted = "[" * MAX_DEPTH + "0" + "]" * MAX_DEPTH
        document = parse(accepted)
        self.assertEqual(document.path_at(MAX_DEPTH), (0,) * MAX_DEPTH)

        rejected = "[" * (MAX_DEPTH + 1) + "0" + "]" * (MAX_DEPTH + 1)
        with self.assertRaises(PathError):
            parse(rejected)

    def test_span_limit_is_enforced_at_the_exact_boundary(self):
        accepted = "[" + ",".join(["0"] * (MAX_SPANS - 1)) + "]"
        document = parse(accepted)
        self.assertEqual(len(document.spans), MAX_SPANS)

        rejected = "[" + ",".join(["0"] * MAX_SPANS) + "]"
        with self.assertRaises(PathError):
            parse(rejected)

    def test_text_limit_and_non_string_input_are_rejected(self):
        with self.assertRaises(PathError):
            parse(" " * (MAX_CHARS + 1))
        for value in [None, b"{}", 1, True]:
            with self.subTest(value=repr(value)):
                with self.assertRaises(PathError):
                    parse(value)

    def test_errors_are_concise_and_do_not_include_source_text(self):
        secret = "value-that-must-not-leak"
        with self.assertRaises(PathError) as caught:
            parse('{"' + secret + '": ]}')
        message = str(caught.exception)
        self.assertNotIn(secret, message)
        self.assertLessEqual(len(message), 80)


if __name__ == "__main__":
    unittest.main()
