'''Notoriety of a peak: the number of Wikipedia (and sister project)
sitelinks of its Wikidata item. Fetched once, cached in a JSON file'''

import json
import os

import requests


def sitelinks(qids, cfg):
    '''{qid: number of sitelinks} for the given Wikidata ids. Only the ids
    missing from the cache are fetched'''
    w     = cfg['wikidata']
    cache = os.path.join(cfg['paths']['output_dir'], w['cache_json'])
    known = {}
    if os.path.exists(cache):
        with open(cache) as f:
            known = json.load(f)

    missing = sorted(set(q for q in qids if q and q not in known))
    for i in range(0, len(missing), w['batch_size']):
        batch = missing[i:i + w['batch_size']]
        r = requests.get(w['api'],
                         params  = dict(action = 'wbgetentities', ids = '|'.join(batch),
                                        props = 'sitelinks', format = 'json'),
                         headers = {'User-Agent': w['user_agent']},
                         timeout = w['timeout_s'])
        r.raise_for_status()
        entities = r.json().get('entities', {})
        for q in batch:
            e = entities.get(q, {})
            # a missing/redirected item counts as no notoriety
            known[q] = len(e.get('sitelinks', {})) if 'missing' not in e else 0

    if missing:
        os.makedirs(cfg['paths']['output_dir'], exist_ok = True)
        with open(cache, 'w') as f:
            json.dump(known, f, indent = 0, sort_keys = True)
    return {q: known[q] for q in qids if q}
