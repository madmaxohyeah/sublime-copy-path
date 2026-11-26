#!/usr/bin/env python3
"""Build the Copy Path archive reproducibly on every platform."""
import argparse
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = (
    '.python-version',
    'CHANGELOG.md',
    'Context.sublime-menu',
    'Copy Path.sublime-settings',
    'Default.sublime-commands',
    'LICENSE',
    'Main.sublime-menu',
    'README.md',
    'copy_path.py',
    'copy_path_lib/__init__.py',
    'copy_path_lib/engine.py',
    'copy_path_lib/json_parser.py',
    'copy_path_lib/model.py',
    'copy_path_lib/paths.py',
    'copy_path_lib/xml_parser.py',
    'copy_path_lib/yaml_parser.py',
    'dependencies.json',
)


def package_bytes(root):
    """Return an allowlisted ZIP with stable order, modes and timestamps."""
    root = Path(root)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(PACKAGE_FILES):
            member = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, (root / name).read_bytes())
    return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args(argv)
    data = package_bytes(ROOT)
    args.output.mkdir(parents=True, exist_ok=True)
    artifact = args.output / 'Copy Path.sublime-package'
    artifact.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (args.output / 'Copy Path.sublime-package.sha256').write_bytes(
        (digest + '  Copy Path.sublime-package\n').encode('ascii')
    )
    print('{}  {}'.format(digest, artifact))


if __name__ == '__main__':
    main()
