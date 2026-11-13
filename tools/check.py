#!/usr/bin/env python3
"""Read-only source/package gate. Run the builder explicitly after edits."""
import ast
import io
import pathlib
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_package import PACKAGE_FILES, package_bytes  # noqa: E402


def check_release_archive():
    """Fail unless the tag archive Package Control installs holds exactly PACKAGE_FILES.

    Package Control downloads GitHub's archive of a version tag, which is
    ``git archive`` honoring ``export-ignore`` in ``.gitattributes``. This
    archives the staged tree the same way and compares its files, and its
    folders (so no empty leftovers), with the builder's list.
    """
    if not (ROOT / '.git').exists():
        return
    tree = subprocess.run(['git', 'write-tree'], cwd=str(ROOT), check=True,
                          stdout=subprocess.PIPE).stdout.decode('ascii').strip()
    data = subprocess.run(['git', 'archive', '--worktree-attributes', '--format=tar', tree],
                          cwd=str(ROOT), check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
    files = {m.name for m in members if m.isfile()}
    folders = {m.name.rstrip('/') for m in members if m.isdir()}
    expected = set(PACKAGE_FILES)
    expected_folders = {str(pathlib.PurePosixPath(name).parent) for name in expected} - {'.'}
    expected_folders |= {str(p) for name in expected_folders for p in pathlib.PurePosixPath(name).parents} - {'.'}
    if files != expected or folders != expected_folders:
        raise SystemExit('Release archive differs from PACKAGE_FILES. Extra: {}; missing: {}. '
                         'Update export-ignore in .gitattributes.'.format(
                             sorted((files - expected) | (folders - expected_folders)),
                             sorted((expected - files) | (expected_folders - folders))))


def main():
    for name in PACKAGE_FILES:
        if name.endswith('.py'):
            ast.parse((ROOT / name).read_text(encoding='utf-8'), filename=name, feature_version=(3, 8))
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, 'tools/runtime_smoke.py', '--self-test'], cwd=str(ROOT), check=True)
    if (ROOT / 'dist/CopyPath.sublime-package').read_bytes() != package_bytes(ROOT):
        raise SystemExit('Package is stale. Run python3 tools/build_package.py.')
    check_release_archive()
    if (ROOT / '.git').exists():
        subprocess.run(['git', 'diff', '--check'], cwd=str(ROOT), check=True)
        subprocess.run(['git', 'diff', '--cached', '--check'], cwd=str(ROOT), check=True)
    print('PASS: syntax, tests, resources, deterministic archive, release archive and whitespace')


if __name__ == '__main__':
    main()
