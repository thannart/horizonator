'''Phase 3: depth planes, label bands and rows.

Massifs are grouped into depth planes by the median distance of their
labelable peaks, cutting at the largest gaps. Each plane gets a band of rows
above the skyline; the label text is vertical and grows UP from its row's
y. Within a band, each massif gets a main row (massifs whose labels overlap
in azimuth get different ones), so its labels form one visual group'''

import statistics

import numpy as np


def group(scored, cfg):
    '''Returns the list of planes, nearest first: dicts with 'index' (0 =
    nearest), 'massifs' (names), 'd_min', 'd_max' (range of the massif
    medians, m). Sets q['plan'] on every labelable peak'''
    pl, outside = cfg['plans'], cfg['massifs']['outside_name']
    labelable = [q for q in scored if q['score'] > 0]

    per = {}
    for q in labelable:
        if q['massif'] != outside:
            per.setdefault(q['massif'], []).append(q)
    medians = sorted((statistics.median(q['distance_m'] for q in qs), name)
                     for name, qs in per.items())

    n = min(pl['count'], len(medians))
    gaps = sorted(range(len(medians) - 1),
                  key = lambda i: medians[i+1][0] - medians[i][0], reverse = True)[:n-1]
    cuts = sorted(gaps)
    planes, start = [], 0
    for c in cuts + [len(medians) - 1]:
        members = medians[start:c+1]
        planes.append(dict(index   = len(planes),
                           massifs = [m for _, m in members],
                           medians = {m: d for d, m in members},
                           d_min   = members[0][0],
                           d_max   = members[-1][0]))
        start = c + 1

    plane_of = {m: p['index'] for p in planes for m in p['massifs']}
    for q in labelable:
        if q['massif'] in plane_of:
            q['plan'] = plane_of[q['massif']]
        else:
            # Outside every massif: the plane whose range of distances is
            # nearest to the peak's own distance
            d = q['distance_m']
            q['plan'] = min(planes, key = lambda p: 0 if p['d_min'] <= d <= p['d_max']
                            else min(abs(d - p['d_min']), abs(d - p['d_max'])))['index']
    return planes


def skyline_top_y(pano, cfg):
    '''Row of the highest rendered terrain inside the view window'''
    v  = cfg['view']
    x0 = max(0, int(pano.x_from_az(v['az_min'])))
    x1 = min(pano.width, int(pano.x_from_az(v['az_max'])) + 1)
    terrain = pano.ranges[:, x0:x1] > 0
    has = terrain.any(axis = 0)
    return int(np.argmax(terrain, axis = 0)[has].min())


def layout(planes, scored, pano, metrics, cfg):
    '''Assigns the rows: returns dict(rows = [y_bottom of each row, lowest
    first], band_rows = {plane index: [row indices]}, main_row = {massif:
    row index}, spacing, sky_needed_px). Also sets q['label_length'],
    q['label_thickness'] on the labelable peaks'''
    pl = cfg['plans']
    labelable = [q for q in scored if q['score'] > 0]
    for q in labelable:
        q['label_length'], q['label_thickness'] = metrics.size(q)

    spacing = pl['row_spacing_px'] or pl['row_spacing_factor'] * float(np.percentile(
        [q['label_length'] for q in labelable], pl['row_spacing_percentile']))

    order = sorted(planes, key = lambda p: p['index'],
                   reverse = pl['band_order'] == 'far_low')
    sky   = skyline_top_y(pano, cfg)
    rows, band_rows = [], {}
    for p in order:
        band_rows[p['index']] = []
        for _ in range(pl['rows_per_band']):
            band_rows[p['index']].append(len(rows))
            rows.append(sky - pl['skyline_gap_px'] - len(rows)*spacing)

    # Main row of each massif within its band: interval coloring of the
    # massifs' azimuth extents (plus half a label on each side), so that
    # massifs overlapping in azimuth start on different rows
    main_row = {}
    for p in planes:
        spans = []
        for m in p['massifs']:
            qs = [q for q in labelable if q['massif'] == m]
            half = max(q['label_thickness'] for q in qs) / 2
            spans.append((min(q['x_render'] for q in qs) - half,
                          max(q['x_render'] for q in qs) + half, m))
        spans.sort()
        row_end = {r: -np.inf for r in band_rows[p['index']]}
        for x0, x1, m in spans:
            free = [r for r, e in row_end.items() if e <= x0]
            r = free[0] if free else min(row_end, key = row_end.get)
            main_row[m] = r
            row_end[r] = max(row_end[r], x1)

    top_needed = rows[-1] - max(q['label_length'] for q in labelable)
    return dict(rows = rows, band_rows = band_rows, main_row = main_row,
                spacing = spacing, skyline_y = sky,
                sky_needed_px = max(0.0, -top_needed))
