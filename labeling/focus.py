'''One massif alone, with as many of its peak names as possible: every
named peak of the massif visible from the viewpoint, including those the
normal selection leaves out (low prominence, a point on a slope rather than
a summit), so the user can choose which ones to show. Box colors tell the
status of each peak'''

import math

import cairo
import numpy as np

from . import selection, draw as draw_mod


STATUS_LABELS = {'':               'retenu par le score',
                 'low_prominence': 'proéminence faible',
                 'not_summit':     'pas un sommet (point sur une pente)',
                 'too_close':      'trop proche'}


def _own_terrain_row(pano, x, d, y_hint, cfg):
    '''Row of column x showing the peak's own terrain (distance within
    [d - front, d + behind]) nearest to y_hint, or y_hint if none'''
    s   = cfg['score']
    col = pano.ranges[:, x]
    own = np.where((col >= d - s['delta_front_m']) & (col <= d + s['delta_behind_m']))[0]
    return float(own[np.argmin(np.abs(own - y_hint))]) if own.size else y_hint


def candidates(scored, massif, pano, cfg):
    '''The visible named peaks of the massif, each with an anchor point on
    its rendered terrain (x_render/y_render: the rendered summit for a real
    summit, its own position for a point on a slope). Several points on the
    same anchor are one: the most notable one is kept'''
    s = cfg['score']
    out = []
    for q in scored:
        if q['massif'] != massif or q['hidden']:
            continue
        q = dict(q)
        if not q['summit']:
            x = int(round(q['x_geom']))
            q['x_render'] = x
            q['y_render'] = _own_terrain_row(pano, x, q['distance_m'], q['y_geom'], cfg)
        q['status'] = '' if q['reason'] in ('', 'duplicate') else q['reason']
        out.append(q)

    out.sort(key = lambda q: (-q['sitelinks'], -q['ele']))
    kept, dpp = [], pano.deg_per_px
    for q in out:
        if not any(abs(k['x_render'] - q['x_render'])*dpp <= s['dedup_deg'] and
                   abs(k['y_render'] - q['y_render'])*dpp <= s['dedup_deg'] for k in kept):
            kept.append(q)
    return kept


def layout_rows(cands, pano, metrics, cfg):
    '''Rows (y of the label bottoms, lowest first) above the skyline of the
    massif's own azimuth range'''
    pl, fo = cfg['plans'], cfg['focus']
    for q in cands:
        q['label_length'], q['label_thickness'] = metrics.size(q)
    x0 = max(0, min(q['x_render'] for q in cands) - 1)
    x1 = min(pano.width, max(q['x_render'] for q in cands) + 2)
    terrain = pano.ranges[:, x0:x1] > 0
    sky = int(np.argmax(terrain, axis = 0)[terrain.any(axis = 0)].min())
    spacing = pl['row_spacing_px'] or pl['row_spacing_factor'] * float(np.percentile(
        [q['label_length'] for q in cands], pl['row_spacing_percentile']))
    return [sky - pl['skyline_gap_px'] - r*spacing for r in range(fo['rows'])], spacing


def select_max(cands, rows, cfg):
    '''As many labels as possible (each worth 1), the score breaking ties,
    lower rows preferred (shorter leader lines). Same conflict rules as the
    normal selection'''
    import pulp
    P = [p for q in cands for p in selection.placements_for(q, list(enumerate(rows)), cfg)]
    pairs = selection.conflict_pairs(P)
    prob = pulp.LpProblem('focus', pulp.LpMaximize)
    x = [pulp.LpVariable(f'x{i}', cat = 'Binary') for i in range(len(P))]
    n = len(rows)
    # the count first (each label worth ~1), then the score, then a lower
    # row (shorter leader), then a straight leader
    prob += pulp.lpSum((1.0 + 0.5*p.q['score'] + 0.01*(n - p.row)/n) *
                       selection.shift_factor(p, cfg) * x[i]
                       for i, p in enumerate(P))
    by_peak = {}
    for i, p in enumerate(P):
        by_peak.setdefault(id(p.q), []).append(i)
    for idx in by_peak.values():
        prob += pulp.lpSum(x[i] for i in idx) <= 1
    for a, b in pairs:
        prob += x[a] + x[b] <= 1
    status = prob.solve(pulp.PULP_CBC_CMD(msg = False, timeLimit = cfg['selection']['time_limit_s']))
    return [P[i] for i in range(len(P)) if (x[i].value() or 0) > 0.5], pulp.LpSolution[prob.sol_status]


def write_png(pano, massif, chosen, cands, metrics, cfg, path):
    '''The massif's azimuth range only, labels colored by status, with a
    legend'''
    fo, d = cfg['focus'], cfg['draw']
    colors = {k: draw_mod.hex_rgb(fo[f'color_{k or "scored"}']) for k in STATUS_LABELS}
    margin = fo['crop_margin_deg'] / pano.deg_per_px
    fx0 = int(max(0, min(p.x0 for p in chosen) - margin))
    fx1 = int(min(pano.width, max(p.x1 for p in chosen) + margin))
    fy0 = int(max(0, min(p.top for p in chosen) - d['top_margin_px'] - 3*d['massif_name_size_px']))
    fy1 = int(min(pano.height, math.ceil(pano.y_from_el(-d['keep_below_horizon_deg']))))
    W, H = fx1 - fx0, fy1 - fy0

    bgra = np.zeros((H, W, 4), np.uint8)
    bgra[:, :, :3] = pano.image[fy0:fy1, fx0:fx1]
    bgra[:, :, 3]  = 255
    surf = cairo.ImageSurface.create_for_data(bgra, cairo.FORMAT_ARGB32, W, H)
    cr   = cairo.Context(surf)

    # Legend: title, then one swatch per status present
    size = d['massif_name_size_px']
    cr.select_font_face(cfg['labels']['font_family'], cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(size * 1.3)
    cr.set_source_rgb(0, 0, 0)
    cr.move_to(size, size * 1.6)
    cr.show_text(f'{massif} : {len(chosen)} noms affichés sur {len(cands)} sommets nommés visibles')
    cr.set_font_size(size)
    x = size
    for k, text in STATUS_LABELS.items():
        if not any(q['status'] == k for q in cands):
            continue
        cr.set_source_rgb(*colors[k])
        cr.rectangle(x, size*2.4, size, size)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        cr.move_to(x + size*1.4, size*3.25)
        cr.show_text(text)
        x += size*2 + cr.text_extents(text).x_advance + size

    cr.translate(-fx0, -fy0)
    cr.set_line_width(d['leader_width_px'])
    for p in chosen:
        cr.set_source_rgb(*colors[p.q['status']])
        draw_mod.leader(cr, p)
    for p in chosen:
        draw_mod.label_box(cr, p, colors[p.q['status']], metrics, cfg)
    surf.write_to_png(path)
    return W, H
