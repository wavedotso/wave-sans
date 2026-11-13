"""Add the grade axis (GRAD) to the variable designspace.

    .venv/bin/python tools/grade.py build/ufo/WaveSans-Roman.var.designspace \
        build/ufo/WaveSans-Roman.grade.designspace

Grade changes stroke weight without changing any width, so text never
reflows: lighter for light text on dark backgrounds, heavier for hover and
selected states. Its unit is the weight unit: grade +100 gives the strokes of
weight +100.

No new drawing: each grade master is made from Inter's own drawings. For a
Regular master (one per optical size), it takes the outlines of a heavier or
lighter weight and scales each glyph horizontally back to the Regular width,
so side bearings keep their proportion and letters keep Inter's spacing.
Kerning stays the Regular's. The weight is chosen so the stem of n matches
the stem of weight 400 + grade. A variable font applies these grades at every
weight, so the masters at Regular are enough.
"""

from __future__ import annotations

import argparse
import copy
import sys
from typing import Dict, List

import ufoLib2
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, InstanceDescriptor, SourceDescriptor
from fontmake.instantiator import Instantiator

GRADES = (-50, 100)
REGULAR = 400  # user weight of the masters the grades are made for


def to_design(axis: AxisDescriptor, user: float) -> float:
    points = sorted(axis.map) or [(axis.minimum, axis.minimum), (axis.maximum, axis.maximum)]
    for (u0, d0), (u1, d1) in zip(points, points[1:]):
        if u0 <= user <= u1:
            return d0 + (d1 - d0) * (user - u0) / (u1 - u0)
    raise ValueError(f"weight {user} is outside the axis")


def stem(glyph, y: float) -> float:
    """Width of the first ink run a horizontal line at y crosses (the left
    stem of n). The stem edges are straight, so on-curve points suffice."""
    xs: List[float] = []
    for contour in glyph.contours:
        on = [(p.x, p.y) for p in contour.points if p.type is not None]
        for (x0, y0), (x1, y1) in zip(on, on[1:] + on[:1]):
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    return xs[1] - xs[0]


class GradeMaker:
    def __init__(self, designspace: DesignSpaceDocument):
        self.designspace = designspace
        self.weight = next(a for a in designspace.axes if a.tag == "wght")
        self.instantiator = Instantiator.from_designspace(designspace, round_geometry=False)

    def glyph_at(self, name: str, design_weight: float, location: Dict[str, float]):
        full = {**location, self.weight.name: design_weight}
        return self.instantiator.generate_glyph_instance(name, self.instantiator.normalize(full))

    def weight_for(self, base: ufoLib2.Font, grade: int, location: Dict[str, float]) -> float:
        """Design weight whose n, fitted to the Regular width, has the stem
        of weight REGULAR + grade."""
        y = base.info.xHeight / 2
        target = stem(self.glyph_at("n", to_design(self.weight, REGULAR + grade), location), y)

        def fitted_stem(design_weight: float) -> float:
            g = self.glyph_at("n", design_weight, location)
            return stem(g, y) * base["n"].width / g.width

        lo = to_design(self.weight, REGULAR + min(grade, 0) * 2)
        hi = to_design(self.weight, REGULAR + max(grade, 0) * 2)
        for _ in range(40):  # the stem grows with weight
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fitted_stem(mid) < target else (lo, mid)
        return (lo + hi) / 2

    def master(self, source: SourceDescriptor, grade: int) -> ufoLib2.Font:
        base = ufoLib2.Font.open(source.path)
        location = {k: v for k, v in source.location.items() if k != self.weight.name}
        instance = InstanceDescriptor()
        instance.location = {**location, self.weight.name: self.weight_for(base, grade, location)}
        instance.familyName, instance.styleName = source.familyName, f"Grade {grade:+d}"
        font = self.instantiator.generate_instance(instance)
        fit(font, base)
        font.info.styleName = f"{base.info.styleName} Grade {grade:+d}"
        return font


def fit(font: ufoLib2.Font, base: ufoLib2.Font) -> None:
    """Scale each glyph horizontally to its width in base, and take base's
    kerning, so nothing is positioned differently from base."""
    for glyph in font:
        width = base[glyph.name].width
        # Zero-width glyphs (combining marks) keep their shape: nothing to fit.
        scale = width / glyph.width if glyph.width and width else 1.0
        for contour in glyph.contours:
            for point in contour.points:
                point.x, point.y = round(point.x * scale), round(point.y)
        for component in glyph.components:
            xx, xy, yx, yy, dx, dy = component.transformation
            component.transformation = (xx, xy, yx, yy, round(dx * scale), round(dy))
        for anchor in glyph.anchors:
            anchor.x, anchor.y = round(anchor.x * scale), round(anchor.y)
        glyph.width = width
    font.kerning.clear()
    font.kerning.update(copy.deepcopy(dict(base.kerning)))
    font.groups.clear()
    font.groups.update(copy.deepcopy(dict(base.groups)))


def add_grade(designspace: DesignSpaceDocument) -> DesignSpaceDocument:
    maker = GradeMaker(designspace)
    regular = [s for s in designspace.sources if s.location[maker.weight.name] == to_design(maker.weight, REGULAR)]
    masters = []
    for source in regular:
        for grade in GRADES:
            font = maker.master(source, grade)
            filename = source.filename.replace(".ufo", f"-Grade{grade:+d}.ufo")
            path = source.path.replace(source.filename, filename)
            font.save(path, overwrite=True)
            master = SourceDescriptor()
            master.filename, master.path = filename, path
            master.familyName, master.styleName = source.familyName, font.info.styleName
            master.location = {**source.location, "Grade": grade}
            masters.append(master)
            print(f"{filename}: grade {grade:+d}")
    axis = AxisDescriptor()
    axis.name, axis.tag = "Grade", "GRAD"
    axis.minimum, axis.default, axis.maximum = min(GRADES), 0, max(GRADES)
    designspace.addAxis(axis)
    for item in designspace.sources + designspace.instances:
        item.location["Grade"] = 0
    for master in masters:
        designspace.addSource(master)
    return designspace


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("designspace")
    ap.add_argument("output")
    args = ap.parse_args(argv)
    add_grade(DesignSpaceDocument.fromfile(args.designspace)).write(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
