import unittest

from copy_path_lib.model import PathError
from copy_path_lib.paths import xpath_literal
from copy_path_lib.xml_parser import parse


def namespaced_element(local, uri):
    return "*[local-name()={} and namespace-uri()={}]".format(
        xpath_literal(local), xpath_literal(uri)
    )


def namespaced_attribute(local, uri):
    return "@*[local-name()={} and namespace-uri()={}]".format(
        xpath_literal(local), xpath_literal(uri)
    )


class XmlStyleTests(unittest.TestCase):
    def test_attributes_style_prefers_unique_ids_and_omits_singleton_positions(self):
        text = '<catalog><book id="a"/><book id="b">Title</book></catalog>'

        document = parse(text, style='attributes')

        self.assertEqual(
            document.path_at(text.index('Title')),
            ('catalog', "book[@id='b']"),
        )
        self.assertEqual(
            document.path_at(text.index('id="b"')),
            ('catalog', "book[@id='b']", '@id'),
        )
        self.assertFalse(document.recovered)

    def test_text_style_prefers_unique_short_leaf_string_values(self):
        text = '<catalog><book id="a"/><book id="b">Title</book></catalog>'

        document = parse(text, style='text')

        self.assertEqual(
            document.path_at(text.index('Title')),
            ('catalog', "book[.='Title']"),
        )

    def test_attribute_priority_is_id_then_xml_id_then_deterministic_attribute(self):
        xml_namespace = 'http://www.w3.org/XML/1998/namespace'
        cases = [
            (
                '<r><item id="a" xml:id="x" code="z"/>'
                '<item id="b" xml:id="y" code="q"/></r>',
                "item[@id='b']",
            ),
            (
                '<r><item id="same" xml:id="x" code="z"/>'
                '<item id="same" xml:id="y" code="q"/></r>',
                "item[{}='y']".format(namespaced_attribute('id', xml_namespace)),
            ),
            (
                '<r><item id="same" xml:id="same" z="z1" a="a1"/>'
                '<item id="same" xml:id="same" z="z2" a="a2"/></r>',
                "item[@a='a2']",
            ),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected):
                document = parse(text, style='attributes')
                self.assertEqual(
                    document.path_at(text.rindex('<item') + 1),
                    ('r', expected),
                )

    def test_ambiguous_siblings_and_ancestors_keep_positions(self):
        text = (
            '<r><group><item id="same"/></group>'
            '<group><item id="same"/></group></r>'
        )

        document = parse(text, style='attributes')

        self.assertEqual(
            document.path_at(text.rindex('<item') + 1),
            ('r', 'group[2]', "item[@id='same']"),
        )

        duplicate_text = '<r><item id="same"/><item id="same"/></r>'
        document = parse(duplicate_text, style='attributes')
        self.assertEqual(
            document.path_at(duplicate_text.rindex('<item') + 1),
            ('r', 'item[2]'),
        )

    def test_namespaced_selectors_and_literals_are_prefix_independent(self):
        uri = "urn:u'\"v"
        value = "a'\"b"
        text = (
            '<r xmlns:p="urn:u&apos;&quot;v">'
            '<p:item p:key="a&apos;&quot;b"/><p:item p:key="other"/>'
            '</r>'
        )
        item = namespaced_element('item', uri)
        attribute = namespaced_attribute('key', uri)
        expected_item = '{}[{}={}]'.format(item, attribute, xpath_literal(value))

        document = parse(text, style='attributes')

        self.assertEqual(
            document.path_at(text.index('p:item') + 1),
            ('r', expected_item),
        )
        self.assertEqual(
            document.path_at(text.index('p:key') + 1),
            ('r', expected_item, attribute),
        )
        self.assertIn('concat(', expected_item)

    def test_text_uniqueness_includes_mixed_content_same_name_siblings(self):
        text = '<r><item>same</item><item><b/>same</item></r>'

        document = parse(text, style='text')

        self.assertEqual(
            document.path_at(text.index('same')),
            ('r', 'item[1]'),
        )
        self.assertEqual(
            document.path_at(text.rindex('same')),
            ('r', 'item[2]'),
        )

    def test_text_style_is_bounded_nonblank_and_falls_back_to_positions(self):
        at_limit = 'x' * 128
        over_limit = 'y' * 129
        text = (
            '<r><item id="short">{}</item><item id="long">{}</item>'
            '<item id="blank"> \n\t </item></r>'
        ).format(at_limit, over_limit)

        document = parse(text, style='text')

        self.assertEqual(
            document.path_at(text.index(at_limit)),
            ('r', 'item[.={}]'.format(xpath_literal(at_limit))),
        )
        self.assertEqual(
            document.path_at(text.index(over_limit)),
            ('r', 'item[2]'),
        )
        self.assertEqual(
            document.path_at(text.index(' \n\t ')),
            ('r', 'item[3]'),
        )

    def test_text_literals_use_decoded_string_values_and_safe_quotes(self):
        # Predicate quoting is tested separately from clipboard line framing.
        value = "A&'\"B"
        text = '<r><item>A&amp;&apos;&quot;B</item><item>other</item></r>'

        document = parse(text, style='text')

        self.assertEqual(
            document.path_at(text.index('A&amp;')),
            ('r', 'item[.={}]'.format(xpath_literal(value))),
        )
        self.assertIn('concat(', document.path_at(text.index('A&amp;'))[-1])

    def test_attribute_predicates_reject_decoded_line_breaks(self):
        for codepoint in (10, 13, 133, 8232, 8233):
            for suffix in ('', 'b'):
                text = '<r><x id="a&#{};{}"/><x id="c"/></r>'.format(codepoint, suffix)
                with self.subTest(codepoint=codepoint, suffix=suffix):
                    path = parse(text, style='attributes').path_at(text.index('id='))
                    self.assertEqual(path, ('r', 'x[1]', '@id'))

    def test_text_predicates_reject_line_breaks(self):
        for value in ('a\nb', 'a\r\nb', 'a\r', 'a\x85b', 'a\u2028b', 'a\u2029b'):
            text = '<r><x>{}</x><x>c</x></r>'.format(value)
            with self.subTest(value=value):
                path = parse(text, style='text').path_at(text.index('<x>') + 1)
                self.assertEqual(path, ('r', 'x[1]'))

    def test_recovery_returns_only_complete_elements_with_positional_paths(self):
        text = '<catalog><book id="a"/> \n<book id="b">Title</book>'

        document = parse(text, style='attributes', recover=True)

        self.assertTrue(document.recovered)
        self.assertEqual(
            document.path_at(text.index('Title')),
            ('catalog[1]', 'book[2]'),
        )
        self.assertEqual(
            document.path_at(text.index('id="a"')),
            ('catalog[1]', 'book[1]', '@id'),
        )
        for point in [text.index('<catalog>'), text.index(' \n'), len(text)]:
            with self.subTest(point=point):
                with self.assertRaisesRegex(PathError, 'complete XML element'):
                    document.path_at(point)

    def test_recovery_rejects_everything_except_missing_ancestor_end_tags(self):
        invalid = [
            '<r><x',
            '<r a="unterminated',
            '<r><x></r>',
            '<r><x/>&undefined;',
            '<!DOCTYPE r><r><x/>',
            '<r><!-- unfinished',
            '<r><![CDATA[unfinished',
            '<r><?unfinished',
            '<r><x/></r><',
        ]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(PathError):
                    parse(text, recover=True)

    def test_recovery_does_not_bypass_resource_or_argument_limits(self):
        with self.assertRaisesRegex(PathError, '128-level'):
            parse('<x>' * 129, recover=True)
        with self.assertRaisesRegex(PathError, '2,000,000-character'):
            parse('x' * 2_000_001, recover=True)
        with self.assertRaisesRegex(PathError, '50,000-node'):
            parse('<r>' + '<x/>' * 50_000, recover=True)
        with self.assertRaises(PathError):
            parse('<r/>', style='unknown')
        with self.assertRaises(PathError):
            parse('<r/>', recover='yes')


if __name__ == '__main__':
    unittest.main()
