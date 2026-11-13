"""Safe, source-position-aware YAML parsing using vendored parse events."""

import re

from .model import Document, PathError, MAX_SPANS, add_span, check_depth, check_text
from .vendor.yaml import EventParser
from .vendor.yaml.error import YAMLError
from .vendor.yaml.events import (
    AliasEvent,
    DocumentStartEvent,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
)

_MAX_EVENTS = MAX_SPANS * 3 + 8
_STRING_TAG = "tag:yaml.org,2002:str"
_NON_STRING_IMPLICIT_KEYS = (
    re.compile(
        r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$"
    ),
    re.compile(
        r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?"
        r"|[-+]?\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?"
        r"|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*"
        r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
    ),
    re.compile(
        r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)"
        r"|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$"
    ),
    re.compile(r"^(?:~|null|Null|NULL|)$"),
    re.compile(
        r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
        r"|[0-9][0-9][0-9][0-9] -[0-9][0-9]? -[0-9][0-9]?"
        r"(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9]"
        r"(?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$",
        re.X,
    ),
    re.compile(r"^(?:=)$"),
)


def _is_string_key(event):
    if event.tag is not None:
        # "!" is the YAML non-specific tag: the scalar is resolved as a string.
        return event.tag in (_STRING_TAG, "!")
    if not event.implicit[0]:
        return True
    if event.value == "<<":
        return True
    return not any(pattern.match(event.value) for pattern in _NON_STRING_IMPLICIT_KEYS)


def _line_end(text, start):
    newline = text.find("\n", start)
    if newline < 0:
        return len(text)
    return newline + 1


def _block_collection_end(text, content_end, limit, indent):
    """Include comments owned by a block collection, but stop at dedent."""
    if content_end >= limit:
        return content_end

    if content_end == 0 or text[content_end - 1] in "\r\n":
        end = content_end
        line_start = content_end
    else:
        end = min(_line_end(text, content_end), limit)
        line_start = end
    while line_start < limit:
        line_end = _line_end(text, line_start)
        line = text[line_start:line_end]
        body = line.rstrip("\r\n")
        stripped = body.lstrip(" ")
        if not stripped:
            end = min(line_end, limit)
        elif stripped.startswith("#") and len(body) - len(stripped) >= indent:
            end = min(line_end, limit)
        else:
            break
        line_start = line_end
    return end


def parse(text):
    """Return a bounded YAML document containing semantic source spans."""
    check_text(text)
    spans = []
    add_span(spans, 0, len(text), ())
    stack = []
    documents = 0
    event_count = 0
    anchors = set()

    def complete_node(role, path, start, end, collection_span=False):
        if role is None:
            if not collection_span and end > start:
                add_span(spans, start, end, path)
            return
        parent, property_start = role
        parent["children_end"] = max(parent["children_end"], end)
        if parent["kind"] == "mapping":
            add_span(spans, property_start, max(end, property_start + 1), path)
        elif not collection_span and end > start:
            add_span(spans, start, end, path)

    def begin_node(event):
        if not stack:
            path = ()
            role = None
        else:
            parent = stack[-1]
            if parent["kind"] == "sequence":
                path = parent["path"] + (parent["next_index"],)
                parent["next_index"] += 1
                role = (parent, event.start_mark.index)
            elif parent["expect_key"]:
                if not isinstance(event, ScalarEvent) or not _is_string_key(event):
                    raise PathError("YAML mapping keys must be scalar strings.")
                if event.value in parent["keys"]:
                    raise PathError("YAML mapping contains a duplicate key.")
                parent["keys"].add(event.value)
                parent["pending_key"] = event.value
                parent["pending_start"] = event.start_mark.index
                parent["expect_key"] = False
                return None, None
            else:
                key = parent["pending_key"]
                path = parent["path"] + (key,)
                role = (parent, parent["pending_start"])
                parent["pending_key"] = None
                parent["expect_key"] = True
        check_depth(len(path))
        return path, role

    parser = None
    try:
        parser = EventParser(text)
        while parser.check_event():
            event = parser.get_event()
            event_count += 1
            if event_count > _MAX_EVENTS:
                raise PathError("Document exceeds the 50,000-node safety limit.")

            if isinstance(event, DocumentStartEvent):
                documents += 1
                if documents > 1:
                    raise PathError("YAML streams with multiple documents are not supported.")
                continue

            if isinstance(event, (ScalarEvent, AliasEvent, SequenceStartEvent, MappingStartEvent)):
                if isinstance(event, AliasEvent):
                    if event.anchor not in anchors:
                        raise PathError("YAML aliases require a previously declared anchor.")
                elif event.anchor is not None:
                    # Register collections before their children, allowing recursion
                    # without expanding aliases or constructing tagged objects.
                    anchors.add(event.anchor)
                path, role = begin_node(event)
                if path is None:
                    continue
                start = event.start_mark.index
                if isinstance(event, ScalarEvent) or isinstance(event, AliasEvent):
                    complete_node(role, path, start, event.end_mark.index)
                else:
                    is_mapping = isinstance(event, MappingStartEvent)
                    stack.append({
                        "kind": "mapping" if is_mapping else "sequence",
                        "path": path,
                        "role": role,
                        "start": start,
                        "flow": bool(event.flow_style),
                        "indent": event.end_mark.column,
                        "children_end": event.end_mark.index,
                        "expect_key": is_mapping,
                        "keys": set(),
                        "pending_key": None,
                        "pending_start": None,
                        "next_index": 0,
                    })
                continue

            if isinstance(event, (SequenceEndEvent, MappingEndEvent)):
                if not stack:
                    raise PathError("Invalid YAML document.")
                frame = stack.pop()
                if isinstance(event, MappingEndEvent) != (frame["kind"] == "mapping"):
                    raise PathError("Invalid YAML document.")
                if frame["flow"]:
                    end = event.end_mark.index
                else:
                    end = _block_collection_end(
                        text,
                        frame["children_end"],
                        event.end_mark.index,
                        frame["indent"],
                    )
                if end > frame["start"]:
                    add_span(spans, frame["start"], end, frame["path"])
                complete_node(
                    frame["role"],
                    frame["path"],
                    frame["start"],
                    end,
                    collection_span=True,
                )

        if stack:
            raise PathError("Invalid YAML document.")
    except PathError:
        raise
    except (YAMLError, RecursionError, UnicodeError):
        raise PathError("Invalid YAML document.")
    finally:
        if parser is not None:
            parser.dispose()

    return Document(len(text), "yaml", spans)
