'''Phase 4: which peaks get a label, and in which row.

A placement is (peak, row). Its label is a box centered on the peak's
rendered azimuth, as wide as the label's stacked lines, standing on the row
(text rotated 90 deg, growing up); its leader line runs vertically from the
peak up to the row. Two placements conflict if their boxes overlap, or if
one's leader line runs through the other's box.

Solved as an integer linear program (PuLP + CBC), maximizing the sum of the
scores; greedy fallback in two passes if PuLP isn't available'''

import math


class Placement:
    def __init__(self, q, row, y_row, cfg):
        sel = cfg['selection']
        self.q    = q
        self.row  = row
        self.y    = y_row                       # bottom of the text
        half      = q['label_thickness'] / 2
        self.x0   = q['x_render'] - half
        self.x1   = q['x_render'] + half
        self.top  = y_row - q['label_length']
        self.xc   = q['x_render']
        self.peak_y = q['y_render']
        self.gap  = sel['box_gap_px']

    def boxes_overlap(self, o):
        return (self.x0 < o.x1 + self.gap and o.x0 < self.x1 + self.gap and
                self.top < o.y + self.gap and o.top < self.y + self.gap)

    def line_crosses(self, o):
        '''Whether this placement's leader line (x = xc, from the row down to
        the peak) runs through o's box'''
        return (o.x0 - self.gap <= self.xc <= o.x1 + self.gap and
                self.y < o.y and o.top < self.peak_y)

    def conflicts(self, o):
        return self.boxes_overlap(o) or self.line_crosses(o) or o.line_crosses(self)


def placements(scored, lay, cfg):
    '''Every allowed (peak, row): the rows of its plane's band that are high
    enough above the peak'''
    out = []
    for q in scored:
        if q['score'] <= 0:
            continue
        for r in lay['band_rows'][q['plan']]:
            y = lay['rows'][r]
            if y <= q['y_render'] - cfg['selection']['min_leader_px']:
                out.append(Placement(q, r, y, cfg))
    return out


def conflict_pairs(P):
    '''Index pairs (a, b), a < b, of conflicting placements of different
    peaks. Sorted sweep on x to avoid testing far-apart pairs'''
    order = sorted(range(len(P)), key = lambda i: P[i].x0)
    # A leader line can only cross boxes in its own column, and boxes only
    # overlap if their x ranges do: so x overlap (with the gap) is necessary
    pairs = []
    for ii, a in enumerate(order):
        pa = P[a]
        for b in order[ii+1:]:
            pb = P[b]
            if pb.x0 > pa.x1 + pa.gap:
                break
            if pa.q is not pb.q and pa.conflicts(pb):
                pairs.append((min(a, b), max(a, b)))
    return pairs


def _objective_weight(p, lay, cfg):
    # The main-row bonus is relative (a tie-breaker): as an absolute amount
    # it outweighed whole peaks once scores are raised to a power (2 x 0.05
    # of bonus kept two minor labels against the Meije)
    sel   = cfg['selection']
    bonus = sel['main_row_bonus'] if lay['main_row'].get(p.q['massif']) == p.row else 0.0
    return p.q['score'] ** sel['score_exponent'] * (1.0 + bonus)


def solve_pulp(P, pairs, lay, cfg):
    import pulp
    sel = cfg['selection']
    prob = pulp.LpProblem('labels', pulp.LpMaximize)
    x = [pulp.LpVariable(f'x{i}', cat = 'Binary') for i in range(len(P))]

    by_peak, by_massif = {}, {}
    for i, p in enumerate(P):
        by_peak.setdefault(id(p.q), []).append(i)
        by_massif.setdefault(p.q['massif'], []).append(i)

    slack = {m: pulp.LpVariable(f's{k}', lowBound = 0, upBound = 1)
             for k, m in enumerate(by_massif)}
    prob += (pulp.lpSum(_objective_weight(p, lay, cfg) * x[i] for i, p in enumerate(P)) -
             sel['massif_min_penalty'] * pulp.lpSum(slack.values()))

    for idx in by_peak.values():                       # at most one label per peak
        prob += pulp.lpSum(x[i] for i in idx) <= 1
    for a, b in pairs:                                 # no overlaps
        prob += x[a] + x[b] <= 1
    total = pulp.lpSum(x)
    for m, idx in by_massif.items():
        prob += pulp.lpSum(x[i] for i in idx) + slack[m] >= 1          # soft: >= 1 per massif
        prob += pulp.lpSum(x[i] for i in idx) <= sel['massif_cap_fraction'] * total

    status = prob.solve(pulp.PULP_CBC_CMD(msg = False, timeLimit = sel['time_limit_s']))
    chosen = [P[i] for i in range(len(P)) if (x[i].value() or 0) > 0.5]
    return chosen, pulp.LpStatus[status]


def solve_greedy(P, pairs, lay, cfg):
    '''Two passes: the best placement of each massif's best peak first, then
    everything else by decreasing score. Main row preferred'''
    conflict = {i: set() for i in range(len(P))}
    for a, b in pairs:
        conflict[a].add(b)
        conflict[b].add(a)
    taken, done = set(), set()

    def try_peak(idx):
        for i in sorted(idx, key = lambda i: -_objective_weight(P[i], lay, cfg)):
            if not (conflict[i] & taken):
                taken.add(i)
                return True
        return False

    by_peak = {}
    for i, p in enumerate(P):
        by_peak.setdefault(id(p.q), []).append(i)
    peaks = sorted(by_peak.values(), key = lambda idx: -P[idx[0]].q['score'])

    seen_massif = set()
    for idx in peaks:                                   # pass 1
        m = P[idx[0]].q['massif']
        if m not in seen_massif and try_peak(idx):
            seen_massif.add(m)
            done.add(id(P[idx[0]].q))
    for idx in peaks:                                   # pass 2
        if id(P[idx[0]].q) not in done:
            try_peak(idx)
    return [P[i] for i in sorted(taken)], 'greedy'


def select(scored, lay, cfg):
    P     = placements(scored, lay, cfg)
    pairs = conflict_pairs(P)
    if cfg['selection']['solver'] == 'pulp':
        try:
            import pulp  # noqa: F401
            chosen, status = solve_pulp(P, pairs, lay, cfg)
        except ImportError:
            chosen, status = solve_greedy(P, pairs, lay, cfg)
            status += ' (PuLP not installed)'
    else:
        chosen, status = solve_greedy(P, pairs, lay, cfg)
    return chosen, dict(placements = len(P), conflicts = len(pairs), status = status)
