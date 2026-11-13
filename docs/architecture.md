# Architecture

## Parsing

`copy_path_lib` contains everything that doesn't need Sublime, so it can be tested on its own. Each format has a parser that validates the whole buffer and returns a `Document`: a list of source spans (start and end offsets), each with the path of its element. Working with source positions instead of re-serialized data means duplicate values, escapes, whitespace and unsaved edits all map back to the right element.

- `json_parser.py` is a small validating scanner. A property's span covers its key, colon and value.
- `xml_parser.py` validates with Expat, then scans the source a second time to get character offsets and namespace-expanded names. DTDs are rejected before any entity is processed. Sibling counts are kept per name, so positions and uniqueness checks never rescan siblings. If the file ends with unclosed ancestors, completed elements can still get a positional path (see the README).
- `yaml_parser.py` reads parser events from the vendored, pure-Python PyYAML. It never constructs objects from tags and never expands aliases; anchors, aliases and merge keys are reported at their literal position.
- `model.py` holds the limits and picks the deepest span containing the caret (the narrowest one on a tie). `paths.py` renders JSONPath, JSON Pointer and XPath. `engine.py` detects the format and resolves all carets at once, removing duplicates while keeping their order.

Parser errors are raised as `PathError` and never include document text.

## Editor side

`copy_path.py` is the only module that imports the Sublime API. A right-click uses the click position (`want_event()` and `window_to_text()`); the Command Palette uses the carets. The plugin never changes the buffer, the selection or the caret.

The buffer and selections are captured on the UI thread after the size check, parsed with `set_timeout_async`, and the result is applied back on the UI thread. The clipboard is only written if nothing changed in the meantime: same view, still active, no edits, same selection, same format and no newer request. Because the clipboard is global, a newer request always wins, even if it fails. Closing the view or unloading the plugin cancels pending work.

Menu visibility depends only on syntax and settings; it never parses the buffer. The **Copy Path As** submenu has a no-op command (`copy_path_menu`) whose visibility check hides it outside supported files on Linux. Windows and macOS always draw submenu headings, so the submenu always ends with **Settings…** and is never empty.

## Safety and limits

Document text is treated as untrusted: no `eval`, no object construction, no entity or alias expansion, and parser exceptions aren't logged. Malformed documents and duplicate keys are rejected instead of guessing a path. The limits (characters, spans, path depth, carets, namespace length) are checked before the buffer is copied and while parsing. Settings can lower the file size limit but never raise it.

## Packaging

`tools/build_package.py` owns the list of shipped files. Entries are stored uncompressed, with fixed timestamps, fixed modes and sorted names, so the same source always produces the same archive. Tests, test drivers and Sublime binaries are never included.
