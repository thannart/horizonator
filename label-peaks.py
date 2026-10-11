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

The peak list comes from query-peaks-from-osm.py --json, the massif outlines
from a GeoJSON file; all paths and parameters are in labeling/labeling.toml
(--config to use another one). Peaks with no OSM name are never labeled.
'''

import argparse
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from labeling import config, geometry, massifs as massifs_mod, peaks as peaks_mod
from labeling import render as render_mod, scoring, text, planes as planes_mod


def parse_args():
    parser = argparse.ArgumentParser(description = __doc__,
                                     formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default = None,
                        help = 'Configuration file (default: labeling/labeling.toml)')
    parser.add_argument('phase', choices = ('massifs', 'scores', 'plans'))
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


def main():
    args = parse_args()
    cfg  = config.load(args.config)
    {'massifs': phase_massifs, 'scores': phase_scores, 'plans': phase_plans}[args.phase](cfg)


if __name__ == '__main__':
    main()
