#!/usr/bin/python3

r'''Query OSM data for peak annotation

SYNOPSIS

  $ ./query-peaks-from-osm.py 34. -118 100000 > socal-peaks.h
  # generates peak data from lat,lon 34,-118 in a radius of 100000m

  $ ./query-peaks-from-osm.py --json 45.77294 4.82993 200000 > lyon-peaks.json
  # same peaks, as a JSON list, with more fields (see --json)
'''

import sys
import argparse
import re
import os

def parse_args():

    parser = \
        argparse.ArgumentParser(description = __doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--json',
                        action='store_true',
                        help='''Write a JSON list instead of the C poi_t[]
                        initializer: one object per peak with osm_id, name,
                        name_en, lat, lon, ele and wikidata (the Wikidata item
                        id, or null). For this output, name is the LOCAL name
                        (OSM "name"), falling back to "name:en"; null if the
                        peak has neither. Used by the peak labeling tools
                        (labeling/)''')
    parser.add_argument('lat',
                        type=float,
                        help='''Latitude''')
    parser.add_argument('lon',
                        type=float,
                        help='''Longitude''')
    parser.add_argument('radius',
                        type=float,
                        help='''Radius, in m''')

    args = parser.parse_args()

    return args

args = parse_args()





import requests
import json

api = 'https://overpass-api.de/api/interpreter'

query = f'''
[out:json][timeout:60];

node
 ["natural" = "peak" ]
 (around: {args.radius},{args.lat},{args.lon});

(._;>;);
out;
'''

# The Overpass API rejects requests with no (or a generic) User-Agent, and
# plain http:// tends to time out; https:// with an identifying UA is
# reliable
r = requests.post(api,
                  data    = query,
                  headers = {'User-Agent': 'horizonator query-peaks-from-osm.py'},
                  timeout = 90)
if r.status_code != 200:
    print(f"Overpass api error: {r.status_code} {r.reason=}",
          file = sys.stderr)
    sys.exit(1)

l = json.loads(r.text)


# with open("peaks.json") as f:
#     l = json.load(f)



def name_from_element(t,
                      *,
                      ele):
    keys = ('name:en', 'name', 'name:th')
    for k in keys:
        if k in t:
            return t[k]

    # No name available. Use the elevation
    return f"{ele}m"


try:
    E = l['elements']
except:
    print("Expected 'elements' in the json output", sys.stderr)
    sys.exit(1);

peaks_json = []

for e in E:
    try:
        t = e['tags']
    except:
        print("Expected 'tags' for each element", sys.stderr)
        sys.exit(1);

    try:             ele = float(t['ele'])
    except:          continue

    if args.json:
        peaks_json.append(dict(osm_id   = e['id'],
                               name     = t.get('name', t.get('name:en')),
                               name_en  = t.get('name:en'),
                               lat      = e['lat'],
                               lon      = e['lon'],
                               ele      = ele,
                               wikidata = t.get('wikidata')))
        continue

    name = name_from_element(t, ele = ele)
    if name is None: continue

    print(f'{{ "{name}", {e["lat"]}, {e["lon"]}, {ele} }},')

if args.json:
    json.dump(peaks_json, sys.stdout, ensure_ascii = False, indent = 0)
    print()

