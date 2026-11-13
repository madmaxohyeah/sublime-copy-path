# Vendored PyYAML provenance

- Upstream project: PyYAML
- Version: 6.0.3
- Source: official PyPI source distribution `pyyaml-6.0.3.tar.gz`
- Source URL: https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz
- Source distribution SHA-256: `d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f`
- Retrieved and verified: 2026-09-26
- License: MIT; exact upstream `LICENSE` retained beside this file.

The following files are copied byte-for-byte from `lib/yaml/` in that source distribution:

| File | SHA-256 |
| --- | --- |
| `error.py` | `021f73fada072546c4f63f8cf18a7181244ce4280b09cc15cc980b2d1176171a` |
| `events.py` | `e74fd392c810884e2ea7e94aa3f57e9c1cbeb402319083d0c58e6a0e1282787c` |
| `parser.py` | `8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a` |
| `reader.py` | `d1d9b38ab3a20c6e17a38d519ee412ecaf6b918df18c78956ac7c330d4ea08dc` |
| `scanner.py` | `60433788b652690c17710460da5d91e0c753d3318fd85f5e1e42862a71f25906` |
| `tokens.py` | `953408cd2570f0c83dc2fe39f7e4e388e41eeb05738aa69196a5f6ffcf6ba79e` |
| `LICENSE` | `8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4` |

`__init__.py` is a project-authored, event-only facade. It deliberately combines only the upstream reader, scanner, and parser with relative imports. No loader, composer, constructor, resolver, representer, serializer, C extension, or runtime dependency installation is included. The application consumes parse events only; it never constructs Python objects or expands aliases.
