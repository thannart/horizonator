'''The render the labels are computed on: image + per-pixel distance, for
the view window plus a margin on each side, rendered in azimuth tiles
through the Python bindings (one GL context, rebuild_mesh() between tiles),
and cached on disk'''

import hashlib
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Panorama:
    '''image (H,W,3 uint8 BGR), ranges (H,W float32, meters; <= 0: sky),
    and the geometry needed to map pixels <-> (azimuth, elevation)'''

    def __init__(self, image, ranges, meta):
        self.image  = image
        self.ranges = ranges
        self.meta   = meta
        self.az_lo      = meta['az_lo']        # left edge of pixel 0
        self.deg_per_px = meta['deg_per_px']
        self.height     = ranges.shape[0]
        self.width      = ranges.shape[1]
        self.viewer_z   = meta['viewer_z']

    # Same conventions as horizonator_x_from_az()/horizonator_project():
    # pixel centers are at integer coordinates, the horizon is the middle row
    def x_from_az(self, az_deg):
        return (az_deg - self.az_lo) / self.deg_per_px - 0.5

    def az_from_x(self, x):
        return self.az_lo + (x + 0.5) * self.deg_per_px

    def el_from_y(self, y):
        return (self.height/2.0 - 0.5 - y) * self.deg_per_px

    def y_from_el(self, el_deg):
        return self.height/2.0 - 0.5 - el_deg / self.deg_per_px


def _layout(cfg):
    '''Pixel-exact tiling of [az_min - margin, az_max + margin]'''
    v, r, s = cfg['view'], cfg['render'], cfg['score']
    deg_per_px = 1.0 / r['px_per_deg']
    span   = (v['az_max'] - v['az_min']) + 2*s['margin_deg']
    width  = int(math.ceil(span / deg_per_px))
    ntiles = int(math.ceil(width / r['max_tile_px']))
    tile_w = int(math.ceil(width / ntiles))
    width  = ntiles * tile_w
    az_lo  = v['az_min'] - s['margin_deg']
    return dict(az_lo = az_lo, deg_per_px = deg_per_px, width = width,
                height = r['height_px'], ntiles = ntiles, tile_w = tile_w)


def _renderer_fingerprint():
    '''Hash of the compiled renderer library the bindings load (shaders
    included: they're compiled in), so that any change to the renderer
    invalidates the cached renders, not only a change of configuration'''
    import horizonator
    lib = os.path.realpath(horizonator.__file__)
    h = hashlib.sha1()
    for path in (lib, os.path.join(os.path.dirname(lib), 'libhorizonator.so')):
        if os.path.exists(path):
            with open(os.path.realpath(path), 'rb') as f:
                h.update(f.read())
    return h.hexdigest()


def _family_key(cfg):
    '''Cache key of everything but the height: renders of one family differ
    only by how much is above/below the horizon (the middle row), so a
    taller one contains any shorter one exactly, cropped about its middle'''
    render = {k: v for k, v in cfg['render'].items() if k != 'height_px'}
    keyed = dict(view = cfg['view'], render = render,
                 margin = cfg['score']['margin_deg'],
                 renderer = _renderer_fingerprint())
    return hashlib.sha1(json.dumps(keyed, sort_keys = True).encode()).hexdigest()[:12]


def _cached(out, family):
    '''[(height, base path)] of the cached renders of this family'''
    found = []
    for name in os.listdir(out) if os.path.isdir(out) else ():
        if name.startswith(f'render_{family}_') and name.endswith('.json'):
            base = os.path.join(out, name[:-5])
            if all(os.path.exists(base + ext) for ext in ('_image.npy', '_ranges.npy')):
                with open(base + '.json') as f:
                    found.append((json.load(f)['height'], base))
    return sorted(found)


def get(cfg):
    '''The Panorama for this configuration: cropped from the cached render
    of the same family if one is at least as tall (with the same parity, so
    the horizon stays the exact middle row), rendered (and cached, replacing
    the shorter ones of the family) otherwise'''
    out    = cfg['paths']['output_dir']
    family = _family_key(cfg)
    H      = cfg['render']['height_px']
    for h, base in _cached(out, family):
        if h >= H and (h - H) % 2 == 0:
            with open(base + '.json') as f:
                meta = json.load(f)
            off = (h - H) // 2
            meta['height'] = H
            return Panorama(np.array(np.load(base + '_image.npy',  mmap_mode = 'r')[off:off+H]),
                            np.array(np.load(base + '_ranges.npy', mmap_mode = 'r')[off:off+H]),
                            meta)

    import horizonator

    v, r = cfg['view'], cfg['render']
    lay  = _layout(cfg)
    tile_deg = lay['tile_w'] * lay['deg_per_px']
    edges = [lay['az_lo'] + i*tile_deg for i in range(lay['ntiles'] + 1)]

    h = horizonator.horizonator(v['lat'], v['lon'], lay['tile_w'], lay['height'],
                                SRTM1                 = r['SRTM1'],
                                dir_landcover         = os.path.expanduser(r['dir_landcover']),
                                render_radius_m       = v['zfar_m'],
                                restrict_mesh_azimuth = True,
                                mesh_az_deg0          = edges[0],
                                mesh_az_deg1          = edges[1],
                                viewer_height_m       = r['viewer_height_m'])
    h.set_curvature(r['curvature'], r['refraction_k'])
    h.set_sun(r['shading'], r['sun_azimuth'], r['sun_elevation'])
    h.set_materials(r['materials'])

    images, ranges = [], []
    for i in range(lay['ntiles']):
        print(f'  render tile {i+1}/{lay["ntiles"]}: az [{edges[i]:.3f}, {edges[i+1]:.3f}]')
        h.rebuild_mesh(edges[i], edges[i+1])
        img, rng = h.render(edges[i], edges[i+1],
                            znear = r['znear_m'], zfar = v['zfar_m'])
        images.append(img)
        ranges.append(rng)

    meta = dict(lay, viewer_z = h.viewer_z, lat = v['lat'], lon = v['lon'],
                zfar_m = v['zfar_m'], curvature = r['curvature'],
                refraction_k = r['refraction_k'])
    pano = Panorama(np.concatenate(images, axis = 1),
                    np.concatenate(ranges, axis = 1).astype(np.float32), meta)
    # The shorter renders of the family are now redundant: drop them (each
    # one is hundreds of MB)
    for h, old in _cached(out, family):
        if h < lay['height']:
            for ext in ('.json', '_image.npy', '_ranges.npy'):
                os.remove(old + ext)
    os.makedirs(out, exist_ok = True)
    base = os.path.join(out, f'render_{family}_{lay["height"]}')
    np.save(base + '_image.npy',  pano.image)
    np.save(base + '_ranges.npy', pano.ranges)
    with open(base + '.json', 'w') as f:
        json.dump(meta, f, indent = 1)
    return pano
