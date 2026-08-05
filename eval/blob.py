#!/usr/bin/env python3
"""Shared classical-CV blob detector for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md section 4).

Deliberately dumb, no trained model: a scalar "birdness" map -> threshold -> morphological
open/close denoise -> connected-components -> area filter -> boxes. Both baseline_ndvi.py and
baseline_rgb.py feed this the same shape of input so approach (a) and (b) differ only in the
signal, not the machinery. If this baseline clears the FNR bar, we are done -- a network would be
unjustified complexity (docs/SPIKE_ndvi_vs_rgb.md section 4).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def detect_blobs(mask: np.ndarray, min_area: int, max_area: int, open_iter: int = 1,
                 close_iter: int = 1):
    """mask: bool (H,W) of candidate (bird) pixels. Returns list of [x0,y0,x1,y1] boxes.
    Morphological open (drop specks) then close (fill), 3x3 structure; label; area-filter."""
    struct = ndimage.generate_binary_structure(2, 1)  # 4-connectivity 3x3 cross
    m = mask
    if open_iter > 0:
        m = ndimage.binary_opening(m, structure=struct, iterations=open_iter)
    if close_iter > 0:
        m = ndimage.binary_closing(m, structure=struct, iterations=close_iter)
    labels, n = ndimage.label(m, structure=ndimage.generate_binary_structure(2, 2))  # 8-conn
    boxes = []
    if n == 0:
        return boxes
    slices = ndimage.find_objects(labels)
    for i, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        area = int((labels[sl] == i).sum())
        if area < min_area or area > max_area:
            continue
        ys, xs = sl
        boxes.append([float(xs.start), float(ys.start), float(xs.stop), float(ys.stop)])
    return boxes
