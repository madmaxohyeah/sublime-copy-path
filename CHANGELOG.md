# Changelog

## 1.4.0 – 2026-11-26

- YAML parsing now uses Package Control's `pyyaml` library instead of a bundled copy of PyYAML's parser. Package Control installs it with the package. Without the library, copying in a YAML file shows how to install it; JSON and XML are not affected.

## 1.3.0 – 2026-11-24

- The right-click menu settings have clearer names: `show_in_context_menu` is now `show_copy_element_path`, and `show_copy_path_as_submenu` is now `show_submenu_copy_element_path_as`.

## 1.2.0 – 2026-11-23

- The right-click submenu is now called **Copy Element Path As** and no longer contains **Settings…**. The settings are in **Preferences → Package Settings → Copy Path** and the Command Palette.
- `show_in_context_menu` now hides only the top-level **Copy Element Path**, and `show_copy_path_as_submenu` only the entries of the submenu.
- In files that aren't JSON, YAML or XML, the right-click entries are shown greyed out instead of hidden.
- Opening the settings no longer pre-fills your user settings with `json_path_style`.
- The default settings file explains every option.
- Menu and Command Palette captions use an en dash: **XPath – Positional**.

## 1.1.0 – 2026-11-15

- The package is now called **Copy Path**, with a space, everywhere: in Package Control, in the archive name `Copy Path.sublime-package` and in the settings file `Copy Path.sublime-settings`.

## 1.0.1 – 2026-11-15

- The README explains how to remove or customize the right-click menu by replacing the package's `Context.sublime-menu`.

## 1.0.0 – 2026-11-13

First public release.

- Copy the JSONPath or JSON Pointer of the element at the caret or click position in JSON, JSONC and YAML, and its XPath in XML (attribute, positional or text style).
- Commands in the right-click menu and the Command Palette; no default key bindings.
- Multiple carets copy one path per line.
- Settings for the default styles, the format, and hiding the context menu entries.
