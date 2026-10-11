'''Loads the peak list written by query-peaks-from-osm.py --json'''

import json


def load(cfg):
    '''The peaks, as a list of dicts (osm_id, name, name_en, lat, lon, ele,
    wikidata). Peaks with no name are dropped if [peaks] require_name: a
    bare altitude is never worth a label'''
    with open(cfg['paths']['peaks_json']) as f:
        peaks = json.load(f)
    if cfg['peaks']['require_name']:
        peaks = [p for p in peaks if p['name']]
    return peaks
