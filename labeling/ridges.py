'''Crest line of each massif on the render: which massif each rendered
pixel shows, then the upper edge of each massif's visible terrain where
sky or a farther massif is above it'''

import math

import numpy as np
import rasterio.features
import rasterio.transform

from . import geometry


def massif_raster(massifs, names, cfg):
    '''Lon/lat raster of the massif polygons: (grid uint8, transform), the
    value being the 1-based index into names (0: no massif). Smaller
    polygons are burnt last, so they win where polygons overlap (same rule
    as the peak attribution)'''
    res = cfg['draw']['massif_raster_deg']
    polys = [m for m in massifs if m.name in names]
    x0 = min(m.polygon.bounds[0] for m in polys)
    y0 = min(m.polygon.bounds[1] for m in polys)
    x1 = max(m.polygon.bounds[2] for m in polys)
    y1 = max(m.polygon.bounds[3] for m in polys)
    W, H = int(math.ceil((x1 - x0)/res)), int(math.ceil((y1 - y0)/res))
    transform = rasterio.transform.from_origin(x0, y1, res, res)
    shapes = [(m.polygon, names.index(m.name) + 1)
              for m in sorted(polys, key = lambda m: -m.area_km2)]
    grid = rasterio.features.rasterize(shapes, out_shape = (H, W), transform = transform,
                                       fill = 0, dtype = 'uint8')
    return grid, transform


def pixel_massifs(pano, x0, y0, W, H, grid, transform, cfg):
    '''Massif index (1-based, 0 = none or sky) of every pixel of the window
    of the render, from its rendered distance and direction, mapped back to
    the ground with the renderer's own tangent-plane geometry'''
    v = cfg['view']
    rng = pano.ranges[y0:y0+H, x0:x0+W]
    terrain = rng > 0
    ys, xs = np.nonzero(terrain)
    az = np.radians(pano.az_from_x(xs + x0))
    el = np.radians(pano.el_from_y(ys + y0))
    d  = rng[ys, xs] * np.cos(el)
    east, north = d*np.sin(az), d*np.cos(az)
    lat = v['lat'] + np.degrees(north / geometry.R_EARTH_M)
    lon = v['lon'] + np.degrees(east / (geometry.R_EARTH_M * math.cos(math.radians(v['lat']))))
    rows, cols = rasterio.transform.rowcol(transform, lon, lat)
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < grid.shape[0]) & (cols >= 0) & (cols < grid.shape[1])
    out = np.zeros((H, W), np.uint8)
    out[ys[ok], xs[ok]] = grid[rows[ok], cols[ok]]
    return out, rng


def crest_masks(ids, rng, n, cfg):
    '''{index: bool mask} of the crest pixels of each massif: a pixel of
    the massif with, right above it, sky or another massif's terrain at
    least ridge_depth_jump_m farther. Thickened to ridge_width_px'''
    jump = cfg['draw']['ridge_depth_jump_m']
    above_id  = np.vstack([np.zeros((1, ids.shape[1]), ids.dtype), ids[:-1]])
    above_rng = np.vstack([np.full((1, rng.shape[1]), -1.0, rng.dtype), rng[:-1]])
    sky_above = above_rng <= 0
    edge = (ids > 0) & (above_id != ids) & (sky_above | (above_rng - rng >= jump))
    w = cfg['draw']['ridge_width_px']
    out = {}
    for i in range(1, n + 1):
        m = edge & (ids == i)
        if not m.any():
            continue
        # thicken downwards (into the massif) and sideways
        t = m.copy()
        for k in range(1, w):
            t[k:] |= m[:-k]
        side = t.copy()
        side[:, 1:] |= t[:, :-1]
        side[:, :-1] |= t[:, 1:]
        out[i] = side if w > 1 else t
    return out
