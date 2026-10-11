'''Phase 2: peak scores, from the render's own distance map ("voie A").

For a distance limit D and a column x, the topmost pixel whose distance is
<= D is exactly the horizon of the terrain closer than D: nearer terrain is
never masked by farther terrain. So the profiles below are read straight off
the rendered pixels, with the render's own viewpoint, curvature and
refraction: they line up with the rendered peaks by construction'''

import math

import numpy as np

from . import geometry, wikidata


def elevation_deg(d, ele, viewer_z, curvature, k):
    '''Apparent elevation angle of a point d meters away (horizontal), ele m
    high: the renderer's formula, i.e. eps = atan((h - h_obs)/d - d/(2 R_eff))
    with R_eff = R/(1-k)'''
    drop = (1.0 - k) * d*d / (2.0*geometry.R_EARTH_M) if curvature else 0.0
    return math.degrees(math.atan2(ele - viewer_z - drop, d))


def profile(pano, x0, x1, dmax):
    '''Elevation (deg) of the horizon of the terrain at most dmax away, for
    columns [x0, x1): the topmost pixel with 0 < distance <= dmax. Columns
    with no such terrain get the elevation of the bottom row (the lowest
    the image can show)'''
    sub  = pano.ranges[:, x0:x1]
    mask = (sub > 0) & (sub <= dmax)
    has  = mask.any(axis = 0)
    top  = np.argmax(mask, axis = 0)
    return np.where(has, pano.el_from_y(top), pano.el_from_y(pano.height - 1))


def col_search(S, i0, eps, direction):
    '''From index i0 of profile S, walk in direction (-1/+1) until a point
    strictly higher than eps, or the end of the window; returns the lowest
    elevation met on the way (the "col" on that side)'''
    lowest = math.inf
    i = i0 + direction
    while 0 <= i < len(S):
        if S[i] > eps:
            break
        lowest = min(lowest, S[i])
        i += direction
    return lowest if lowest != math.inf else S[i0]


def score_peaks(peaks, pano, cfg):
    '''Computes, for every peak in the view window, the columns of
    peaks_scored.csv (see the code for the list), and its score'''
    v, s = cfg['view'], cfg['score']
    dpp  = pano.deg_per_px
    k    = pano.meta['refraction_k']
    curv = pano.meta['curvature']
    recal_px = int(math.ceil(s['recal_deg'] / dpp))
    win_px   = int(math.ceil(s['prom_window_deg'] / dpp))

    scored = []
    for p in peaks:
        az, d = geometry.azimuth_distance(p['lat'], p['lon'], v['lat'], v['lon'])
        if not (v['az_min'] <= az <= v['az_max']) or not (s['min_distance_m'] <= d <= v['zfar_m']):
            continue
        q = dict(p)
        q['azimuth_deg'] = az
        q['distance_m']  = d
        q['elev_deg']    = elevation_deg(d, p['ele'], pano.viewer_z, curv, k)
        q['x_geom']      = pano.x_from_az(az)
        q['y_geom']      = pano.y_from_el(q['elev_deg'])

        xc  = int(round(q['x_geom']))
        lo, hi = max(0, xc - recal_px), min(pano.width, xc + recal_px + 1)

        # Re-centering: the rendered summit is the max of S nearby. It must
        # be a true local maximum: a max on the edge of the window means
        # the profile keeps rising beyond it, i.e. this point is on the
        # slope of something higher, not a summit of its own
        far = profile(pano, lo, hi, d + s['delta_behind_m'])
        i_r = int(np.argmax(far))
        q['x_render']   = lo + i_r
        q['elev_render_deg'] = far[i_r]
        q['y_render']   = pano.y_from_el(far[i_r])
        q['dx_px']      = q['x_render'] - q['x_geom']
        q['dy_px']      = q['y_render'] - q['y_geom']
        q['summit']     = 0 < i_r < len(far) - 1

        # Clearance: the peak against the horizon of the terrain in front of
        # it, at the column of its rendered summit (not the best column of
        # the window: that let a peak masked at its own position through a
        # notch a few pixels away)
        x_r  = q['x_render']
        near = profile(pano, x_r, x_r + 1, d - s['delta_front_m'])[0]
        q['horizon_front_deg'] = near
        q['clearance_deg'] = q['elev_deg'] - near
        q['clearance_px']  = q['clearance_deg'] / dpp
        q['hidden'] = q['clearance_deg'] < -s['hidden_tol_deg']

        q['col_left_deg'] = q['col_right_deg'] = math.nan
        q['prom_deg'] = q['prom_px'] = 0.0
        if not q['hidden'] and q['summit']:
            x_r = q['x_render']
            x0  = max(0, x_r - win_px)
            x1  = min(pano.width, x_r + win_px + 1)
            S   = profile(pano, x0, x1, d + s['delta_behind_m'])
            i0  = x_r - x0
            eps = S[i0]
            q['col_left_deg']  = col_search(S, i0, eps, -1)
            q['col_right_deg'] = col_search(S, i0, eps, +1)
            q['prom_deg'] = eps - max(q['col_left_deg'], q['col_right_deg'])
            q['prom_px']  = q['prom_deg'] / dpp
        scored.append(q)

    # Why a peak gets no score (empty: it does get one). In this order of
    # precedence
    for q in scored:
        q['reason'] = ('hidden'         if q['hidden'] else
                       'not_summit'     if not q['summit'] else
                       'too_close'      if q['distance_m'] < s['min_label_distance_m'] else
                       'low_prominence' if q['prom_deg'] < s['prom_min_deg'] else
                       '')

    # Notoriety, for the peaks that can get a nonzero score only
    candidates = [q for q in scored if not q['reason']]
    links = wikidata.sitelinks([q['wikidata'] for q in candidates], cfg)
    for q in scored:
        q['sitelinks'] = links.get(q['wikidata'], 0) if q['wikidata'] else 0

    # Several OSM points (e.g. named points of the Mont Blanc dome) can be
    # re-centered onto the same rendered summit: they are one peak. Keep the
    # most notable one, then the highest
    candidates.sort(key = lambda q: (-q['sitelinks'], -q['ele']))
    kept = []
    for q in candidates:
        dup = next((k for k in kept
                    if abs(k['x_render'] - q['x_render'])*dpp <= s['dedup_deg'] and
                       abs(k['elev_render_deg'] - q['elev_render_deg']) <= s['dedup_deg']), None)
        if dup is None:
            kept.append(q)
            q['duplicate_of'] = ''
        else:
            q['reason'] = 'duplicate'
            q['duplicate_of'] = dup['name']
    max_links = max((q['sitelinks'] for q in kept), default = 0)

    for q in scored:
        q.setdefault('duplicate_of', '')
        q['p'] = min(q['prom_deg'] / s['prom_full_deg'], 1.0)
        q['n'] = (math.log1p(q['sitelinks']) / math.log1p(max_links)) if max_links > 0 else 0.0
        q['g'] = min(max(q['clearance_deg'], 0.0) / s['clear_full_deg'], 1.0)
        if q['reason']:
            q['score'] = 0.0
        else:
            q['score'] = s['w_prominence']*q['p'] + s['w_notoriety']*q['n'] + s['w_clearance']*q['g']
            if s['attenuation']:
                q['score'] *= math.exp(-q['distance_m'] / s['attenuation_L_m'])
        q['plan'] = ''   # phase 3
    return scored


CSV_FIELDS = ('name', 'osm_id', 'massif', 'lat', 'lon', 'ele', 'wikidata', 'sitelinks',
              'azimuth_deg', 'distance_m', 'elev_deg', 'x_geom', 'y_geom',
              'x_render', 'y_render', 'dx_px', 'dy_px', 'elev_render_deg',
              'summit', 'horizon_front_deg', 'clearance_deg', 'clearance_px', 'hidden',
              'col_left_deg', 'col_right_deg', 'prom_deg', 'prom_px',
              'p', 'n', 'g', 'score', 'reason', 'duplicate_of', 'plan')
