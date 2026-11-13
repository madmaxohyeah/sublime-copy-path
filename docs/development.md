# Development

## Build and test

Python 3.8 or newer is enough; the tests need no extra packages.

```sh
python3 tools/build_package.py
python3 tools/check.py
```

`build_package.py` writes `dist/CopyPath.sublime-package` from the file list in `PACKAGE_FILES`. The archive is reproducible: the same source always gives the same bytes.

`check.py` checks that the shipped Python files parse as Python 3.8, runs the unit tests and the runtime harness self-tests, compares `dist/` with a fresh build, checks that the release archive (see below) contains exactly `PACKAGE_FILES`, and runs `git diff --check`. It never rebuilds anything itself, so rebuild after changing a shipped file.

The tests are split by area: path model and rendering, JSON, XML, YAML, the engine, the Sublime adapter and the package. The adapter tests use a small fake of the Sublime API, so menu behavior is also checked in a real editor (below).

The vendored PyYAML files are kept byte-identical to the upstream release, and the tests check their hashes. `.gitattributes` exempts only those files from Git's whitespace check.

## XPath cross-check (optional)

`tools/xpath_oracle.py` generates XML fixtures and uses lxml to check that every XPath style selects exactly the intended node. lxml is only needed for this script: install it in a throwaway virtual environment and run the script with that environment's Python.

## Testing in Sublime Text

`tools/runtime_smoke.py` installs the built archive into a fresh portable Sublime Text profile on a separate Xvfb display and runs the cases in `tools/runtime_driver.py`: mouse and keyboard copying, every path style, multiple carets, Unicode, YAML, and malformed documents that must leave the clipboard alone. It also takes screenshots of the context menu. Run it with `--help` for the options. The driver is a test helper and is never packaged.

`tools/Dockerfile.runtime` provides the Linux GUI libraries if your machine lacks them. CI runs the same harness against Sublime Text build 4215, downloaded from sublimetext.com and checked against a pinned SHA-256. Never point the harness at your own Sublime profile, and don't commit Sublime binaries.

## Releasing

1. Update `CHANGELOG.md`, rebuild, run `tools/check.py` and push to `main`. Wait for CI to pass.
2. Tag the commit as `vX.Y.Z` (annotated) and push the tag. Package Control installs GitHub's archive of the newest tag. `export-ignore` in `.gitattributes` limits that archive to `PACKAGE_FILES`, so it matches `dist/` exactly.
3. Upload `dist/CopyPath.sublime-package` and its `.sha256` file to the package website (see its `WEBSITE-README.md`).
