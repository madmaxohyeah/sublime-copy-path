import hashlib
from pathlib import Path
import unittest
from unittest import mock

from copy_path_lib.model import PathError
from copy_path_lib.yaml_parser import parse


class YamlParserTests(unittest.TestCase):
    def test_nested_mapping_and_sequence_source_paths(self):
        text = "# heading\nroot:\n  items:\n    - name: Ada\n      note: hi\n# tail\n"

        document = parse(text)

        self.assertEqual(document.length, len(text))
        self.assertEqual(document.kind, "yaml")
        self.assertEqual(document.path_at(text.index("heading")), ())
        self.assertEqual(document.path_at(text.index("root")), ("root",))
        self.assertEqual(document.path_at(text.index("items")), ("root", "items"))
        self.assertEqual(document.path_at(text.index("name")), ("root", "items", 0, "name"))
        self.assertEqual(document.path_at(text.index("Ada")), ("root", "items", 0, "name"))
        self.assertEqual(document.path_at(text.index("note")), ("root", "items", 0, "note"))
        self.assertEqual(document.path_at(text.index("tail")), ())
        self.assertEqual(document.path_at(len(text)), ())

    def test_flow_collections_assign_items_and_punctuation_to_containers(self):
        text = 'top: [{a: 1}, "x", null]\n'

        document = parse(text)

        self.assertEqual(document.path_at(text.index("[")), ("top",))
        self.assertEqual(document.path_at(text.index("{")), ("top", 0))
        self.assertEqual(document.path_at(text.index("a:")), ("top", 0, "a"))
        self.assertEqual(document.path_at(text.index("1")), ("top", 0, "a"))
        self.assertEqual(document.path_at(text.index(",", text.index("}"))), ("top",))
        self.assertEqual(document.path_at(text.index('"x"')), ("top", 1))
        self.assertEqual(document.path_at(text.index("null")), ("top", 2))
        self.assertEqual(document.path_at(text.index("]")), ("top",))

    def test_quoted_unicode_keys_and_block_scalar_values(self):
        text = '"first name": "Ada"\n\'yes\': ok\n☃: snow\nscript: |\n  one\n  two\n'

        document = parse(text)

        self.assertEqual(document.path_at(text.index("first name")), ("first name",))
        self.assertEqual(document.path_at(text.index("Ada")), ("first name",))
        self.assertEqual(document.path_at(text.index("yes")), ("yes",))
        self.assertEqual(document.path_at(text.index("☃")), ("☃",))
        self.assertEqual(document.path_at(text.index("two")), ("script",))
        self.assertEqual(document.path_at(text.index("|")), ("script",))

    def test_anchors_aliases_and_merge_keys_are_literal_source_locations(self):
        text = (
            "base: &base\n"
            "  name: Ada\n"
            "copy: *base\n"
            "recursive: &loop [*loop]\n"
            "merge:\n"
            "  <<: *base\n"
        )

        document = parse(text)

        self.assertEqual(document.path_at(text.index("&base")), ("base",))
        self.assertEqual(document.path_at(text.index("name")), ("base", "name"))
        self.assertEqual(document.path_at(text.index("*base")), ("copy",))
        self.assertEqual(document.path_at(text.index("*loop")), ("recursive", 0))
        self.assertEqual(document.path_at(text.index("<<")), ("merge", "<<"))
        self.assertEqual(document.path_at(text.rindex("*base")), ("merge", "<<"))

    def test_comments_belong_to_their_enclosing_mapping(self):
        text = (
            "outer:\n"
            "  child: value # trailing child\n"
            "  # between children\n"
            "  other: value\n"
            "# root comment\n"
        )

        document = parse(text)

        self.assertEqual(document.path_at(text.index("trailing")), ("outer",))
        self.assertEqual(document.path_at(text.index("between")), ("outer",))
        self.assertEqual(document.path_at(text.index("root comment")), ())

    def test_unknown_and_forward_aliases_are_rejected_without_source_leakage(self):
        for text in ['a: *missing\n', 'a: *later\nb: &later value\n', '*missing',
                     'root: [*later, &later value]\n']:
            with self.subTest(text=text):
                with self.assertRaisesRegex(PathError, 'previously declared anchor') as caught:
                    parse(text)
                self.assertNotIn('missing', str(caught.exception))
                self.assertNotIn('later', str(caught.exception))

    def test_anchors_on_every_node_kind_allow_prior_and_recursive_references(self):
        text = '&key field: &scalar value\nsequence: &seq [*scalar, *key, *seq]\nmapping: &map {self: *map}\nreused: &scalar replacement\nlast: *scalar\n'
        document = parse(text)
        self.assertEqual(document.path_at(text.index('*key')), ('sequence', 1))
        self.assertEqual(document.path_at(text.index('*seq')), ('sequence', 2))
        self.assertEqual(document.path_at(text.index('*map')), ('mapping', 'self'))
        self.assertEqual(document.path_at(text.rindex('*scalar')), ('last',))

    def test_signed_leading_dot_float_keys_require_quotes_or_string_tag(self):
        for key in ['+.5', '-.5', '+.5e+2', '-.5e-2', '+.5E-2', '-.5_0']:
            with self.subTest(key=key):
                with self.assertRaisesRegex(PathError, 'scalar strings'):
                    parse(key + ': value\n')
                for source_key in ['"' + key + '"', '!!str ' + key]:
                    document = parse(source_key + ': value\n')
                    self.assertEqual(document.path_at(0), (key,))

    def test_empty_mapping_values_cover_their_key_and_colon(self):
        text = "blank:\nnext: value\nnested:\n  child:\n"

        document = parse(text)

        self.assertEqual(document.path_at(text.index("blank")), ("blank",))
        self.assertEqual(document.path_at(text.index(":")), ("blank",))
        self.assertEqual(document.path_at(text.index("next")), ("next",))
        self.assertEqual(document.path_at(text.index("child")), ("nested", "child"))
        self.assertEqual(document.path_at(text.rindex(":")), ("nested", "child"))

    def test_yaml_1_1_implicit_non_string_keys_are_rejected(self):
        invalid_keys = [
            "true",
            "FALSE",
            "yes",
            "Off",
            "null",
            "~",
            "12",
            "0x10",
            "1.5",
            ".inf",
            "1:20",
            "2001-12-15",
            "=",
        ]

        for key in invalid_keys:
            with self.subTest(key=key):
                with self.assertRaisesRegex(PathError, "scalar strings"):
                    parse("{}: value\n".format(key))

    def test_quoted_and_explicit_standard_string_keys_are_accepted(self):
        text = '"true": one\n\'12\': two\n!!str null: three\n'

        document = parse(text)

        self.assertEqual(document.path_at(text.index("true")), ("true",))
        self.assertEqual(document.path_at(text.index("12")), ("12",))
        self.assertEqual(document.path_at(text.index("null")), ("null",))

    def test_typed_custom_alias_and_complex_mapping_keys_are_rejected(self):
        invalid_documents = [
            "!!int '12': value\n",
            "!custom key: value\n",
            "&key key: one\n*key: two\n",
            "? [a, b]\n: value\n",
            "? {a: b}\n: value\n",
        ]

        for text in invalid_documents:
            with self.subTest(text=text):
                with self.assertRaisesRegex(PathError, "scalar strings"):
                    parse(text)

    def test_duplicate_decoded_keys_are_rejected_per_mapping(self):
        invalid_documents = [
            'a: one\n"a": two\n',
            "{a: one, a: two}\n",
            "base: &base {x: one}\nmerge:\n  <<: *base\n  <<: *base\n",
        ]

        for text in invalid_documents:
            with self.subTest(text=text):
                with self.assertRaisesRegex(PathError, "duplicate key"):
                    parse(text)

        document = parse("one: {a: first}\ntwo: {a: second}\n")
        self.assertEqual(document.path_at(6), ("one", "a"))
        self.assertEqual(document.path_at(22), ("two", "a"))

    def test_arbitrary_value_tags_are_never_constructed_or_executed(self):
        text = (
            "payload: !!python/object/apply:os.system ['echo unsafe']\n"
            "other: !<tag:example.com,2026:Thing> value\n"
        )

        with mock.patch("os.system") as system:
            document = parse(text)

        system.assert_not_called()
        self.assertEqual(document.path_at(text.index("echo unsafe")), ("payload", 0))
        self.assertEqual(document.path_at(text.index("Thing")), ("other",))
        self.assertEqual(document.path_at(text.rindex("value")), ("other",))

    def test_empty_and_comment_only_streams_are_root_documents(self):
        for text in ("", "# comment only\n"):
            with self.subTest(text=text):
                document = parse(text)
                self.assertEqual(document.length, len(text))
                self.assertEqual(document.kind, "yaml")
                if text:
                    self.assertEqual(document.path_at(text.index("comment")), ())
                self.assertEqual(document.path_at(len(text)), ())

    def test_multiple_documents_are_rejected_but_one_explicit_document_is_allowed(self):
        document = parse("---\na: value\n...\n")
        self.assertEqual(document.path_at(4), ("a",))

        with self.assertRaisesRegex(PathError, "multiple documents"):
            parse("---\na: one\n---\nb: two\n")

    def test_malformed_yaml_uses_source_neutral_errors(self):
        invalid_documents = [
            "a: [one, two\n",
            "a:\n\tbad: value\n",
            "a: \x00\n",
            "{a: value,, b: value}\n",
        ]

        for text in invalid_documents:
            with self.subTest(text=text):
                with self.assertRaises(PathError) as raised:
                    parse(text)
                self.assertEqual(str(raised.exception), "Invalid YAML document.")
                self.assertNotIn(text.strip(), str(raised.exception))

    def test_recursive_aliases_are_not_expanded(self):
        text = "loop: &loop [*loop]\n"

        document = parse(text)

        self.assertEqual(document.path_at(text.index("*loop")), ("loop", 0))
        self.assertLess(len(document.spans), 10)

    def test_size_depth_and_node_limits_fail_closed(self):
        with self.assertRaisesRegex(PathError, "2,000,000-character"):
            parse("x" * 2_000_001)

        too_deep = "[" * 129 + "x" + "]" * 129
        with self.assertRaisesRegex(PathError, "128-level"):
            parse(too_deep)

        at_limit = "[" * 128 + "x" + "]" * 128
        document = parse(at_limit)
        self.assertEqual(document.path_at(128), (0,) * 128)

        too_many_nodes = "- value\n" * 50_001
        with self.assertRaisesRegex(PathError, "50,000-node"):
            parse(too_many_nodes)

    def test_vendored_pyyaml_files_match_verified_upstream_bytes(self):
        vendor = Path(__file__).parents[1] / "copy_path_lib" / "vendor" / "yaml"
        expected = {
            "LICENSE": "8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4",
            "error.py": "021f73fada072546c4f63f8cf18a7181244ce4280b09cc15cc980b2d1176171a",
            "events.py": "e74fd392c810884e2ea7e94aa3f57e9c1cbeb402319083d0c58e6a0e1282787c",
            "parser.py": "8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a",
            "reader.py": "d1d9b38ab3a20c6e17a38d519ee412ecaf6b918df18c78956ac7c330d4ea08dc",
            "scanner.py": "60433788b652690c17710460da5d91e0c753d3318fd85f5e1e42862a71f25906",
            "tokens.py": "953408cd2570f0c83dc2fe39f7e4e388e41eeb05738aa69196a5f6ffcf6ba79e",
        }

        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((vendor / name).read_bytes()).hexdigest(), digest)

        provenance = (vendor / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("PyYAML", provenance)
        self.assertIn("6.0.3", provenance)
        self.assertIn("d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f", provenance)
        self.assertIn("2026-09-26", provenance)


if __name__ == "__main__":
    unittest.main()
