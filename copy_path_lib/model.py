"""Shared source spans, hard resource ceilings and user-safe errors."""
from dataclasses import dataclass

MAX_CHARS = 2_000_000
MAX_SPANS = 50_000
MAX_DEPTH = 128
MAX_CARETS = 32


class PathError(ValueError):
    """A supported format cannot safely yield an unambiguous path."""


def check_text(text):
    if not isinstance(text, str) or len(text) > MAX_CHARS:
        raise PathError("Document exceeds the {:,}-character safety limit.".format(MAX_CHARS))


def check_depth(depth):
    """``depth`` counts path segments, so a JSON/YAML root container is depth 0."""
    if depth > MAX_DEPTH:
        raise PathError("Document exceeds the {}-level nesting limit.".format(MAX_DEPTH))


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    path: tuple


def add_span(spans, start, end, path):
    if len(spans) >= MAX_SPANS:
        raise PathError("Document exceeds the {:,}-node safety limit.".format(MAX_SPANS))
    check_depth(len(path))
    spans.append(Span(start, end, tuple(path)))


@dataclass
class Document:
    length: int
    kind: str
    spans: list
    recovered: bool = False

    def path_at(self, point):
        """Deepest (then narrowest) span containing ``point``; spans are half-open."""
        if type(point) is not int or not 0 <= point <= self.length:
            raise PathError("Cursor position is outside the document.")
        best = None
        if point < self.length:
            for span in self.spans:
                if span.start <= point < span.end:
                    rank = (len(span.path), -(span.end - span.start))
                    if best is None or rank > best[0]:
                        best = (rank, span.path)
        if best is not None:
            return best[1]
        if self.recovered:
            raise PathError("Cursor is not inside a complete XML element.")
        return ()
