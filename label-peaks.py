#!/usr/bin/env python3

r'''Peak labeling for horizonator renders

SYNOPSIS

  $ ./label-peaks.py massifs
  12034 named peaks; ...
  Wrote ~/.horizonator/labeling/peaks_massifs.csv

DESCRIPTION

Selects which peaks to name on a render, and draws the labels. Works phase
by phase, each one a subcommand:

  massifs   attribute every peak to a massif (labeling/massifs.py)

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


def parse_args():
    parser = argparse.ArgumentParser(description = __doc__,
                                     formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default = None,
                        help = 'Configuration file (default: labeling/labeling.toml)')
    parser.add_argument('phase', choices = ('massifs',))
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
              'distance_m', 'massif', 'massif_candidates')
    with open(out, 'w', newline = '') as f:
        w = csv.DictWriter(f, fieldnames = fields, extrasaction = 'ignore')
        w.writeheader()
        for p in sorted(peaks, key = lambda p: (p['massif'], -p['ele'])):
            in_view(p, cfg)
            w.writerow(p)
    print(f'\nWrote {out}')


def main():
    args = parse_args()
    cfg  = config.load(args.config)
    {'massifs': phase_massifs}[args.phase](cfg)


if __name__ == '__main__':
    main()
