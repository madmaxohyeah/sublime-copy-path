"""Strict JSON/JSONC parsing with Unicode source spans.

A single leading U+FEFF is accepted as a byte-order mark.  JSONC mode adds
JavaScript-style comments and trailing commas; every other JSON rule remains
strict.
"""

from json import JSONDecoder

from .model import Document, PathError, add_span, check_depth, check_text


_INVALID = "Invalid JSON document."
_DUPLICATE = "JSON object keys must be unique."
_WHITESPACE = " \t\r\n"


class _Parser:
    def __init__(self, text, comments):
        self.text = text
        self.length = len(text)
        self.comments = comments
        self.index = 0
        self.spans = []
        self.decoder = JSONDecoder()

    def parse(self):
        if self.text.startswith("\ufeff"):
            self.index = 1
        self._skip_ignored()
        if self.index == self.length:
            self._fail()

        self._parse_value(())
        self._skip_ignored()
        if self.index != self.length:
            self._fail()
        return Document(self.length, "json", self.spans)

    def _parse_value(self, path, span_start=None):
        check_depth(len(path))
        value_start = self.index
        if value_start >= self.length:
            self._fail()

        token = self.text[value_start]
        if token == '"':
            self._parse_string()
        elif token == "{":
            self._parse_object(path)
        elif token == "[":
            self._parse_array(path)
        elif token == "t":
            self._parse_literal("true")
        elif token == "f":
            self._parse_literal("false")
        elif token == "n":
            self._parse_literal("null")
        elif token == "-" or "0" <= token <= "9":
            self._parse_number()
        else:
            self._fail()

        if span_start is None:
            span_start = value_start
        add_span(self.spans, span_start, self.index, path)

    def _parse_object(self, path):
        self.index += 1
        self._skip_ignored()
        if self._consume("}"):
            return

        keys = set()
        while True:
            key_start = self.index
            if key_start >= self.length or self.text[key_start] != '"':
                self._fail()
            key = self._parse_string()
            if key in keys:
                raise PathError(_DUPLICATE)
            keys.add(key)

            self._skip_ignored()
            if not self._consume(":"):
                self._fail()
            self._skip_ignored()
            self._parse_value(path + (key,), key_start)
            self._skip_ignored()

            if self._consume("}"):
                return
            if not self._consume(","):
                self._fail()
            self._skip_ignored()
            if self.index < self.length and self.text[self.index] == "}":
                if not self.comments:
                    self._fail()
                self.index += 1
                return

    def _parse_array(self, path):
        self.index += 1
        self._skip_ignored()
        if self._consume("]"):
            return

        item = 0
        while True:
            self._parse_value(path + (item,))
            item += 1
            self._skip_ignored()

            if self._consume("]"):
                return
            if not self._consume(","):
                self._fail()
            self._skip_ignored()
            if self.index < self.length and self.text[self.index] == "]":
                if not self.comments:
                    self._fail()
                self.index += 1
                return

    def _parse_string(self):
        try:
            value, end = self.decoder.raw_decode(self.text, self.index)
        except ValueError:
            raise PathError(_INVALID) from None
        if not isinstance(value, str):
            self._fail()
        self.index = end
        return value

    def _parse_literal(self, literal):
        end = self.index + len(literal)
        if self.text[self.index:end] != literal:
            self._fail()
        self.index = end

    def _parse_number(self):
        index = self.index
        if self.text[index] == "-":
            index += 1
            if index == self.length:
                self._fail()

        if self.text[index] == "0":
            index += 1
        elif "1" <= self.text[index] <= "9":
            index += 1
            while index < self.length and "0" <= self.text[index] <= "9":
                index += 1
        else:
            self._fail()

        if index < self.length and self.text[index] == ".":
            index += 1
            if index == self.length or not "0" <= self.text[index] <= "9":
                self._fail()
            index += 1
            while index < self.length and "0" <= self.text[index] <= "9":
                index += 1

        if index < self.length and self.text[index] in "eE":
            index += 1
            if index < self.length and self.text[index] in "+-":
                index += 1
            if index == self.length or not "0" <= self.text[index] <= "9":
                self._fail()
            index += 1
            while index < self.length and "0" <= self.text[index] <= "9":
                index += 1

        self.index = index

    def _skip_ignored(self):
        index = self.index
        while index < self.length:
            token = self.text[index]
            if token in _WHITESPACE:
                index += 1
                continue
            if not self.comments or token != "/" or index + 1 >= self.length:
                break

            marker = self.text[index + 1]
            if marker == "/":
                index += 2
                while index < self.length and self.text[index] not in "\r\n":
                    index += 1
                continue
            if marker == "*":
                end = self.text.find("*/", index + 2)
                if end < 0:
                    self._fail()
                index = end + 2
                continue
            break
        self.index = index

    def _consume(self, token):
        if self.index < self.length and self.text[self.index] == token:
            self.index += 1
            return True
        return False

    @staticmethod
    def _fail():
        raise PathError(_INVALID)


def parse(text, comments=False):
    """Parse *text* and return source spans for strict JSON or JSONC."""
    check_text(text)
    return _Parser(text, comments).parse()
