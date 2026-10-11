#!/usr/bin/env python3

r'''Peak labeling for horizonator renders

SYNOPSIS

  $ ./label-peaks.py massifs
  6765 named peaks, 26 massif polygons; ...
  Wrote ~/.horizonator/labeling/peaks_massifs.csv

  $ ./label-peaks.py scores
  ...
  Wrote ~/.horizonator/labeling/peaks_scored.csv

DESCRIPTION

Selects which peaks to name on a render, and draws the labels. Works phase
by phase, each one a subcommand:

  massifs   attribute every peak to a massif (labeling/massifs.py)
  scores    score every peak of the view (labeling/scoring.py) from the
            render's own distance map (rendered in tiles, then cached);
            fetches Wikidata sitelinks once (cached). Writes
            peaks_scored.csv
  plans     group the massifs into depth planes, and lay out the bands of
            label rows above the skyline (labeling/planes.py); fills the
            plan column of peaks_scored.csv
  select    choose the labels and their rows (labeling/selection.py:
            integer program with PuLP/CBC, greedy fallback); writes
            labels_selected.csv and a debug preview labels_preview.png
  draw      draw the labels (labeling/draw.py): an SVG overlay with the
            same size and projection as the PNG, and the PNG composite
            (render + labels). Re-renders taller if the labels need more
            sky

The peak list comes from query-peaks-from-osm.py --json, the massif outlines
from a GeoJSON file; all paths and parameters are in labeling/labeling.toml
(--config to use another one). Peaks with no OSM name are never labeled.
'''

import argparse
import collections
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from labeling import config, geometry, massifs as massifs_mod, peaks as peaks_mod
from labeling import render as render_mod, scoring, text, planes as planes_mod, selection
from labeling import draw as draw_mod


def parse_args():
    parser = argparse.ArgumentParser(description = __doc__,
                                     formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default = None,
                        help = 'Configuration file (default: labeling/labeling.toml)')
    parser.add_argument('phase', choices = ('massifs', 'scores', 'plans', 'select', 'draw'))
    return parser.parse_args()


def in_view(p, cfg):
    '''Whether peak p lies inside the configured azimuth window and range'''
    v = cfg['view']
    az, d = geometry.azimuth_distance(p['lat'], p['lon'], v['lat'], v['lon'])
    p['azimuth_deg'], p['distance_m'] = az, d
    return v['az_min'] <= az <= v['az_max'] and d <= v['zfar_m']


def phase_massifs(cfg):
    peaks   = peaks_mod.load(cfg)
    massifs = massifs_mod.load(cfg)
    massifs_mod.assign(peaks, massifs, cfg)
    view = [p for p in peaks if in_view(p, cfg)]

    print(f'{len(peaks)} named peaks, {len(massifs)} massif polygons; '
          f'{len(view)} peaks in the view window '
          f'(az {cfg["view"]["az_min"]:g}-{cfg["view"]["az_max"]:g} deg, '
          f'<= {cfg["view"]["zfar_m"]/1000:g} km)')
    overlaps = [p for p in peaks if p['massif_candidates'] > 1]
    print(f'{len(overlaps)} peaks in several polygons (smallest one kept): ' +
          ', '.join(f'{p["name"]} -> {p["massif"]}' for p in overlaps))

    print('\nPeaks in the view, per massif (highest first):')
    per = collections.defaultdict(list)
    for p in view:
        per[p['massif']].append(p)
    for name, ps in sorted(per.items(), key = lambda t: -len(t[1])):
        ps.sort(key = lambda p: -p['ele'])
        top = ', '.join(f'{p["name"]} {p["ele"]:.0f}' for p in ps[:3])
        print(f'  {name:32s} {len(ps):4d}   {top}')

    suspects = massifs_mod.narrow_perimeter_suspects(view, massifs, cfg)
    rep = cfg['massifs']['narrow_perimeter_report']
    print(f'\n"{cfg["massifs"]["outside_name"]}" peaks in the view >= {rep["min_ele_m"]:g} m '
          f'and <= {rep["max_dist_km"]:g} km from a {"/".join(rep["type_values"])} perimeter '
          f'(probably that massif; NOT reassigned): {len(suspects)}')
    suspects.sort(key = lambda t: -t[0]['ele'])
    for p, m, d in suspects[:rep['max_lines']]:
        print(f'  {p["name"]:36s} {p["ele"]:5.0f} m  {d:5.1f} km from {m.name}')
    if len(suspects) > rep['max_lines']:
        print(f'  ... ({len(suspects) - rep["max_lines"]} more in massif_suspects.csv)')

    os.makedirs(cfg['paths']['output_dir'], exist_ok = True)
    with open(os.path.join(cfg['paths']['output_dir'], 'massif_suspects.csv'), 'w', newline = '') as f:
        w = csv.writer(f)
        w.writerow(('name', 'lat', 'lon', 'ele', 'azimuth_deg', 'distance_m', 'nearest_perimeter', 'dist_km'))
        for p, m, d in suspects:
            w.writerow((p['name'], p['lat'], p['lon'], p['ele'],
                        f'{p["azimuth_deg"]:.3f}', f'{p["distance_m"]:.0f}', m.name, f'{d:.2f}'))
    out = os.path.join(cfg['paths']['output_dir'], 'peaks_massifs.csv')
    fields = ('osm_id', 'name', 'lat', 'lon', 'ele', 'wikidata', 'azimuth_deg',
              'distance_m', 'massif', 'massif_candidates', 'massif_snap_km')
    with open(out, 'w', newline = '') as f:
        w = csv.DictWriter(f, fieldnames = fields, extrasaction = 'ignore')
        w.writeheader()
        for p in sorted(peaks, key = lambda p: (p['massif'], -p['ele'])):
            in_view(p, cfg)
            w.writerow(p)
    print(f'\nWrote {out}')


def fmt(v):
    if isinstance(v, float):
        return '' if v != v else f'{v:.4f}'
    return v


def compute_scores(cfg):
    '''Phases 1+2: the render and the scored peaks of the view'''
    peaks   = peaks_mod.load(cfg)
    massifs = massifs_mod.load(cfg)
    massifs_mod.assign(peaks, massifs, cfg)

    print('Render (image + distance map), or the cached one:')
    pano = render_mod.get(cfg)
    print(f'  {pano.width}x{pano.height} px, {1/pano.deg_per_px:g} px/deg, '
          f'az {pano.az_lo:.2f}-{pano.az_from_x(pano.width-0.5):.2f}, '
          f'viewer_z {pano.viewer_z:.1f} m')
    return pano, scoring.score_peaks(peaks, pano, cfg)


def write_scored(scored, cfg):
    out = os.path.join(cfg['paths']['output_dir'], 'peaks_scored.csv')
    with open(out, 'w', newline = '') as f:
        w = csv.writer(f)
        w.writerow(scoring.CSV_FIELDS)
        for q in sorted(scored, key = lambda q: -q['score']):
            w.writerow([fmt(q.get(k, '')) for k in scoring.CSV_FIELDS])
    print(f'\nWrote {out}')


def phase_scores(cfg):
    pano, scored = compute_scores(cfg)
    s       = cfg['score']
    visible = [q for q in scored if not q['hidden']]
    kept    = [q for q in scored if q['score'] > 0]
    print(f'{len(scored)} named peaks in the view: {len(visible)} visible, '
          f'{len(scored) - len(visible)} hidden; {len(kept)} with a nonzero score')
    reasons = collections.Counter(q['reason'] for q in scored if q['reason'])
    print('  no score because: ' + ', '.join(f'{r} {n}' for r, n in reasons.most_common()) +
          f'  (too_close: < {s["min_label_distance_m"]/1000:g} km; '
          f'low_prominence: < {s["prom_min_deg"]:g} deg)')
    print(f'Wikidata: {sum(1 for q in kept if q["wikidata"])} of them have an item, '
          f'max sitelinks {max((q["sitelinks"] for q in kept), default = 0)}')

    # Alignment between the OSM peak, projected with the renderer's
    # geometry, and the rendered summit found nearby
    import statistics
    dx = [abs(q['dx_px']) for q in kept]
    dy = [abs(q['dy_px']) for q in kept]
    if kept:
        print(f'Alignment OSM -> rendered summit, scored peaks: |dx| median {statistics.median(dx):.1f} px, '
              f'p90 {sorted(dx)[int(0.9*len(dx))]:.1f}; |dy| median {statistics.median(dy):.1f} px, '
              f'p90 {sorted(dy)[int(0.9*len(dy))]:.1f}')

    kept.sort(key = lambda q: -q['score'])
    print(f'\nTop {cfg["validation"]["top_n"]} scores:')
    print(f'  {"":3s} {"name":34s} {"massif":24s} {"ele":>5s} {"km":>4s} '
          f'{"prom°":>6s} {"clear°":>6s} {"links":>5s} {"score":>5s}')
    for i, q in enumerate(kept[:cfg['validation']['top_n']]):
        print(f'  {i+1:3d} {q["name"][:34]:34s} {q["massif"][:24]:24s} {q["ele"]:5.0f} '
              f'{q["distance_m"]/1000:4.0f} {q["prom_deg"]:6.3f} {q["clearance_deg"]:6.3f} '
              f'{q["sitelinks"]:5d} {q["score"]:5.3f}')

    print('\nValidation peaks:')
    rank = {id(q): i+1 for i, q in enumerate(kept)}
    for name in cfg['validation']['peaks']:
        for q in (q for q in scored if q['name'] == name):
            print(f'  {name:28s} {q["massif"][:22]:22s} rank {rank.get(id(q), "-"):>4} '
                  f'score {q["score"]:.3f}  prom {q["prom_deg"]:.3f} deg  clear {q["clearance_deg"]:+.3f} deg  '
                  f'{q["reason"] or "labeled"}{" (" + q["duplicate_of"] + ")" if q["duplicate_of"] else ""}  '
                  f'dx {q["dx_px"]:+.1f} dy {q["dy_px"]:+.1f} px')
        if not any(q['name'] == name for q in scored):
            print(f'  {name:28s} (not in the view window)')

    write_scored(scored, cfg)


def phase_plans(cfg):
    pano, scored = compute_scores(cfg)
    planes = planes_mod.group(scored, cfg)
    lay    = planes_mod.layout(planes, scored, pano, text.Metrics(cfg), cfg)
    labelable = [q for q in scored if q['score'] > 0]
    outside   = cfg['massifs']['outside_name']

    print(f'\n{len(labelable)} labelable peaks, {len(planes)} depth planes '
          f'(cut at the {len(planes)-1} largest gaps between massif median distances):')
    for p in planes:
        qs = [q for q in labelable if q['plan'] == p['index']]
        print(f'\n  Plane {p["index"]+1}: massif medians {p["d_min"]/1000:.0f}-{p["d_max"]/1000:.0f} km, '
              f'{len(qs)} labelable peaks, rows {lay["band_rows"][p["index"]]}')
        for m in p['massifs']:
            mq = sorted((q for q in qs if q['massif'] == m), key = lambda q: -q['score'])
            print(f'    {m:30s} median {p["medians"][m]/1000:5.1f} km  {len(mq):3d} peaks  '
                  f'main row {lay["main_row"][m]}  e.g. ' +
                  ', '.join(q['name'] for q in mq[:3]))
        hl = sorted((q for q in qs if q['massif'] == outside), key = lambda q: -q['score'])
        if hl:
            print(f'    {outside:30s} {len(hl):3d} peaks placed here by distance, e.g. ' +
                  ', '.join(f'{q["name"]} ({q["distance_m"]/1000:.0f} km)' for q in hl[:4]))

    print(f'\nRows (y of the label bottoms, lowest first): ' +
          ', '.join(f'{y:.0f}' for y in lay['rows']) +
          f'; spacing {lay["spacing"]:.0f} px; highest terrain of the view at y={lay["skyline_y"]}')
    lengths = sorted(q['label_length'] for q in labelable)
    print(f'Label lengths: median {lengths[len(lengths)//2]:.0f} px, max {lengths[-1]:.0f} px '
          f'({cfg["labels"]["name_size_px"]} px names); thickness ~{labelable[0]["label_thickness"]:.0f} px')
    if lay['sky_needed_px'] > 0:
        print(f'The current render has {lay["sky_needed_px"]:.0f} px too little sky above the rows: '
              f'[render] height_px should be >= {cfg["render"]["height_px"] + 2*int(lay["sky_needed_px"]+0.5)} '
              f'(the horizon is the middle row; the extra bottom is cut off in phase 5)')

    write_scored(scored, cfg)


def preview(pano, chosen, lay, cfg, path):
    '''Debug picture of the selection: the render, padded with sky on top,
    label boxes (one color per plane), leader lines and names. Not the
    final look (that's phase 5)'''
    import cairo
    import numpy as np
    pad = int(math.ceil(lay['sky_needed_px']))
    W, H = pano.width, pano.height + pad
    argb = np.zeros((H, W, 4), np.uint8)
    argb[:pad] = (235, 225, 210, 255)                     # pale sky, BGRA
    argb[pad:, :, :3] = pano.image                        # BGR, as cairo wants
    argb[pad:, :, 3] = 255
    surf = cairo.ImageSurface.create_for_data(argb, cairo.FORMAT_ARGB32, W, H)
    cr   = cairo.Context(surf)
    cr.translate(0, pad)
    colors = [(0.85, 0.37, 0.0), (0.0, 0.45, 0.70), (0.0, 0.62, 0.45), (0.80, 0.47, 0.65)]
    cr.select_font_face(cfg['labels']['font_family'])
    cr.set_font_size(cfg['labels']['name_size_px'])
    for p in chosen:
        c = colors[p.q['plan'] % len(colors)]
        cr.set_source_rgb(*c)
        cr.set_line_width(1.5)
        cr.move_to(p.xc, p.peak_y)
        cr.line_to(p.xc, p.y)
        cr.stroke()
        cr.rectangle(p.x0, p.top, p.x1 - p.x0, p.y - p.top)
        cr.stroke()
        cr.save()
        cr.translate(p.xc + cfg['labels']['name_size_px']/3, p.y - 4)
        cr.rotate(-math.pi/2)
        cr.set_source_rgb(0, 0, 0)
        cr.move_to(0, 0)
        cr.show_text(p.q['name'])
        cr.restore()
    surf.write_to_png(path)


def phase_select(cfg):
    pano, scored = compute_scores(cfg)
    planes = planes_mod.group(scored, cfg)
    lay    = planes_mod.layout(planes, scored, pano, text.Metrics(cfg), cfg)
    chosen, info = selection.select(scored, lay, cfg)
    labelable = [q for q in scored if q['score'] > 0]
    sel = cfg['selection']

    print(f'\n{info["placements"]} candidate placements for {len(labelable)} labelable peaks, '
          f'{info["conflicts"]} conflicting pairs; solver: {info["status"]}')
    print(f'{len(chosen)} labels selected (row spacing {lay["spacing"]:.0f} px, '
          f'{len(lay["rows"])} rows)')
    chosen_q = {id(p.q): p for p in chosen}
    for p in planes:
        n = sum(1 for c in chosen if c.q['plan'] == p['index'])
        tot = sum(1 for q in labelable if q['plan'] == p['index'])
        print(f'\n  Plane {p["index"]+1} ({p["d_min"]/1000:.0f}-{p["d_max"]/1000:.0f} km): {n}/{tot} labeled')
        for m in p['massifs'] + [cfg['massifs']['outside_name']]:
            mq = [q for q in labelable if q['massif'] == m and q['plan'] == p['index']]
            if not mq:
                continue
            got = sorted((q for q in mq if id(q) in chosen_q), key = lambda q: -q['score'])
            main = sum(1 for q in got if chosen_q[id(q)].row == lay['main_row'].get(m))
            print(f'    {m:30s} {len(got):3d}/{len(mq):<3d} (main row: {main})  ' +
                  ', '.join(q['name'] for q in got[:6]) + (' ...' if len(got) > 6 else ''))
    empty = [m for m in {q['massif'] for q in labelable} if not any(c.q['massif'] == m for c in chosen)]
    if empty:
        print(f'\nMassifs left without a label: {", ".join(empty)}')
    cap = sel['massif_cap_fraction'] * len(chosen)
    print(f'Largest massif share: {max(collections.Counter(c.q["massif"] for c in chosen).values())} '
          f'labels (cap {cap:.1f})')

    best_dropped = sorted((q for q in labelable if id(q) not in chosen_q), key = lambda q: -q['score'])
    print('\nBest-scored peaks NOT labeled (no room): ' +
          ', '.join(f'{q["name"]} ({q["score"]:.2f})' for q in best_dropped[:10]))
    print('\nValidation peaks:')
    for name in cfg['validation']['peaks']:
        q = next((q for q in scored if q['name'] == name), None)
        if q is None:
            continue
        state = (f'LABELED, row {chosen_q[id(q)].row}' if id(q) in chosen_q else
                 'not labeled: ' + (q['reason'] or 'no room'))
        print(f'  {name:28s} {state}')

    out = os.path.join(cfg['paths']['output_dir'], 'labels_selected.csv')
    with open(out, 'w', newline = '') as f:
        w = csv.writer(f)
        w.writerow(('name', 'massif', 'plan', 'row', 'main_row', 'x', 'y_row', 'y_peak',
                    'label_length', 'label_thickness', 'score', 'ele', 'distance_m'))
        for p in sorted(chosen, key = lambda p: p.xc):
            w.writerow((p.q['name'], p.q['massif'], p.q['plan'], p.row, lay['main_row'].get(p.q['massif'], ''),
                        p.xc, f'{p.y:.1f}', f'{p.peak_y:.1f}', f'{p.q["label_length"]:.1f}',
                        f'{p.q["label_thickness"]:.1f}', f'{p.q["score"]:.4f}', p.q['ele'],
                        f'{p.q["distance_m"]:.0f}'))
    png = os.path.join(cfg['paths']['output_dir'], 'labels_preview.png')
    preview(pano, chosen, lay, cfg, png)
    print(f'\nWrote {out}\nWrote {png} (debug preview)')
    write_scored(scored, cfg)


def layout_and_select(cfg):
    pano, scored = compute_scores(cfg)
    metrics = text.Metrics(cfg)
    planes  = planes_mod.group(scored, cfg)
    lay     = planes_mod.layout(planes, scored, pano, metrics, cfg)
    chosen, info = selection.select(scored, lay, cfg)
    return pano, scored, metrics, planes, lay, chosen, info


def phase_draw(cfg):
    pano, scored, metrics, planes, lay, chosen, info = layout_and_select(cfg)

    # Not enough sky above the skyline for the label rows: render taller.
    # The horizon is the middle row, so the height grows by twice the
    # missing sky; the scores don't change (same angular resolution)
    missing = cfg['draw']['top_margin_px'] - min(p.top for p in chosen)
    if missing > 0 and cfg['draw']['auto_sky']:
        cfg['render']['height_px'] += 2 * int(math.ceil(missing))
        print(f'\nThe labels need {missing:.0f} more px of sky: re-rendering '
              f'{cfg["render"]["height_px"]} px high')
        pano, scored, metrics, planes, lay, chosen, info = layout_and_select(cfg)

    out = cfg['paths']['output_dir']
    svg = os.path.join(out, cfg['draw']['svg_name'])
    png = os.path.join(out, cfg['draw']['png_name'])
    res = draw_mod.write(pano, chosen, lay, planes, metrics, cfg, svg, png)

    print(f'\n{len(chosen)} labels drawn; {info["status"]}')
    print(f'Image {res["width"]}x{res["height"]} px (render window x {res["x0"]}, y {res["y0"]})')
    print('Massif colors (DSatur, neighbors in azimuth must differ):')
    for m, c in sorted(res['colors'].items(), key = lambda t: t[0]):
        n = sum(1 for p in chosen if p.q['massif'] == m)
        if n:
            print(f'  {m:30s} #{"".join(f"{int(round(v*255)):02X}" for v in c)}  {n:3d} labels'
                  f'  neighbors: {", ".join(sorted(res["neighbors"].get(m, ()))) or "-"}')
    err = draw_mod.alignment_errors(chosen, pano, cfg)
    worst = sorted(err, key = lambda t: -t[1])
    tol = cfg['validation']['alignment_tol_px']
    bad = [(n, e) for n, e in worst if e > tol]
    print(f'Alignment (leader line foot -> the peak\'s own rendered terrain): '
          f'{len(err) - len(bad)}/{len(err)} labels within {tol:g} px' +
          ('; above: ' + ', '.join(f'{n} ({"masked at its column" if e == math.inf else f"{e:.0f} px"})'
                                   for n, e in bad) if bad else ''))
    print('\nValidation peaks:')
    on = {p.q['name'] for p in chosen}
    for name in cfg['validation']['peaks']:
        q = next((q for q in scored if q['name'] == name), None)
        if q is not None:
            print(f'  {name:28s} {"labeled" if name in on else "not labeled: " + (q["reason"] or "no room")}')
    print(f'\nWrote {svg}\nWrote {png}')


def main():
    args = parse_args()
    cfg  = config.load(args.config)
    {'massifs': phase_massifs, 'scores': phase_scores, 'plans': phase_plans,
     'select': phase_select, 'draw': phase_draw}[args.phase](cfg)


if __name__ == '__main__':
    main()
