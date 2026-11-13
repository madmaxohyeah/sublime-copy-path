import unittest
from unittest import mock

from copy_path_lib.model import PathError
from copy_path_lib.paths import xpath_literal
from copy_path_lib.xml_parser import parse


def namespaced_element(local, uri, index):
    return "*[local-name()={} and namespace-uri()={}][{}]".format(
        xpath_literal(local), xpath_literal(uri), index
    )


def namespaced_attribute(local, uri):
    return "@*[local-name()={} and namespace-uri()={}]".format(
        xpath_literal(local), xpath_literal(uri)
    )


def nth_index(text, needle, occurrence):
    point = -1
    for _ in range(occurrence):
        point = text.index(needle, point + 1)
    return point


class XmlParserTests(unittest.TestCase):
    def assert_path(self, document, point, *segments):
        self.assertEqual(document.path_at(point), tuple(segments))

    def test_document_metadata_bom_declaration_and_outside_root(self):
        text = (
            "\ufeff<?xml version='1.0'?>\n"
            "<!--before--><root>text</root><!--after-->\n"
        )
        document = parse(text)

        self.assertEqual(document.length, len(text))
        self.assertEqual(document.kind, "xml")
        for point in [
            0,
            text.index("xml"),
            text.index("before"),
            text.index("after"),
            len(text) - 1,
            len(text),
        ]:
            self.assert_path(document, point)
        for point in [
            text.index("<root>"),
            text.index("root"),
            text.index("text"),
            text.index("</root>") + 2,
        ]:
            self.assert_path(document, point, "root[1]")

    def test_elements_use_one_based_expanded_name_sibling_indices(self):
        text = "<root>before<a/>between<a><only/></a>after</root>"
        document = parse(text)
        first_child = text.index("<a/>")
        second_child = text.index("<a>")
        only_child = text.index("<only/>")
        second_end = text.index("</a>")

        for point in [text.index("before"), text.index("between"), text.index("after")]:
            self.assert_path(document, point, "root[1]")
        for point in [first_child, first_child + 1, first_child + 3]:
            self.assert_path(document, point, "root[1]", "a[1]")
        for point in [second_child, second_child + 1, second_end, second_end + 2]:
            self.assert_path(document, point, "root[1]", "a[2]")
        self.assert_path(document, only_child + 1, "root[1]", "a[2]", "only[1]")

        self.assert_path(document, first_child - 1, "root[1]")
        self.assert_path(document, first_child + len("<a/>"), "root[1]")

    def test_attribute_names_equals_and_values_map_to_attributes(self):
        text = (
            '<root xmlns="urn:r" xmlns:p="urn:p" '
            'a = "x>y" b=\'q"r\' p:id = \'42\' id="plain" '
            'xml:lang="en" p:a="other"/>'
        )
        document = parse(text)
        root = namespaced_element("root", "urn:r", 1)

        a_source = 'a = "x>y"'
        a_start = text.index(a_source)
        for offset in [0, a_source.index("="), a_source.index(">"), len(a_source) - 1]:
            self.assert_path(document, a_start + offset, root, "@a")

        b_source = 'b=\'q"r\''
        b_start = text.index(b_source)
        for offset in [0, b_source.index("="), b_source.index('"'), len(b_source) - 1]:
            self.assert_path(document, b_start + offset, root, "@b")

        prefixed_source = "p:id = '42'"
        prefixed_start = text.index(prefixed_source)
        prefixed_path = namespaced_attribute("id", "urn:p")
        for offset in [0, prefixed_source.index("="), prefixed_source.index("4"), len(prefixed_source) - 1]:
            self.assert_path(document, prefixed_start + offset, root, prefixed_path)

        plain_source = 'id="plain"'
        plain_start = text.index(plain_source)
        for offset in [0, plain_source.index("="), plain_source.index("p"), len(plain_source) - 1]:
            self.assert_path(document, plain_start + offset, root, "@id")

        xml_source = 'xml:lang="en"'
        xml_start = text.index(xml_source)
        xml_path = namespaced_attribute(
            "lang", "http://www.w3.org/XML/1998/namespace"
        )
        for offset in [0, xml_source.index("="), xml_source.index("e"), len(xml_source) - 1]:
            self.assert_path(document, xml_start + offset, root, xml_path)

        prefixed_a_source = 'p:a="other"'
        prefixed_a_start = text.index(prefixed_a_source)
        prefixed_a_path = namespaced_attribute("a", "urn:p")
        for offset in [0, prefixed_a_source.index("="), prefixed_a_source.index("o"), len(prefixed_a_source) - 1]:
            self.assert_path(
                document, prefixed_a_start + offset, root, prefixed_a_path
            )

        for point in [text.index("xmlns"), text.index("xmlns:p"), text.rindex("/")]:
            self.assert_path(document, point, root)

    def test_namespace_prefixes_rebinding_and_default_namespace(self):
        text = (
            '<r xmlns:a="urn:u" xmlns:b="urn:u" xmlns:c="urn:v">'
            '<a:x/><b:x/><c:x/><x xmlns="urn:u"/><x xmlns=""/>'
            '<a:x xmlns:a="urn:v"/>'
            "</r>"
        )
        document = parse(text)
        root = "r[1]"
        u1 = namespaced_element("x", "urn:u", 1)
        u2 = namespaced_element("x", "urn:u", 2)
        u3 = namespaced_element("x", "urn:u", 3)
        v1 = namespaced_element("x", "urn:v", 1)
        v2 = namespaced_element("x", "urn:v", 2)

        self.assert_path(document, nth_index(text, "<a:x", 1) + 1, root, u1)
        self.assert_path(document, text.index("<b:x") + 1, root, u2)
        self.assert_path(document, text.index("<c:x") + 1, root, v1)
        self.assert_path(document, text.index('<x xmlns="urn:u"') + 1, root, u3)
        self.assert_path(document, text.index('<x xmlns=""') + 1, root, "x[1]")
        self.assert_path(document, nth_index(text, "<a:x", 2) + 1, root, v2)

        self.assert_path(document, text.index('xmlns="urn:u"'), root, u3)
        self.assert_path(document, text.rindex('xmlns:a="urn:v"'), root, v2)
        self.assert_path(document, text.index("xmlns:a"), root)

    def test_xpath_literals_protect_quoted_namespace_uris(self):
        uri = "urn:a'\"b"
        text = '<r xmlns:p="urn:a&apos;&quot;b"><p:x p:y="1"/></r>'
        document = parse(text)
        child = namespaced_element("x", uri, 1)
        attribute = namespaced_attribute("y", uri)

        self.assert_path(document, text.index("p:x"), "r[1]", child)
        self.assert_path(document, text.index("p:y"), "r[1]", child, attribute)
        self.assertIn("concat(", child)
        self.assertIn("concat(", attribute)

    def test_text_comments_cdata_and_processing_instructions_use_container(self):
        text = (
            '<r>alpha<!-- <fake/> -->beta<![CDATA[<fake attr=">"/>]]>'
            "<?inside <fake attr='>'?><c>delta<!--inside--><![CDATA[<z/>]]></c>omega</r>"
        )
        document = parse(text)
        root = ("r[1]",)
        child = ("r[1]", "c[1]")

        for needle in [
            "alpha",
            "<fake/>",
            "beta",
            '<fake attr=">"/>',
            "<fake attr='>'",
            "omega",
        ]:
            self.assertEqual(document.path_at(text.index(needle)), root)
        for needle in ["delta", "<!--inside-->", "<z/>", "</c>"]:
            self.assertEqual(document.path_at(text.index(needle)), child)

        child_start = text.index("<c>")
        child_end = text.index("</c>") + len("</c>")
        self.assertEqual(document.path_at(child_start - 1), root)
        self.assertEqual(document.path_at(child_start), child)
        self.assertEqual(document.path_at(child_end - 1), child)
        self.assertEqual(document.path_at(child_end), root)

    def test_predefined_entities_are_allowed_without_creating_nodes(self):
        text = '<r a="&lt;&amp;&quot;&apos;&gt;">x &lt; y &amp; z</r>'
        document = parse(text)

        self.assert_path(document, text.index("&amp;"), "r[1]", "@a")
        self.assert_path(document, text.rindex("&amp;"), "r[1]")

    def test_unicode_source_positions_are_codepoint_offsets(self):
        text = (
            '<?xml version="1.0"?><r note="😀"><前>é<a 属性="值">文本</a></前>'
            '<target id="✓"/></r>'
        )
        document = parse(text)
        target = text.index("<target")
        target_id = text.index('id="✓"')
        unicode_attribute = text.index('属性="值"')

        self.assert_path(document, unicode_attribute, "r[1]", "前[1]", "a[1]", "@属性")
        self.assert_path(document, target + 1, "r[1]", "target[1]")
        self.assert_path(document, target_id + len('id="'), "r[1]", "target[1]", "@id")
        self.assertEqual(document.length, len(text))

    def test_malformed_xml_has_concise_source_safe_errors(self):
        malformed = [
            "",
            "<r>",
            "<r><x></r>",
            "<r a='1' a='2'/>",
            "<r>&unknown;</r>",
            "text<r/>",
            "<r/><x/>",
            "<!DOCTYPE r [",
            "<r>\ud800</r>",
            "<r>\x00</r>",
            "<p:r/>",
            '<r xmlns:p="urn:u" xmlns:q="urn:u" p:a="1" q:a="2"/>',
        ]
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(PathError) as caught:
                    parse(source)
                self.assertLessEqual(len(str(caught.exception)), 120)
                if source:
                    self.assertNotIn(source, str(caught.exception))

        secret = "DO_NOT_ECHO_THIS_SOURCE"
        with self.assertRaises(PathError) as caught:
            parse("<r>{}&unknown;</r>".format(secret))
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(PathError):
            parse(None)

    def test_dtds_and_external_entities_are_rejected_without_resolution(self):
        sources = [
            "<!DOCTYPE\nr><r/>",
            '<!DOCTYPE r [<!ENTITY x "expanded">]><r>&x;</r>',
            '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>',
            '<!DOCTYPE r SYSTEM "https://example.invalid/external.dtd"><r/>',
        ]
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(PathError) as caught:
                    parse(source)
                self.assertIn("DTD", str(caught.exception))
                self.assertNotIn("file:///etc/passwd", str(caught.exception))
                self.assertNotIn("example.invalid", str(caught.exception))

    def test_character_limit_and_non_string_input_fail_before_parsing(self):
        source = "<r>" + "é" * (2_000_000 - len("<r></r>")) + "</r>"
        document = parse(source)
        self.assertEqual(document.length, 2_000_000)
        self.assert_path(document, source.index("é"), "r[1]")

        with self.assertRaises(PathError) as caught:
            parse("x" * 2_000_001)
        self.assertIn("2,000,000", str(caught.exception))

        with self.assertRaises(PathError) as caught:
            parse(b"<r/>")
        self.assertNotIn("<r/>", str(caught.exception))

    def test_depth_limit_accepts_128_and_rejects_129_levels(self):
        at_limit = "<x>" * 128 + "</x>" * 128
        document = parse(at_limit)
        self.assertEqual(len(document.path_at(at_limit.rindex("<x>") + 1)), 128)

        over_limit = "<x>" * 129 + "</x>" * 129
        with self.assertRaises(PathError):
            parse(over_limit)

    def test_attribute_paths_obey_the_shared_depth_ceiling(self):
        source = "<r>" * 126 + '<x a="value"/>' + "</r>" * 126
        document = parse(source)
        path = document.path_at(source.index("value"))
        self.assertEqual(len(path), 128)
        self.assertEqual(path[-2:], ("x[1]", "@a"))

        source = "<r>" * 127 + '<x a="value"/>' + "</r>" * 127
        with self.assertRaisesRegex(PathError, "128-level nesting limit"):
            parse(source)

    def test_same_local_name_attributes_keep_their_source_order(self):
        text = (
            '<r xmlns:p="urn:p" xmlns:q="urn:q" '
            'q:a="first" a="second" p:a="third"/>'
        )
        document = parse(text)
        for source, segment in [
            ('q:a="first"', namespaced_attribute("a", "urn:q")),
            ('a="second"', "@a"),
            ('p:a="third"', namespaced_attribute("a", "urn:p")),
        ]:
            with self.subTest(source=source):
                start = text.index(source)
                for offset in range(len(source)):
                    self.assert_path(document, start + offset, "r[1]", segment)
                self.assert_path(document, start - 1, "r[1]")
                self.assert_path(document, start + len(source), "r[1]")

    def test_markup_inside_processing_instructions_and_comments_is_not_parsed(self):
        text = (
            '<?before <outside/>?><r><!-- <!DOCTYPE r> -->'
            '<?inside <ghost/>?><x/></r><?after <outside/>?>\r\n \t'
        )
        document = parse(text)
        self.assert_path(document, text.index("<!DOCTYPE"), "r[1]")
        self.assert_path(document, text.index("<ghost/>"), "r[1]")
        self.assert_path(document, text.index("<x/>"), "r[1]", "x[1]")
        self.assert_path(document, text.index("<outside/>"))
        self.assert_path(document, text.rindex("<outside/>"))
        for point in range(text.index("?>\r\n") + 2, len(text) + 1):
            self.assert_path(document, point)

    def test_namespace_uri_size_is_bounded_before_expanding_names(self):
        uri = "u" * 1024
        source = '<r xmlns:p="{}"><p:x/></r>'.format(uri)
        document = parse(source)
        self.assert_path(document, source.index("p:x"), "r[1]", namespaced_element("x", uri, 1))
        with self.assertRaisesRegex(PathError, "namespace URI.*1,024"):
            parse('<r xmlns:p="{}"><p:x/></r>'.format(uri + "u"))

    def test_span_budget_stops_validation_before_processing_the_tail(self):
        for child, count in [("<x/>", 50_000), ('<x a="1"/>', 25_000)]:
            with self.subTest(child=child):
                source = "<r>" + child * count + "<"
                with self.assertRaisesRegex(PathError, "50,000-node safety limit"):
                    parse(source)

    def test_span_budget_counts_attributes_but_not_namespace_declarations(self):
        source = (
            '<r xmlns:p="urn:u" a="1">'
            + '<x xmlns:q="urn:v" b="2"/>' * 24_999
            + "</r>"
        )
        document = parse(source)
        self.assertEqual(len(document.spans), 50_000)
        self.assert_path(document, source.rindex('b="2"'), "r[1]", "x[24999]", "@b")
        with self.assertRaisesRegex(PathError, "50,000-node safety limit"):
            parse(source.replace("</r>", "<x/></r>"))

    def test_span_limit_accepts_50000_and_rejects_more(self):
        at_limit = "<r>" + "<x/>" * 49_999 + "</r>"
        document = parse(at_limit)
        self.assertEqual(len(document.spans), 50_000)
        self.assert_path(document, at_limit.rindex("<x/>") + 1, "r[1]", "x[49999]")
        del document

        over_limit = "<r>" + "<x/>" * 50_000 + "</r>"
        with mock.patch(
            "copy_path_lib.xml_parser._source_spans",
            side_effect=AssertionError("span limit was checked too late"),
        ):
            with self.assertRaises(PathError):
                parse(over_limit)


if __name__ == "__main__":
    unittest.main()
