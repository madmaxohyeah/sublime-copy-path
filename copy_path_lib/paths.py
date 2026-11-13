"""Portable JSONPath, JSON Pointer and namespace-independent XPath."""
import json
import re
from .model import PathError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_XPATH_STYLES = (
    "xpath",
    "xpath_attributes",
    "xpath_positional",
    "xpath_text",
)


def xpath_literal(value):
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"


def render(path, kind, style="auto"):
    if style == "auto":
        style = "xpath_attributes" if kind == "xml" else "jsonpath"
    if kind == "xml":
        if style not in _XPATH_STYLES:
            raise PathError("XML requires XPath, not JSONPath or JSON Pointer.")
        return "/" + "/".join(path)
    if style == "pointer":
        return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)
    if style != "jsonpath":
        raise PathError("JSON and YAML require JSONPath or JSON Pointer.")
    result = "$"
    for part in path:
        if type(part) is int:
            result += "[{}]".format(part)
        elif _IDENTIFIER.fullmatch(part):
            result += "." + part
        else:
            result += "[" + json.dumps(part, ensure_ascii=True) + "]"
    return result
