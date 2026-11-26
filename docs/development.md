# Development

## Build and test

Use Python 3.10 or newer; CI uses 3.14, like Sublime Text 4215. The tests need PyYAML, which Sublime Text gets from Package Control's `pyyaml` library:

```sh
python3 -m pip install -r tools/requirements-test.txt
python3 tools/build_package.py
python3 tools/check.py
```

`build_package.py` writes `dist/Copy Path.sublime-package` from the file list in `PACKAGE_FILES`. The archive is reproducible: the same source always gives the same bytes.

`check.py` checks that the shipped Python files parse, runs the unit tests and the runtime harness self-tests, compares `dist/` with a fresh build, checks that the release archive (see below) contains exactly `PACKAGE_FILES`, and runs `git diff --check`. It never rebuilds anything itself, so rebuild after changing a shipped file.

The tests are split by area: path model and rendering, JSON, XML, YAML, the engine, the Sublime adapter and the package. The adapter tests use a small fake of the Sublime API, so menu behavior is also checked in a real editor (below).

YAML parsing uses the `pyyaml` library declared in `dependencies.json`, which Package Control installs into Sublime's `Lib/python314` folder. `tools/requirements-test.txt` pins the same PyYAML release for the tests. If the library is missing, YAML copying fails with a status-bar message that says how to install it; JSON and XML are not affected.

## XPath cross-check (optional)

`tools/xpath_oracle.py` generates XML fixtures and uses lxml to check that every XPath style selects exactly the intended node. lxml is only needed for this script: install it in a throwaway virtual environment and run the script with that environment's Python.

## Testing in Sublime Text

`tools/runtime_smoke.py` installs the built archive into a fresh portable Sublime Text profile on a separate Xvfb display and runs the cases in `tools/runtime_driver.py`: mouse and keyboard copying, every path style, multiple carets, Unicode, YAML, and malformed documents that must leave the clipboard alone. It also takes screenshots of the context menu. The profile gets the pinned `pyyaml` wheel unpacked into `Data/Lib/python314`, as Package Control would do, and the YAML case checks that PyYAML is loaded from there. Run it with `--help` for the options. The driver is a test helper and is never packaged.

`tools/Dockerfile.runtime` provides the Linux GUI libraries if your machine lacks them. CI runs the same harness against Sublime Text build 4215 and the `pyyaml` 6.0.4 wheel, both downloaded and checked against pinned SHA-256 hashes. Never point the harness at your own Sublime profile, and don't commit Sublime binaries.

## Releasing

1. Update `CHANGELOG.md`, rebuild, run `tools/check.py` and push to `main`. Wait for CI to pass.
2. Tag the commit as `vX.Y.Z` (annotated) and push the tag. Package Control installs GitHub's archive of the newest tag. `export-ignore` in `.gitattributes` limits that archive to `PACKAGE_FILES`, so it matches `dist/` exactly.
3. Upload `dist/Copy Path.sublime-package` and its `.sha256` file to the package website (see its `WEBSITE-README.md`).
