"""Independent, deterministic XPath-engine check; not a package dependency."""
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import time

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copy_path_lib.xml_parser import parse
from copy_path_lib.paths import render

rng = random.Random(270926)
values = ['a', 'b', 'same', '', ' ', 'A\'"B', 'é😀', 'A&B', 'Title', 'x' * 128, 'y' * 129]
count = 0
sources = hashlib.sha256()
started = time.monotonic()
for case in range(180):
    # Plain and namespaced same-local-name siblings plus mixed-content collisions.
    root = etree.Element('catalog', nsmap={'p': 'urn:books', 'q': 'urn:other'})
    for group in range(rng.randrange(1, 5)):
        parent = etree.SubElement(root, 'group')
        for item in range(rng.randrange(2, 10)):
            name = rng.choice(['book', 'book', '{urn:books}book', '{urn:other}book'])
            node = etree.SubElement(parent, name)
            for key in ['id', '{http://www.w3.org/XML/1998/namespace}id', 'code', '{urn:books}key']:
                if rng.random() < 0.5:
                    node.set(key, rng.choice(values))
            node.text = rng.choice(values)
            if rng.random() < 0.3:
                child = etree.SubElement(node, 'b')
                child.text = rng.choice(['', 'Title', 'same'])
                child.tail = rng.choice(['', 'Title', 'same'])
    text = etree.tostring(root, encoding='unicode')
    sources.update(text.encode())
    reference = etree.fromstring(text.encode(), etree.XMLParser(collect_ids=False))
    positions = [m.start() + 1 for m in re.finditer(r'<(?![/!?])', text)]
    nodes = list(reference.iter())
    assert len(positions) == len(nodes)
    for style in ('attributes', 'positional', 'text'):
        document = parse(text, style=style)
        for position, node in zip(positions, nodes):
            path = render(document.path_at(position), 'xml')
            selected = reference.getroottree().xpath(path)
            assert len(selected) == 1 and selected[0] is node, (case, style, path, text)
            count += 1

# Quoting, Unicode, entity decoding and namespaces on clicked attributes.
text = '<r xmlns:p="urn:p"><x id="A&apos;&quot;B"/><x p:key="é&amp;😀">Title</x></r>'
reference = etree.fromstring(text.encode())
for style in ('attributes', 'positional', 'text'):
    document = parse(text, style=style)
    for needle, value in [('id=', 'A\'"B'), ('p:key=', 'é&😀')]:
        path = render(document.path_at(text.index(needle)), 'xml')
        assert reference.getroottree().xpath(path) == [value], (style, path)
        count += 1

result = {'passed': True, 'engine': 'lxml/libxml2', 'lxml_version': etree.LXML_VERSION,
          'python': sys.version.split()[0], 'seed': 270926, 'generated_documents': 180,
          'unique_target_assertions': count, 'fixture_sha256': sources.hexdigest(),
          'elapsed_seconds': round(time.monotonic() - started, 3)}
print(json.dumps(result, indent=2))
