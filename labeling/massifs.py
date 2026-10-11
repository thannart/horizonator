'''Massif attribution: which massif polygon each peak falls in'''

import json

import shapely
from shapely.geometry import Point, shape
from shapely.ops import transform

from . import geometry


class Massif:
    def __init__(self, name, polygon, properties, lat0):
        self.name       = name
        self.polygon    = polygon          # WGS84 lon/lat
        self.properties = properties
        # Areas and distances are compared between nearby polygons only, so
        # a local planar approximation (km) around the data is enough
        self.polygon_km = transform(lambda x, y: geometry.local_km(x, y, lat0), polygon)
        self.area_km2   = self.polygon_km.area


def load(cfg):
    '''The massifs of the GeoJSON file. Handles Polygon and MultiPolygon,
    with holes (shapely does)'''
    with open(cfg['paths']['massifs_geojson']) as f:
        features = json.load(f)['features']

    polygons = [shape(f['geometry']) for f in features]
    lat0 = shapely.union_all(polygons).centroid.y

    massifs = []
    for feature, polygon in zip(features, polygons):
        props = feature['properties'] or {}
        name  = next((props[k] for k in cfg['massifs']['name_fields'] if props.get(k)), None)
        if name is None:
            raise ValueError(f'massif polygon with no name in any of {cfg["massifs"]["name_fields"]}: {props}')
        massifs.append(Massif(name, polygon, props, lat0))
    return massifs


def assign(peaks, massifs, cfg):
    '''Sets peak['massif'] for every peak: the polygon containing it (its
    boundary included); if several do, the smallest one (the most
    specific); if none, the nearest polygon within [massifs]
    snap_tolerance_km; else [massifs] outside_name. Also sets
    peak['massif_candidates'] (number of polygons containing it) and
    peak['massif_snap_km'] (distance to the polygon it was snapped to, or
    empty if it wasn't)'''
    tree = shapely.STRtree([m.polygon for m in massifs])
    lat0 = shapely.union_all([m.polygon for m in massifs]).centroid.y
    tol  = cfg['massifs']['snap_tolerance_km']
    for p in peaks:
        pt  = Point(p['lon'], p['lat'])
        hit = [massifs[i] for i in tree.query(pt, predicate = 'covered_by')]
        p['massif_candidates'] = len(hit)
        p['massif_snap_km']    = ''
        if hit:
            p['massif'] = min(hit, key = lambda m: m.area_km2).name
            continue
        pt_km = Point(geometry.local_km(p['lon'], p['lat'], lat0))
        d, m  = min(((m.polygon_km.distance(pt_km), m) for m in massifs),
                    key = lambda t: t[0])
        if d <= tol:
            p['massif']         = m.name
            p['massif_snap_km'] = round(d, 3)
        else:
            p['massif'] = cfg['massifs']['outside_name']


def narrow_perimeter_suspects(peaks, massifs, cfg):
    '''Peaks outside every polygon, but high and close to a perimeter of the
    configured type (national parks): probably part of that massif in common
    usage, missed only because the park is narrower than the massif. Listed
    for review, never reassigned automatically. Returns (peak, massif,
    distance_km) tuples'''
    rep    = cfg['massifs']['narrow_perimeter_report']
    parks  = [m for m in massifs if m.properties.get(rep['type_field']) in rep['type_values']]
    lat0   = shapely.union_all([m.polygon for m in massifs]).centroid.y
    out    = []
    for p in peaks:
        if p['massif'] != cfg['massifs']['outside_name'] or p['ele'] < rep['min_ele_m']:
            continue
        pt_km = Point(geometry.local_km(p['lon'], p['lat'], lat0))
        dists = [(m.polygon_km.distance(pt_km), m) for m in parks]
        if not dists:
            continue
        d, m = min(dists, key = lambda t: t[0])
        if d <= rep['max_dist_km']:
            out.append((p, m, d))
    return out
