'''Phase 5: drawing the labels.

The same cairo drawing goes to an SVG overlay (labels only, same size and
projection as the PNG) and to a PNG composite (render + labels), so the two
match exactly. Colors: DSatur graph coloring of the massifs'''

import math

import cairo
import numpy as np

from . import text


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def luminance(rgb):
    '''WCAG relative luminance'''
    def lin(c):
        return c/12.92 if c <= 0.03928 else ((c + 0.055)/1.055)**2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126*r + 0.7152*g + 0.0722*b


def text_color(bg):
    '''Black or white, whichever contrasts most with bg (WCAG ratio)'''
    L = luminance(bg)
    return (0.0, 0.0, 0.0) if (L + 0.05)/0.05 >= 1.05/(L + 0.05) else (1.0, 1.0, 1.0)


def massif_colors(chosen, pano, cfg):
    '''{massif: rgb}. DSatur: massifs whose label spans are within
    adjacency_gap_deg in azimuth are neighbors and get different colors'''
    d, outside = cfg['draw'], cfg['massifs']['outside_name']
    spans = {}
    for p in chosen:
        m = p.q['massif']
        if m == outside:
            continue
        lo, hi = spans.get(m, (math.inf, -math.inf))
        spans[m] = (min(lo, p.x0), max(hi, p.x1))
    gap = d['adjacency_gap_deg'] / pano.deg_per_px
    nb  = {m: {o for o in spans if o != m and
               spans[m][0] - gap <= spans[o][1] and spans[o][0] - gap <= spans[m][1]}
           for m in spans}

    color = {}
    while len(color) < len(spans):
        # most distinct neighbor colors first, then most neighbors
        m = max((m for m in spans if m not in color),
                key = lambda m: (len({color[o] for o in nb[m] if o in color}), len(nb[m]), m))
        used    = {color[o] for o in nb[m] if o in color}
        allowed = [i for i in range(len(d['palette'])) if i not in used] or list(range(len(d['palette'])))
        # among the allowed colors, the least used one so far: plain DSatur
        # takes the first one, and ends up with 3 colors for the whole view
        count   = {i: sum(1 for c in color.values() if c == i) for i in allowed}
        color[m] = min(allowed, key = lambda i: (count[i], i))
    out = {m: hex_rgb(d['palette'][i]) for m, i in color.items()}
    out[outside] = hex_rgb(d['outside_color'])
    return out, nb


def draw(cr, chosen, lay, planes, colors, metrics, cfg):
    '''Leader lines, massif bars and names, then the labels, in render
    pixel coordinates'''
    d, lab = cfg['draw'], cfg['labels']
    outside = cfg['massifs']['outside_name']

    cr.set_line_width(d['leader_width_px'])
    for p in chosen:
        cr.set_source_rgb(*colors[p.q['massif']])
        leader(cr, p)

    # Massif names: once each, on a bar spanning its labels, just below the
    # lowest row of its plane's band
    cr.select_font_face(lab['font_family'], cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(d['massif_name_size_px'])
    for plane in planes:
        y_band = max(lay['rows'][r] for r in lay['band_rows'][plane['index']])
        for m in plane['massifs']:
            ps = [p for p in chosen if p.q['massif'] == m]
            if not ps:
                continue
            x0, x1 = min(p.x0 for p in ps), max(p.x1 for p in ps)
            y = y_band + d['massif_bar_offset_px']
            c = colors[m]
            cr.set_source_rgb(*c)
            cr.set_line_width(d['massif_bar_width_px'])
            cr.move_to(x0, y)
            cr.line_to(x1, y)
            cr.stroke()
            ext = cr.text_extents(m)
            pad = d['massif_name_size_px'] * 0.3
            bx  = (x0 + x1)/2 - ext.x_advance/2
            cr.rectangle(bx - pad, y - d['massif_name_size_px']/2 - pad/2,
                         ext.x_advance + 2*pad, d['massif_name_size_px'] + pad)
            cr.fill()
            cr.set_source_rgb(*text_color(c))
            cr.move_to(bx, y + d['massif_name_size_px']*0.35)
            cr.show_text(m)

    for p in chosen:
        label_box(cr, p, colors[p.q['massif']], metrics, cfg)


def leader(cr, p):
    '''A placement's leader line: up from the peak, then (for a label
    shifted sideways) straight to the label's bottom center'''
    (x, y), _ = p.segments[0]
    cr.move_to(x, y)
    for _, (x, y) in p.segments:
        cr.line_to(x, y)
    cr.stroke()


def box_path(cr, x0, y0, x1, y1, r):
    '''A box path with rounded ends of radius r (r = half the width: an
    oblong pill, rounded at the top and bottom); r = 0: a plain rectangle'''
    if r <= 0:
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        return
    xm = (x0 + x1) / 2
    cr.new_sub_path()
    cr.arc(xm, y0 + r, r, math.pi, 2*math.pi)       # top end
    cr.arc(xm, y1 - r, r, 0, math.pi)               # bottom end
    cr.close_path()


def label_box(cr, p, c, metrics, cfg):
    '''One label: box in color c, text rotated 90 deg (bottom-up), name
    then altitude (italic, smaller)'''
    d, lab = cfg['draw'], cfg['labels']
    r = text.end_radius(lab, p.x1 - p.x0)
    cr.set_source_rgb(*c)
    box_path(cr, p.x0, p.top, p.x1, p.y, r)
    cr.fill()
    cr.set_source_rgb(*text_color(c))
    _, lines = metrics.layout(p.q)
    for t, size, italic, baseline in lines:
        text.set_font(cr, lab, size, italic)
        cr.save()
        # rotated -90 deg: the baselines are vertical, at their offsets
        # from the box's left edge (metrics.layout()); the text starts
        # above the bottom rounded end
        cr.translate(p.x0 + baseline, p.y - d['text_pad_px'] - r)
        cr.rotate(-math.pi/2)
        cr.move_to(0, 0)
        cr.show_text(t)
        cr.restore()


def frame(pano, chosen, cfg):
    '''The final image's window in render pixels: (x0, y0, width, height):
    the view window horizontally; from just above the highest label down
    to keep_below_horizon_deg below the horizon'''
    v, d = cfg['view'], cfg['draw']
    x0 = int(round(pano.x_from_az(v['az_min']) + 0.5))
    x1 = int(round(pano.x_from_az(v['az_max']) + 0.5))
    y0 = max(0, int(math.floor(min(p.top for p in chosen) - d['top_margin_px'])))
    y1 = int(math.ceil(pano.y_from_el(-d['keep_below_horizon_deg'])))
    return x0, y0, x1 - x0, min(y1, pano.height) - y0


def write(pano, chosen, lay, planes, metrics, cfg, svg_path, png_path):
    colors, nb = massif_colors(chosen, pano, cfg)
    fx, fy, W, H = frame(pano, chosen, cfg)

    svg = cairo.SVGSurface(svg_path, W, H)
    cr  = cairo.Context(svg)
    cr.translate(-fx, -fy)
    draw(cr, chosen, lay, planes, colors, metrics, cfg)
    svg.finish()

    bgra = np.zeros((H, W, 4), np.uint8)
    bgra[:, :, :3] = pano.image[fy:fy+H, fx:fx+W]        # BGR, as cairo wants
    bgra[:, :, 3]  = 255
    surf = cairo.ImageSurface.create_for_data(bgra, cairo.FORMAT_ARGB32, W, H)
    cr   = cairo.Context(surf)
    cr.translate(-fx, -fy)
    draw(cr, chosen, lay, planes, colors, metrics, cfg)
    surf.write_to_png(png_path)
    return dict(width = W, height = H, x0 = fx, y0 = fy, colors = colors, neighbors = nb)


def alignment_errors(chosen, pano, cfg):
    '''For each label, the vertical distance (px) from its leader line's
    foot (the rendered summit) to the nearest pixel of its column showing
    the peak's own terrain (distance within [d - front, d + behind]). 0 =
    the line starts exactly on the peak'''
    s = cfg['score']
    out = []
    for p in chosen:
        d   = p.q['distance_m']
        col = pano.ranges[:, p.xc]
        own = np.where((col >= d - s['delta_front_m']) & (col <= d + s['delta_behind_m']))[0]
        y   = int(round(p.peak_y))
        out.append((p.q['name'], float(np.min(np.abs(own - y))) if own.size else math.inf))
    return out
