'''Label text metrics, measured with cairo (the same engine phase 5 draws
with), so footprints match the drawn labels'''

import cairo


class Metrics:
    def __init__(self, cfg):
        lab = cfg['labels']
        self.cfg     = lab
        self.pad     = cfg['draw']['text_pad_px']
        self.abbrevs = cfg['massifs'].get('abbrev', {})
        surface  = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
        self.cr  = cairo.Context(surface)

    def _width(self, text, size, italic):
        self.cr.select_font_face(self.cfg['font_family'],
                                 cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_NORMAL)
        self.cr.set_font_size(size)
        return self.cr.text_extents(text).x_advance

    def lines(self, peak):
        '''The (text, size_px, italic) lines of a peak's label: name, then
        altitude, then (optionally) the massif abbreviation'''
        lab = self.cfg
        out = [(peak['name'], lab['name_size_px'], False),
               (f'{peak["ele"]:.0f} m', lab['alt_size_px'], True)]
        abbrev = self.abbrevs.get(peak.get('massif'))
        if lab['show_massif_abbrev'] and abbrev:
            out.append((abbrev, lab['alt_size_px'], False))
        return out

    def size(self, peak):
        '''(length, thickness) of the label box in pixels. The text is
        rotated 90 deg (read bottom-up): length is vertical (the longest
        line, plus the padding at each end), thickness horizontal (the
        stacked lines, plus the margins on each side) -- its horizontal
        footprint'''
        lines  = self.lines(peak)
        length = max(self._width(t, s, i) for t, s, i in lines) + 2*self.pad
        thick  = sum(s * self.cfg['line_spacing'] for _, s, _ in lines) + 2*self.cfg['margin_px']
        return length, thick
