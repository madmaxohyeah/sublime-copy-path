"""Format detection and atomic multi-caret path resolution."""
from dataclasses import dataclass
import os
from .model import MAX_CARETS, PathError, check_text
from .paths import render

FORMATS = ('json', 'jsonc', 'xml', 'yaml')
_JSONC_EXTENSIONS = {
    '.jsonc', '.sublime-settings', '.sublime-keymap', '.sublime-mousemap',
    '.sublime-menu', '.sublime-commands', '.sublime-build', '.sublime-project',
    '.sublime-workspace', '.sublime-color-scheme', '.sublime-theme',
    '.sublime-completions', '.sublime-file-icons', '.sublime-macro',
    '.sublime-merge-theme', '.hidden-color-scheme', '.sublime_session',
}
_XML_EXTENSIONS = {'.xml', '.xhtml', '.svg', '.xsl', '.xslt', '.xsd', '.plist', '.wsdl', '.resx'}


@dataclass(frozen=True)
class Resolution:
    paths: list
    recovered: bool


def detect_format(filename=None, scope='', override='auto'):
    """Explicit override, then whole-buffer syntax, then extension for plain text."""
    if override != 'auto':
        if override not in FORMATS:
            raise PathError('Unknown format override; choose json, jsonc, xml or yaml.')
        return override
    extension = os.path.splitext(filename or '')[1].lower()
    base = (scope or '').split(' ')[0]
    # Exact scope or a sub-scope only: source.json5 / source.jsonnet are other languages.
    if base == 'source.json' or base.startswith('source.json.'):
        return 'jsonc' if ('comment' in base or extension in _JSONC_EXTENSIONS) else 'json'
    if base in ('text.xml', 'source.xml') or base.startswith(('text.xml.', 'source.xml.')):
        return 'xml'
    if extension == '.xhtml' and base == 'text.html.basic':
        # Sublime's bundled HTML syntax owns .xhtml; still validate it as XML.
        return 'xml'
    if base == 'source.yaml' or base.startswith('source.yaml.'):
        return 'yaml'
    if base and base not in ('text.plain', 'text.plain.null'):
        return None
    if extension in _JSONC_EXTENSIONS:
        return 'jsonc'
    if extension == '.json':
        return 'json'
    if extension in _XML_EXTENSIONS:
        return 'xml'
    if extension in ('.yml', '.yaml'):
        return 'yaml'
    return None


def _xml_parser_style(style):
    if style in ('auto', 'xpath_attributes'):
        return 'attributes'
    if style in ('xpath', 'xpath_positional'):
        return 'positional'
    if style == 'xpath_text':
        return 'text'
    raise PathError('XML requires XPath, not JSONPath or JSON Pointer.')


def _path_near(document, point):
    """Path of the element at ``point``, attaching a caret that ends a value to that value.

    Spans are half-open, so a caret directly after a value (the End key, a
    double-click selection, a click on the right half of the last character)
    sits outside it and would yield the parent. When the character before the
    caret belongs to a strictly deeper descendant, that descendant wins. Ties
    keep ``point``, so a caret between two siblings still selects the next one.
    """
    try:
        path = document.path_at(point)
    except PathError:
        if point == 0:
            raise
        return document.path_at(point - 1)  # Recovered XML: only completed elements count.
    if point > 0:
        try:
            before = document.path_at(point - 1)
        except PathError:
            return path
        if len(before) > len(path) and before[:len(path)] == path:
            return before
    return path


def _check_copyable(paths):
    """Refuse paths the clipboard cannot hold, or that would be ambiguous one per line."""
    for path in paths:
        try:
            path.encode('utf-8')
        except UnicodeEncodeError:
            raise PathError('The path contains an invalid character and cannot be copied.') from None
    if len(paths) > 1 and any(path.splitlines() not in ([], [path]) for path in paths):
        raise PathError('A path contains a line break; copy it with a single caret.')


def resolve_with_status(text, points, kind, style='auto'):
    """Resolve each caret position to a rendered path, de-duplicated in caret order."""
    check_text(text)
    if kind not in FORMATS:
        raise PathError('Choose JSON, JSONC, XML or YAML syntax first.')
    if not points or len(points) > MAX_CARETS:
        raise PathError('Choose between 1 and {} carets.'.format(MAX_CARETS))
    if any(type(point) is not int or not 0 <= point <= len(text) for point in points):
        raise PathError('Cursor position is outside the document.')
    render((), kind, style)  # Reject an incompatible style before doing parser work.
    try:
        if kind in ('json', 'jsonc'):
            from .json_parser import parse
            document = parse(text, comments=(kind == 'jsonc'))
        elif kind == 'xml':
            from .xml_parser import parse
            document = parse(text, style=_xml_parser_style(style), recover=True)
        else:
            from .yaml_parser import parse
            document = parse(text)
        paths = list(dict.fromkeys(
            render(_path_near(document, point), document.kind, style)
            for point in points
        ))
        _check_copyable(paths)
        return Resolution(paths, document.recovered)
    except RecursionError:
        raise PathError('Document is too deeply nested.') from None


def resolve_many(text, points, kind, style='auto'):
    return resolve_with_status(text, points, kind, style).paths


def resolve(text, point, kind, style='auto'):
    return resolve_many(text, [point], kind, style)[0]
