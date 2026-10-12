'''Label text metrics, measured with cairo (the same engine phase 5 draws
with), so footprints match the drawn labels'''

import cairo


def set_font(cr, lab, size, italic, weight = cairo.FONT_WEIGHT_NORMAL):
    '''Selects the label font on cr. Italic is synthesized by slanting the
    upright face (see [labels] italic_shear): no italic face is installed'''
    cr.select_font_face(lab['font_family'], cairo.FONT_SLANT_NORMAL, weight)
    shear = lab['italic_shear'] if italic else 0.0
    # font matrix: x' = size*x - shear*size*y; glyph y is negative upwards,
    # so the top of each glyph leans right
    cr.set_font_matrix(cairo.Matrix(size, 0, -shear*size, size, 0, 0))


def end_radius(lab, thickness):
    '''Radius of the rounded ends of a label box of this thickness'''
    return thickness/2 if lab['shape'] == 'pill' else 0.0


class Metrics:
    def __init__(self, cfg):
        lab = cfg['labels']
        self.cfg     = lab
        self.pad     = cfg['draw']['text_pad_px']
        self.abbrevs = cfg['massifs'].get('abbrev', {})
        surface  = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
        self.cr  = cairo.Context(surface)

    def _width(self, text, size, italic):
        set_font(self.cr, self.cfg, size, italic)
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
        line, plus the padding and the rounded end at each end), thickness
        horizontal (the stacked lines, plus the margins on each side) -- its
        horizontal footprint'''
        lines  = self.lines(peak)
        thick  = sum(s * self.cfg['line_spacing'] for _, s, _ in lines) + 2*self.cfg['margin_px']
        length = (max(self._width(t, s, i) for t, s, i in lines) +
                  2*(self.pad + end_radius(self.cfg, thick)))
        return length, thick
