"""Regenerate invented fixtures deterministically. Writes only data/demo."""
from pathlib import Path
import random


def generate():
    rng = random.Random(42)
    destination = Path(__file__).resolve().parent / 'demo'
    destination.mkdir(parents=True, exist_ok=True)
    groups = {
        'topic': ['Learning', 'Writing', 'Planning', 'Research', 'Wellbeing', 'Technology'],
        'project': ['Demo Reading List', 'Demo Personal Website', 'Demo Study Plan', 'Demo Weekly Review', 'Demo Budget', 'Demo Research Project'],
        'note': [f'Demo Note {i:02}' for i in range(1, 19)],
    }
    titles = [title for values in groups.values() for title in values]
    for kind, values in groups.items():
        for title in values:
            links = rng.sample([t for t in titles if t != title], rng.randint(2, 5))
            content = (f'---\ntype: {kind}\ndemo: true\n---\n\n# {title}\n\n'
                       'Invented demonstration content. This is not a fact about Seth.\n\n'
                       + '\n'.join(f'- [[{link}]]' for link in links) + '\n')
            (destination / f'{title}.md').write_text(content, encoding='utf-8')
    print(f'Generated {len(titles)} invented notes with seed 42.')


if __name__ == '__main__':
    generate()
