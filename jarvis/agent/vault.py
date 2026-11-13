"""Build a searchable note graph without accessing source files directly."""
import argparse
from collections import Counter, defaultdict
import json
import re

from . import data


def build_index():
    records, warnings = data.sources()
    names = defaultdict(list)
    for record in records:
        names[record['title'].casefold()].append(record['id'])
        names[record['file'].rsplit('.', 1)[0].casefold()].append(record['id'])
    edges = set()
    for record in records:
        match = re.search(r'^type:\s*([\w-]+)', record['text'], re.MULTILINE)
        record['type'] = match.group(1) if match else record['format']
        for link in re.findall(r'\[\[([^\]]+)\]\]', record['text']):
            target = link.split('|', 1)[0].split('#', 1)[0].strip().removesuffix('.md').casefold()
            candidates = set(names.get(target, []))
            if len(candidates) == 1:
                other = next(iter(candidates))
                if other != record['id']:
                    edges.add(tuple(sorted((record['id'], other))))
            else:
                warnings.append(f'Unresolved or ambiguous link in {record["file"]}: {link}')
    degrees = Counter(endpoint for edge in edges for endpoint in edge)
    for record in records:
        record['connections'] = degrees[record['id']]
    return {'nodes': records, 'edges': [{'source': a, 'target': b} for a, b in sorted(edges)],
            'counts': dict(sorted(Counter(r['type'] for r in records).items())),
            'warnings': warnings, **data.status()}


def search(index, query, limit=5):
    terms = set(re.findall(r'\w+', query.casefold()))
    ranked = []
    for record in index['nodes']:
        title = set(re.findall(r'\w+', record['title'].casefold()))
        body = set(re.findall(r'\w+', record['text'].casefold()))
        score = len(terms & title) * 3 + len(terms & body)
        if score:
            ranked.append({**record, 'score': score})
    return sorted(ranked, key=lambda r: (-r['score'], r['id']))[:limit]


def main():
    parser = argparse.ArgumentParser(description='Print the JARVIS read-only index')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    index = build_index()
    if args.json:
        print(json.dumps(index, indent=2))
        return
    print(f'JARVIS index | {index["source"]}')
    print(f'{len(index["nodes"])} notes | {len(index["edges"])} links')
    for kind, count in index['counts'].items():
        print(f'  {kind}: {count}')
    print('Top 10 hubs:')
    for record in sorted(index['nodes'], key=lambda r: (-r['connections'], r['id']))[:10]:
        print(f'  {record["connections"]:2}  {record["file"]}')
    for warning in index['warnings']:
        print(f'WARNING: {warning}')


if __name__ == '__main__':
    main()
