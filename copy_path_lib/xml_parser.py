"""Bounded XML source indexing with conservative missing-end-tag recovery."""
from xml.parsers import expat

from .model import MAX_SPANS, Document, PathError, add_span, check_depth, check_text
from .paths import xpath_literal


_NAMESPACE_SEPARATOR = "\x1f"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_XML_WHITESPACE = " \t\r\n"
_MAX_NAMESPACE_URI_CHARS = 1024
_MAX_ATTRIBUTE_VALUE_CHARS = 128
_MAX_TEXT_VALUE_CHARS = 128
_STYLES = ("attributes", "positional", "text")
_EOF_ERROR = expat.errors.codes[expat.errors.XML_ERROR_NO_ELEMENTS]


class _SiblingStats:
    __slots__ = ("name_counts", "attribute_counts", "text_counts")

    def __init__(self):
        self.name_counts = {}
        self.attribute_counts = {}
        self.text_counts = {}


class _Node:
    __slots__ = (
        "name",
        "index",
        "parent",
        "siblings",
        "attributes",
        "children",
        "has_element_child",
        "text_value",
        "text_too_long",
        "path",
    )

    def __init__(self, name, index, parent, siblings, attributes):
        self.name = name
        self.index = index
        self.parent = parent
        self.siblings = siblings
        self.attributes = attributes
        self.children = None
        self.has_element_child = False
        self.text_value = ""
        self.text_too_long = False
        self.path = None

    def child_stats(self):
        if self.children is None:
            self.children = _SiblingStats()
        return self.children

    def append_text(self, value, too_long=False):
        if self.text_too_long:
            return
        remaining = _MAX_TEXT_VALUE_CHARS + 1 - len(self.text_value)
        self.text_value += value[:remaining]
        if too_long or len(value) > remaining or len(self.text_value) > _MAX_TEXT_VALUE_CHARS:
            self.text_too_long = True


def _split_expanded_name(name):
    if _NAMESPACE_SEPARATOR in name:
        uri, local = name.split(_NAMESPACE_SEPARATOR, 1)
        return uri, local
    return "", name


def _element_selector(expanded_name):
    uri, local = expanded_name
    if not uri:
        return local
    return "*[local-name()={} and namespace-uri()={}]".format(
        xpath_literal(local), xpath_literal(uri)
    )


def _attribute_segment(expanded_name):
    uri, local = expanded_name
    if not uri:
        return "@" + local
    return "@*[local-name()={} and namespace-uri()={}]".format(
        xpath_literal(local), xpath_literal(uri)
    )


def _attribute_predicate(expanded_name, value):
    return "[{}={}]".format(_attribute_segment(expanded_name), xpath_literal(value))


def _is_single_line(value):
    return not value or value.splitlines() == [value]


def _is_suitable_attribute(value):
    return (
        bool(value.strip())
        and len(value) <= _MAX_ATTRIBUTE_VALUE_CHARS
        and _is_single_line(value)
    )


def _unique_attribute(node, expanded_name):
    for name, value in node.attributes:
        if name != expanded_name or not _is_suitable_attribute(value):
            continue
        key = (node.name, name, value)
        if node.siblings.attribute_counts.get(key) == 1:
            return name, value
    return None


def _identifying_attribute(node):
    for preferred in (("", "id"), (_XML_NAMESPACE, "id")):
        candidate = _unique_attribute(node, preferred)
        if candidate is not None:
            return candidate

    preferred_names = {("", "id"), (_XML_NAMESPACE, "id")}
    candidates = []
    for name, value in node.attributes:
        if name in preferred_names or not _is_suitable_attribute(value):
            continue
        key = (node.name, name, value)
        if node.siblings.attribute_counts.get(key) == 1:
            candidates.append((name, value))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def _identifying_text(node):
    if (
        node.has_element_child
        or node.text_too_long
        or not node.text_value.strip()
        or not _is_single_line(node.text_value)
    ):
        return None
    key = (node.name, node.text_value)
    if node.siblings.text_counts.get(key) == 1:
        return node.text_value
    return None


def _assign_paths(nodes, style):
    for node in nodes:
        selector = _element_selector(node.name)
        if style == "positional":
            segment = "{}[{}]".format(selector, node.index)
        else:
            text_value = _identifying_text(node) if style == "text" else None
            attribute = _identifying_attribute(node) if style == "attributes" else None
            if text_value is not None:
                segment = selector + "[.={}]".format(xpath_literal(text_value))
            elif attribute is not None:
                segment = selector + _attribute_predicate(*attribute)
            elif node.siblings.name_counts[node.name] == 1:
                segment = selector
            else:
                segment = "{}[{}]".format(selector, node.index)
        parent_path = node.parent.path if node.parent is not None else ()
        node.path = parent_path + (segment,)


def _reject_doctype(*unused):
    raise PathError("DTD declarations are not supported.")


def _reject_entity_declaration(*unused):
    raise PathError("Entity declarations are not supported.")


def _reject_external_entity(*unused):
    raise PathError("External entities are not supported.")


def _check_namespace(unused_prefix, uri):
    # A single huge URI otherwise multiplies into every expanded element/attribute.
    if uri is not None and len(uri) > _MAX_NAMESPACE_URI_CHARS:
        raise PathError("XML namespace URI exceeds the 1,024-character safety limit.")


def _validated_start_events(text, recover):
    parser = expat.ParserCreate(namespace_separator=_NAMESPACE_SEPARATOR)
    parser.ordered_attributes = True
    parser.StartDoctypeDeclHandler = _reject_doctype
    parser.EntityDeclHandler = _reject_entity_declaration
    parser.UnparsedEntityDeclHandler = _reject_entity_declaration
    parser.ExternalEntityRefHandler = _reject_external_entity
    parser.StartNamespaceDeclHandler = _check_namespace
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    nodes = []
    stack = []
    root_stats = _SiblingStats()
    span_count = 0

    def start_element(name, attributes):
        nonlocal span_count
        # Reserve elements and ordinary attributes before buffering any paths.
        span_count += 1 + len(attributes) // 2
        if span_count > MAX_SPANS:
            raise PathError("Document exceeds the 50,000-node safety limit.")

        depth = len(stack) + 1
        check_depth(depth)
        if attributes:
            check_depth(depth + 1)

        expanded_name = _split_expanded_name(name)
        parent = stack[-1] if stack else None
        if parent is not None:
            parent.has_element_child = True
        siblings = parent.child_stats() if parent is not None else root_stats
        index = siblings.name_counts.get(expanded_name, 0) + 1
        siblings.name_counts[expanded_name] = index

        expanded_attributes = []
        for position in range(0, len(attributes), 2):
            attribute_name = _split_expanded_name(attributes[position])
            value = attributes[position + 1]
            expanded_attributes.append((attribute_name, value))
            if _is_suitable_attribute(value):
                key = (expanded_name, attribute_name, value)
                siblings.attribute_counts[key] = siblings.attribute_counts.get(key, 0) + 1

        node = _Node(
            expanded_name,
            index,
            parent,
            siblings,
            expanded_attributes,
        )
        nodes.append(node)
        stack.append(node)

    def end_element(unused_name):
        node = stack.pop()
        if not node.text_too_long:
            key = (node.name, node.text_value)
            node.siblings.text_counts[key] = node.siblings.text_counts.get(key, 0) + 1
        if node.parent is not None:
            node.parent.append_text(node.text_value, node.text_too_long)

    def character_data(value):
        if stack:
            stack[-1].append_text(value)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data

    try:
        parser.Parse(text, True)
    except PathError:
        raise
    except expat.ExpatError as error:
        if recover and error.code == _EOF_ERROR and stack:
            return nodes, True
        raise PathError("Invalid XML document.") from None
    except UnicodeError:
        raise PathError("Invalid XML document.") from None
    return nodes, False


def _is_namespace_declaration(name):
    return name == "xmlns" or name.startswith("xmlns:")


def _skip_xml_whitespace(text, position):
    while position < len(text) and text[position] in _XML_WHITESPACE:
        position += 1
    return position


def _mapping_error():
    raise PathError("Unable to map XML source positions.")


def _scan_start_tag(text, start):
    position = start + 1
    name_start = position
    while position < len(text) and text[position] not in _XML_WHITESPACE + "/>":
        position += 1
    if position == name_start:
        _mapping_error()

    attributes = []
    while True:
        position = _skip_xml_whitespace(text, position)
        if position >= len(text):
            _mapping_error()
        if text[position] == ">":
            return position + 1, False, attributes
        if text[position] == "/":
            if position + 1 < len(text) and text[position + 1] == ">":
                return position + 2, True, attributes
            _mapping_error()

        attribute_start = position
        while (
            position < len(text)
            and text[position] not in _XML_WHITESPACE + "=/><"
        ):
            position += 1
        if position == attribute_start:
            _mapping_error()
        name = text[attribute_start:position]

        position = _skip_xml_whitespace(text, position)
        if position >= len(text) or text[position] != "=":
            _mapping_error()
        position += 1
        position = _skip_xml_whitespace(text, position)
        if position >= len(text) or text[position] not in "'\"":
            _mapping_error()

        quote = text[position]
        closing_quote = text.find(quote, position + 1)
        if closing_quote < 0:
            _mapping_error()
        attribute_end = closing_quote + 1
        attributes.append((name, attribute_start, attribute_end))
        position = attribute_end


def _finish_element(spans, node, end):
    start, event, attributes = node
    add_span(spans, start, end, event.path)
    for attribute_start, attribute_end, attribute_path in attributes:
        add_span(spans, attribute_start, attribute_end, attribute_path)


def _source_spans(text, events, recovered=False):
    spans = []
    open_elements = []
    event_index = 0
    position = 0

    while True:
        start = text.find("<", position)
        if start < 0:
            break

        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            if end < 0:
                _mapping_error()
            position = end + 3
            continue

        if text.startswith("<![CDATA[", start):
            end = text.find("]]>", start + 9)
            if end < 0:
                _mapping_error()
            position = end + 3
            continue

        if text.startswith("<?", start):
            end = text.find("?>", start + 2)
            if end < 0:
                _mapping_error()
            position = end + 2
            continue

        if text.startswith("</", start):
            end = text.find(">", start + 2)
            if end < 0 or not open_elements:
                _mapping_error()
            _finish_element(spans, open_elements.pop(), end + 1)
            position = end + 1
            continue

        if text.startswith("<!", start):
            _mapping_error()

        end, self_closing, lexical_attributes = _scan_start_tag(text, start)
        if event_index >= len(events):
            _mapping_error()
        event = events[event_index]
        event_index += 1

        ordinary_attributes = [
            attribute
            for attribute in lexical_attributes
            if not _is_namespace_declaration(attribute[0])
        ]
        if len(ordinary_attributes) != len(event.attributes):
            _mapping_error()

        mapped_attributes = []
        for lexical, expanded_attribute in zip(ordinary_attributes, event.attributes):
            lexical_name, attribute_start, attribute_end = lexical
            expanded_name = expanded_attribute[0]
            lexical_local = lexical_name.split(":", 1)[-1]
            if lexical_local != expanded_name[1]:
                _mapping_error()
            mapped_attributes.append(
                (
                    attribute_start,
                    attribute_end,
                    event.path + (_attribute_segment(expanded_name),),
                )
            )

        node = (start, event, mapped_attributes)
        if self_closing:
            _finish_element(spans, node, end)
        else:
            open_elements.append(node)
        position = end

    if event_index != len(events):
        _mapping_error()
    if recovered:
        if not open_elements:
            _mapping_error()
    elif open_elements:
        _mapping_error()
    return spans


def parse(text, style="positional", recover=False):
    """Index non-DTD XML; optionally retain completed elements at unclosed EOF."""
    check_text(text)
    if style not in _STYLES:
        raise PathError("Choose attributes, positional or text XML paths.")
    if type(recover) is not bool:
        raise PathError("XML recovery must be enabled or disabled.")
    events, recovered = _validated_start_events(text, recover)
    _assign_paths(events, "positional" if recovered else style)
    spans = _source_spans(text, events, recovered=recovered)
    return Document(len(text), "xml", spans, recovered=recovered)
