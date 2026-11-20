"""In-memory note index, wikilink graph, citations, and Stage 1 reporting."""
from __future__ import annotations
import re
from collections import Counter

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def _frontmatter_title(record):
    return record["title"].strip()


def build_index(records):
    records = list(records)
    by_title = {}
    for i, record in enumerate(records):
        by_title.setdefault(_frontmatter_title(record).casefold(), []).append(i)
    edges, unresolved, ambiguous = set(), [], []
    for source_i, record in enumerate(records):
        for raw in WIKILINK.findall(record["content"]):
            target = raw.strip().casefold()
            matches = by_title.get(target, [])
            if len(matches) == 1:
                edges.add((source_i, matches[0]))
            elif len(matches) > 1:
                ambiguous.append({"from": record["path"], "target": raw.strip()})
            else:
                unresolved.append({"from": record["path"], "target": raw.strip()})
    degree = Counter()
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    hubs = sorted(((degree[i], records[i]["title"], records[i]["path"])
                   for i in range(len(records))), key=lambda row: (-row[0], row[1].casefold(), row[2]))
    excerpts = []
    for record in records:
        useful = next(((n, line.strip()) for n, line in enumerate(record["content"].splitlines(), 1)
                       if line.strip() and not line.startswith("<!--") and not line.startswith("---")
                       and not line.startswith("type:") and not line.startswith("title:")
                       and not line.startswith("#")), (1, ""))
        excerpts.append({"title": record["title"], "source": record["source"],
                         "path": record["path"], "line": useful[0], "excerpt": useful[1]})
    return {"records": records, "edges": sorted(edges), "unresolved": unresolved,
            "ambiguous": ambiguous, "hubs": hubs[:10], "counts_by_type": dict(sorted(Counter(r["kind"] for r in records).items())),
            "citations": excerpts}


def print_report(index, diagnostics):
    print(f"JARVIS Stage 1 index - {diagnostics['mode']}")
    print("File counts by type:")
    for kind, count in index["counts_by_type"].items():
        print(f"  {kind}: {count}")
    print(f"  total: {len(index['records'])}")
    print("Top 10 hubs (degree, title, path):")
    for degree, title, path in index["hubs"]:
        print(f"  {degree:>2}  {title} - {path}")
    print(f"Resolved links: {len(index['edges'])}; unresolved: {len(index['unresolved'])}; ambiguous: {len(index['ambiguous'])}")
    for item in index["unresolved"]:
        print(f"  unresolved: {item['from']} -> [[{item['target']}]]")
    for item in index["ambiguous"]:
        print(f"  ambiguous: {item['from']} -> [[{item['target']}]]")
    print(f"Skipped files: {len(diagnostics['skipped'])}")
    for item in diagnostics["skipped"]:
        print(f"  {item['path']}: {item['reason']}")
    print(f"Extraction/read failures: {len(diagnostics['failures'])}")
    for item in diagnostics["failures"]:
        print(f"  {item['path']}: {item['reason']}")
    if not diagnostics["pdf_extractor_available"]:
        print("PDF note: no approved pypdf extractor is installed; PDFs will be reported as skipped.")

