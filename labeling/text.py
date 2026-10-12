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

    def _ink(self, text, size, italic):
        '''(above, below): how far the text's ink reaches above and below
        its baseline'''
        set_font(self.cr, self.cfg, size, italic)
        e = self.cr.text_extents(text)
        return -e.y_bearing, e.y_bearing + e.height

    def layout(self, peak):
        '''The label's lines across its thickness: returns (thickness,
        [(text, size, italic, baseline)]), baseline being the offset of
        each line's baseline from the box's left edge (the text is rotated
        90 deg, read bottom-up: "above the baseline" is to the left).

        Laid out from the ink: the margin, then the first line's ink above
        its baseline, its ink below, the gap, the next line... and the
        margin again: the same visible space on both sides. A name line
        uses the extents of [labels] name_top_chars/name_bottom_chars, so
        all names get the same thickness; the other lines (altitude digits,
        abbreviation) their own text's'''
        lab, out = self.cfg, []
        x = lab['margin_px']
        for i, (t, size, italic) in enumerate(self.lines(peak)):
            if i == 0:
                above = self._ink(lab['name_top_chars'], size, italic)[0]
                below = max(0.0, self._ink(lab['name_bottom_chars'], size, italic)[1])
            else:
                above, below = self._ink(t, size, italic)
                below = max(0.0, below)
            if i > 0:
                x += lab['line_gap_px']
            out.append((t, size, italic, x + above))
            x += above + below
        return x + lab['margin_px'], out

    def size(self, peak):
        '''(length, thickness) of the label box in pixels. The text is
        rotated 90 deg (read bottom-up): length is vertical (the longest
        line, plus the padding and the rounded end at each end), thickness
        horizontal (see layout()) -- its horizontal footprint'''
        thick, lines = self.layout(peak)
        length = (max(self._width(t, s, i) for t, s, i, _ in lines) +
                  2*(self.pad + end_radius(self.cfg, thick)))
        return length, thick
