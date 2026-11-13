"""Event-only facade for the vendored pure-Python PyYAML parser."""

from .parser import Parser
from .reader import Reader
from .scanner import Scanner


class EventParser(Reader, Scanner, Parser):
    """Combine PyYAML's reader, scanner and parser without construction."""

    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)

    def dispose(self):
        Parser.dispose(self)


__all__ = ["EventParser"]
