'''Why a peak didn't get a label: its candidate placements, and the chosen
labels each of them conflicts with'''


def why_not(name, scored, chosen, P, cfg):
    q = next((q for q in scored if q['name'] == name), None)
    if q is None:
        return [f'{name}: not in the view']
    if q['score'] <= 0:
        return [f'{name}: no score ({q["reason"]})']
    mine = [p for p in P if p.q is q]
    if not mine:
        return [f'{name}: no allowed row (every row of its band is lower than '
                f'{cfg["selection"]["min_leader_px"]} px above the peak, y={q["y_render"]:.0f})']
    out = [f'{name} (score {q["score"]:.3f}, plane {q["plan"]}, x {q["x_render"]}, '
           f'label {q["label_length"]:.0f}x{q["label_thickness"]:.0f} px):']
    for p in mine:
        blockers = [c for c in chosen if c.q is not q and p.conflicts(c)]
        out.append(f'  row {p.row} (y {p.y:.0f}): blocked by ' +
                   (', '.join(f'{c.q["name"]} [row {c.row}, score {c.q["score"]:.2f}, '
                              f'{"box" if p.boxes_overlap(c) else "its line" if c.line_crosses(p) else "my line"}]'
                              for c in blockers) or 'nothing'))
    return out
