'''Loads labeling.toml'''

import os
import tomllib

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'labeling.toml')


def load(path = None):
    with open(path or DEFAULT_CONFIG, 'rb') as f:
        cfg = tomllib.load(f)
    for k, v in cfg['paths'].items():
        cfg['paths'][k] = os.path.expanduser(v)
    return cfg
