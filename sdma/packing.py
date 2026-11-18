"""Four-pass packing with bounded page repair and sparse-page consolidation."""
import copy
from fractions import Fraction
import itertools
import random

import numpy as np


class Planner:
    def __init__(self, candidates, policy, threshold, seed, capacity, nodes=1500):
        self.candidates, self.policy = candidates, policy
        self.threshold, self.seed, self.capacity = Fraction(str(threshold)), seed, capacity
        self.nodes = nodes
        self.cache, self.fit_cache, self.possible_cache = {}, {}, {}
        self.arrays = {}
        max_qubit = max(q for rows in candidates.values() for row in rows for q in row['qubits'])
        self.words = range(0, max_qubit + 1, 64)
        for name, rows in candidates.items():
            self.arrays[name] = dict(
                bounds=np.asarray([r['bounds'] for r in rows]),
                depth=np.asarray([r['depth'] for r in rows]),
                cost=np.asarray([r['hardware_cost'] for r in rows]),
                occupied=np.asarray([[sum(1 << (q - lo) for q in r['qubits'] if lo <= q < lo + 64)
                                      for lo in self.words] for r in rows], dtype=np.uint64),
            )

    def compat(self, a, b):
        if (a, b) not in self.cache:
            aa, bb = self.arrays[a], self.arrays[b]
            x, y = aa['bounds'], bb['bounds']
            dh = np.maximum(0, np.maximum(x[:, 0, None] - y[None, :, 1], y[None, :, 0] - x[:, 1, None]))
            dv = np.maximum(0, np.maximum(x[:, 2, None] - y[None, :, 3], y[None, :, 2] - x[:, 3, None]))
            matrix = np.zeros(dh.shape, dtype=bool)
            for da in np.unique(aa['depth']):
                for db in np.unique(bb['depth']):
                    k = int(Fraction(int(max(da, db)), int(min(da, db))) + 1 - self.threshold)
                    if k in self.policy:
                        h, v = self.policy[k]
                        matrix |= ((aa['depth'][:, None] == da) & (bb['depth'][None, :] == db)
                                   & ((dh >= h) | (dv >= v)))
            for i in range(len(self.words)):
                matrix &= (aa['occupied'][:, i, None] & bb['occupied'][None, :, i]) == 0
            self.cache[a, b], self.cache[b, a] = matrix, matrix.T
        return self.cache[a, b]

    def placed(self, request, option):
        return dict(copy.deepcopy(self.candidates[request['algorithm']][option]),
                    **request, candidate_index=int(option))

    def score(self, pages):
        distance = sum((a['bounds'][0]+a['bounds'][1]-b['bounds'][0]-b['bounds'][1])**2 +
                       (a['bounds'][2]+a['bounds'][3]-b['bounds'][2]-b['bounds'][3])**2
                       for page in pages for a, b in itertools.combinations(page, 2))
        return (len(pages), sum(w['hardware_cost'] for p in pages for w in p), -distance)

    def _search_page(self, requests):
        """Deterministic node budget, independent of machine wall-clock speed."""
        visited = 0
        def dfs(domains, selected):
            nonlocal visited
            if not domains:
                return selected
            if visited >= self.nodes:
                return None
            i = min(domains, key=lambda j: (len(domains[j]), -requests[j]['width'], j))
            a = requests[i]['algorithm']
            for choice in domains[i]:
                visited += 1
                rest = {}
                for j, ids in domains.items():
                    if i == j:
                        continue
                    rest[j] = ids[self.compat(a, requests[j]['algorithm'])[choice, ids]]
                    if not len(rest[j]):
                        break
                else:
                    found = dfs(rest, {**selected, i: int(choice)})
                    if found is not None:
                        return found
                if visited >= self.nodes:
                    break
            return None
        found = dfs({i: np.arange(len(self.candidates[w['algorithm']])) for i, w in enumerate(requests)}, {})
        return None if found is None else [self.placed(w, found[i]) for i, w in enumerate(requests)]

    def direct(self, request, page):
        name = request['algorithm']
        choices = np.arange(len(self.candidates[name]))
        for w in page:
            choices = choices[self.compat(name, w['algorithm'])[choices, w['candidate_index']]]
            if not len(choices):
                return None
        costs = self.arrays[name]['cost'][choices]
        choices = choices[costs == costs.min()]
        if page and len(choices) > 1:
            coords = self.arrays[name]['bounds'][choices]
            separation = np.zeros(len(choices))
            for w in page:
                b = w['bounds']
                separation += ((coords[:, 0] + coords[:, 1] - b[0] - b[1]) ** 2
                               + (coords[:, 2] + coords[:, 3] - b[2] - b[3]) ** 2)
            choice = choices[int(np.argmax(separation))]
        else:
            choice = choices[0]
        return self.placed(request, choice)

    def fit(self, requests):
        if sum(r['width'] for r in requests) > self.capacity:
            return None
        key = tuple(r['algorithm'] for r in requests)
        if key not in self.fit_cache:
            for a, b in itertools.combinations(key, 2):
                if (a, b) not in self.possible_cache:
                    self.possible_cache[a, b] = self.possible_cache[b, a] = bool(self.compat(a, b).any())
                if not self.possible_cache[a, b]:
                    self.fit_cache[key] = None
                    break
            else:
                result = self._search_page(requests)
                self.fit_cache[key] = None if result is None else [w['candidate_index'] for w in result]
        choices = self.fit_cache[key]
        return None if choices is None else [self.placed(r, c) for r, c in zip(requests, choices)]

    def pack(self, requests, restarts=4):
        rng = random.Random(self.seed)
        solutions = []
        for trial in range(restarts):
            order = list(requests)
            if trial == 0:
                order.sort(key=lambda w: (-min(c['depth'] for c in self.candidates[w['algorithm']]), -w['width']))
            elif trial == 1:
                order.sort(key=lambda w: (-w['width'], w['name']))
            else:
                rng.shuffle(order)
            pages = []
            for request in order:
                choices = []
                for p, page in enumerate(pages):
                    added = self.direct(request, page)
                    if added is not None:
                        choices.append((-len(page), added['hardware_cost'], p, added))
                if choices:
                    _, _, p, added = min(choices, key=lambda row: row[:3])
                    pages[p].append(added)
                    continue
                for p in sorted(range(len(pages)), key=lambda i: -len(pages[i])):
                    result = self.fit([dict(name=w['name'], algorithm=w['algorithm'], width=w['width'])
                                       for w in pages[p]] + [request])
                    if result is not None:
                        pages[p] = result
                        break
                else:
                    pages.append([self.direct(request, [])])
            # Try removing sparsely populated pages while preserving every instance.
            for p in sorted(range(len(pages)), key=lambda i: len(pages[i])):
                if not pages[p]:
                    continue
                attempt = copy.deepcopy(pages)
                pending, attempt[p] = attempt[p], []
                for item in pending:
                    request = {key: item[key] for key in ('name', 'algorithm', 'width')}
                    for j in sorted((i for i in range(len(attempt)) if i != p and attempt[i]), key=lambda i: -len(attempt[i])):
                        result = self.direct(request, attempt[j])
                        if result is not None:
                            attempt[j].append(result)
                            break
                        result = self.fit([{key: w[key] for key in ('name', 'algorithm', 'width')}
                                           for w in attempt[j]]+[request])
                        if result is not None:
                            attempt[j] = result
                            break
                    else:
                        break
                else:
                    pages = attempt
            pages = [p for p in pages if p]
            solutions.append(pages)
        return min(solutions, key=self.score)
