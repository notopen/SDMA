"""Connect compact physical templates and enumerate their grid embeddings."""
from collections import deque
import itertools

import networkx as nx


def bounds(qubits, positions):
    xs, ys = zip(*(positions[q] for q in qubits))
    return [min(xs), max(xs), min(ys), max(ys)]


def embeddings(template, graph, positions):
    """All grid translations/reflections/axis-swaps preserving template edges."""
    lookup = {tuple(xy): q for q, xy in positions.items()}
    xs, ys = zip(*positions.values())
    edges = [(template.index(a), template.index(b)) for a, b in graph.subgraph(template).edges]
    seen = set()
    for swap, sx, sy in itertools.product((False, True), (-1, 1), (-1, 1)):
        points = [(positions[q][1], positions[q][0]) if swap else positions[q] for q in template]
        points = [(x*sx, y*sy) for x, y in points]
        mx, my = min(x for x, y in points), min(y for x, y in points)
        points = [(x-mx, y-my) for x, y in points]
        width, height = max(x for x, y in points), max(y for x, y in points)
        for dx in range(min(xs), max(xs)-width+1):
            for dy in range(min(ys), max(ys)-height+1):
                mapped = [lookup.get((x+dx, y+dy)) for x, y in points]
                if None in mapped or tuple(mapped) in seen:
                    continue
                if all(graph.has_edge(mapped[a], mapped[b]) for a, b in edges):
                    seen.add(tuple(mapped))
                    yield mapped


def templates_for(width, graph, positions, limit=2):
    """Bounded compact-shape family; bends allowed, no aspect-ratio cutoff."""
    shapes = {}
    for start in sorted(graph):
        for sx, sy in itertools.product((-1, 1), repeat=2):
            reached, seen, queue = [start], {start}, deque([start])
            while queue and len(reached) < width:
                node = queue.popleft()
                for nxt in sorted(graph[node], key=lambda q: (sy*positions[q][1], sx*positions[q][0])):
                    if nxt not in seen:
                        reached.append(nxt)
                        seen.add(nxt)
                        queue.append(nxt)
                        if len(reached) == width:
                            break
            if len(reached) != width:
                continue
            ordered = sorted(reached, key=lambda q: (positions[q][1], positions[q][0]))
            bx = bounds(ordered, positions)
            points = [(positions[q][0]-bx[0], positions[q][1]-bx[2]) for q in ordered]
            key = tuple(points)
            w, h = bx[1]-bx[0], bx[3]-bx[2]
            ps = set(points)
            symmetry = sum((w-x, y) in ps for x, y in ps) + sum((x, h-y) in ps for x, y in ps)
            shapes.setdefault(key, (ordered, (w == 0 or h == 0, (w+1)*(h+1), -symmetry/width,
                                              nx.diameter(graph.subgraph(ordered)))))
    if not shapes:
        raise ValueError(f'No connected {width}-qubit template fits this device')
    ranked = sorted(shapes.values(), key=lambda item: (item[1], item[0]))
    result = []
    for ordered, _ in ranked:
        # Equivalent translated/reflected templates add no search freedom.
        signature = frozenset(tuple(m) for m in embeddings(ordered, graph, positions))
        if any(signature == old['signature'] for old in result):
            continue
        result.append(dict(qubits=ordered, signature=signature))
        if len(result) == limit:
            break
    return [row['qubits'] for row in result]
