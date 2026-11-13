# Copy Path for Sublime Text

Copy the structural path of the element under your mouse or caret—not the file's filesystem path.

- **JSON and JSONC:** JSONPath (`$.users[0].name`) or JSON Pointer (`/users/0/name`).
- **XML, XHTML, SVG, XSLT, XSD and XML plist:** absolute XPath (`/catalog/book[@id='b']/@id`), with attribute, positional or text preference.
- **YAML:** JSONPath or JSON Pointer for string-keyed mappings and sequences.
- Native right-click menu and Command Palette. Works on unsaved changes, without altering text or selections.
- Self-contained: no Python installation, network access or telemetry required; Package Control is optional.

Requires **Sublime Text 4** and is tested with build 4215. The plugin runs in Sublime's Python 3.8 plugin host.

## Install

**Package Control:** open the Command Palette, run **Package Control: Install Package** and choose **CopyPath**. Updates install automatically.

**Manually:**

1. Download **`CopyPath.sublime-package`** from the package website or this repository's `dist/` folder.
2. In Sublime Text, choose **Preferences → Browse Packages…**.
3. Go **up one folder**, then open or create **`Installed Packages`**.
4. Place **`CopyPath.sublime-package`** there **without extracting or renaming it**, then restart Sublime Text.

Do not put the ZIP inside `Packages/User` or double-click it to install. To update, replace the same file and restart. To uninstall, remove that file (or use **Package Control: Remove Package**) and optionally `Packages/User/CopyPath.sublime-settings`. Remove any unpacked development `Packages/CopyPath` copy before using a release archive; otherwise it can override the release.

## Use

**Mouse:** right-click the desired key, value, tag or attribute and choose **Copy Element Path**. The clicked position wins, even if the caret is somewhere else. **Copy Path As** exposes compatible explicit formats.

**Keyboard:** place one or more carets, open the Command Palette, and choose **Copy Path: Copy Element Path**, **Copy Path: Copy JSONPath**, **Copy Path: Copy JSON Pointer**, or one of the **Copy Path: XPath — …** actions. For a nonempty selection the active end is used, not its beginning. A caret directly after a value, for example after double-clicking it or pressing End, copies that value's path. Multiple carets copy unique paths in selection order, one per line. There are no default keybindings; add one if desired:

```json
{ "keys": ["ctrl+alt+c"], "command": "copy_element_path" }
```

For macOS, choose an unused `super` combination instead. These are optional examples, not installed bindings.

```json
{"users": [{"name": "Ada", "a/b~c": 42}]}
```

- On `Ada` or `name`: `$.users[0].name`, or `/users/0/name`.
- On `42`: `$.users[0]["a/b~c"]`, or `/users/0/a~1b~0c`.
- JSONPath arrays start at **0**. Unusual keys use JSON-escaped double-quoted brackets.

```xml
<catalog><book id="a"/><book id="b">Title</book></catalog>
```

On the second `book` tag or its text:

- **Copy Element Path** defaults to **XPath — Prefer Attributes**: `/catalog/book[@id='b']`.
- **Copy Path As → XPath — Positional**: `/catalog[1]/book[2]`.
- **Copy Path As → XPath — Prefer Text**: `/catalog/book[.='Title']`.
- On its `id` name/value, the default is `/catalog/book[@id='b']/@id`—the clicked attribute, not its containing element.

Attribute preference tries `id`, then `xml:id`, then other suitable attributes, checking uniqueness among same-name siblings rather than assuming an `id` is unique. Other attributes are chosen deterministically by expanded name; blank, multiline or longer-than-128-character values are unsuitable. Text preference uses nonblank, single-line leaf-element string values of at most 128 characters and checks against all same-name siblings, including mixed-content elements. Descriptive styles omit unnecessary positions; ambiguous or unsuitable steps fall back to positions. Text preference does not fall back to attribute predicates. Positional mode always includes each element's ordinal. Explicit submenu choices do not change your default.

- XPath sibling positions start at **1** and count matching expanded names only.
- Namespaced nodes use `*[local-name()='book' and namespace-uri()='urn:books'][1]`, not prefixes requiring a separate namespace map. Namespace declarations select their containing element.

Containers own their brackets/tags and intervening whitespace. A property owns its key, colon and value. XML closing tags select the matching element; text, comments and CDATA select their containing element. For well-formed XML, outside the root the path is `/`. At end-of-file the document/root path is selected; incomplete-XML recovery refuses these uncertain locations. A root JSON Pointer is the **empty string**; copying it intentionally clears the clipboard and the status message explains this.

## Supported input and limits

- **JSON:** strict JSON, including top-level scalars. Duplicate keys and malformed/truncated input are rejected.
- **JSONC:** comments and trailing commas. Use a `.jsonc` filename with the built-in JSON syntax, or set the format override to `jsonc` for an untitled buffer or a file named `.json`. Build 4215 has no separate built-in “JSON with Comments” syntax. Sublime's JSON resource extensions (including `.sublime-completions`, `.sublime-file-icons`, `.sublime-macro` and `.sublime-merge-theme`) are treated as JSONC.
- **XML:** well-formed XML, plus the bounded recovery described below. No schema validation is required. DTDs are rejected, so external and custom entities are never expanded. Predefined XML entities work. This is not an HTML parser.
- **YAML:** single-document block/flow mappings and sequences, quoted/block scalars, scalar **string keys**. Mapping keys use YAML 1.1 implicit typing: quote numeric, boolean-like (`yes`, `on`, `true`) and null-like keys. Complex or typed keys and duplicates are rejected. Anchors, aliases and `<<` merge keys describe their **literal source locations**, not expanded/merged data. Unknown value tags never instantiate Python objects. Do not assume YAML paths refer to a loader's post-merge result.
- Unsupported: JSON5, TOML, generic HTML, CSV, embedded data inside another language, YAML multi-document streams and complex keys.
- Hard limits: **2,000,000 characters**, **50,000 indexed spans**, **128 path levels**, **32 carets**. XML namespace URIs are capped at **1,024 characters** to prevent expanded-name memory amplification. YAML additionally bounds parser events. Parsing happens on demand off the UI thread; large files are not scanned while typing.

Except for the bounded XML recovery below, a malformed or unsupported document leaves the clipboard unchanged and gives a short status-bar reason. Fix the document or choose its syntax. If you edit, move the selection, close the view or switch tabs before parsing finishes, that outdated result is discarded. No document text is logged.

### Incomplete XML

When the document ends with missing ancestor closing tags, a completed element can still yield a reliable **positional** path. For example, copying the second book from this unfinished document produces `/catalog[1]/book[2]`:

```xml
<catalog><book id="a"/><book id="b">Title</book>
```

The status bar explicitly says **Copied positional XPath from incomplete XML.** This fallback applies even when attributes or text are preferred, since unclosed ancestors prevent proving sibling uniqueness. The buffer is never repaired or changed.

Recovery does **not** accept mismatched tags, unfinished tags/quotes/comments/CDATA, undefined entities, DTDs, or resource-limit failures. Only completed elements and their attributes are selectable; open ancestors, trailing gaps and EOF are refused. If any caret is uncertain, nothing is copied. JSON/JSONC/YAML still require a valid supported document.

## Settings

Open **Copy Path As → Settings…**, **Preferences → Package Settings → Copy Path → Settings**, or **Preferences: Copy Path Settings** in the Command Palette. Defaults:

```json
{
  "format": "auto",
  "json_path_style": "jsonpath",
  "xml_path_style": "attributes",
  "show_in_context_menu": true,
  "show_copy_path_as_submenu": true,
  "max_file_chars": 2000000
}
```

- `format`: `auto`, `json`, `jsonc`, `xml` or `yaml`. Automatic detection prefers the selected whole-buffer syntax; extension fallback is used for plain text. One targeted exception handles `.xhtml` files assigned Sublime's built-in HTML syntax: these are parsed as XML, while ordinary `.html` remains unsupported. Choose a supported syntax for an untitled buffer.
- `json_path_style`: `jsonpath` or `pointer`. Affects the automatic action in JSON/YAML only; XML always uses XPath.
- `xml_path_style`: `attributes` (default), `positional` or `text`. Controls **Copy Element Path** for XML only.
- `show_in_context_menu`: when `false`, hide **Copy Element Path** and all submenu copy actions, but keep **Copy Path As → Settings…** so copying can be turned back on.
- `show_copy_path_as_submenu`: when `false`, show only **Settings…** inside **Copy Path As**, while retaining **Copy Element Path** if `show_in_context_menu` is `true`. This controls the submenu's copy choices, not its structural parent: native Windows menus cannot reliably hide an empty parent.
- Neither visibility setting removes Command Palette actions. In unsupported document types the copy entries are hidden; on Linux the **Copy Path As** heading is hidden too, while Windows and macOS (which always show submenu headings) keep the Settings-only heading.
- `max_file_chars`: positive integer up to the hard limit. Invalid settings safely fall back to defaults.
- A view/project setting named `copy_path_format` overrides `format` for that view/project; useful for JSONC files named `.json`.

## Development

```sh
python3 tools/build_package.py
python3 tools/check.py
```

`build_package.py` writes `dist/CopyPath.sublime-package`; `check.py` runs the tests and fails if that file is out of date. See [development](docs/development.md) and [architecture](docs/architecture.md) for details.

## License

MIT; see [LICENSE](LICENSE). Vendored PyYAML parser components have their own MIT notice and provenance under `copy_path_lib/vendor/`.
