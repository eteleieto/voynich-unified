"""E1 machine observations: ink, text rows, locus alignment and gap measurements on the Yale canvases.

Everything here is a *proposal* produced by a documented algorithm (METHOD_VERSION); rows carry
`method`, `method_version`, `confidence` and `review_status='unreviewed'`. Coordinates are always
full-resolution canvas pixels (x right, y down), regardless of the working scale.

Pipeline per canvas (scale SCALE for speed):
  1. ink mask      L* darker than a large-median background by DARK_DELTA, excluding pigment hues
                   (green a*<-8, blue b*<-6, red a*>24) — i.e. brown iron-gall ink strokes.
  2. components    8-connected ink blobs -> ink_components (bbox, area, centroid, mean Lab)
  3. rows          glyph-sized components chained left->right when horizontally close and vertically
                   aligned; chains = fragments; fragments sharing a baseline = rows.
  4. alignment     per page/panel, ZL3b paragraph loci (type P*) in order are aligned to rows top->bottom
                   by dynamic programming on log(width / expected width); rows/loci may be skipped.
  5. gaps          per aligned row: ink clusters ordered by x, gap widths; every witness's token
                   boundaries are mapped to the physical gap nearest their proportional position.
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

from . import paths

METHOD = "vud.spatial"
METHOD_VERSION = "spatial-v1"
SCALE = 0.5
DARK_DELTA = 22
BG_KERNEL = 61  # at working scale


def load(path: str):
    im = cv2.imread(str(paths.ROOT / path), cv2.IMREAD_COLOR)
    if SCALE != 1:
        im = cv2.resize(im, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    return im


def ink_mask(im: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB)
    L, a, b = lab[..., 0], lab[..., 1].astype(np.int16) - 128, lab[..., 2].astype(np.int16) - 128
    bg = cv2.medianBlur(L, BG_KERNEL)
    dark = (bg.astype(np.int16) - L.astype(np.int16)) > DARK_DELTA
    pigment = (a < -8) | (b < -6) | (a > 24)
    # the black photo background around the leaf is not ink
    leaf = cv2.medianBlur(L, BG_KERNEL) > 60
    mask = (dark & ~pigment & leaf).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return mask, lab


def components(mask: np.ndarray, lab: np.ndarray) -> np.ndarray:
    """Return array of [x0, y0, w, h, area, cx, cy, L, a, b] at working scale (area >= 6)."""
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.where(stats[1:, cv2.CC_STAT_AREA] >= 6)[0] + 1
    out = np.zeros((len(keep), 10), dtype=np.float32)
    flat = labels.ravel()
    Lf, af, bf = (lab[..., i].ravel().astype(np.float32) for i in range(3))
    counts = np.bincount(flat, minlength=n)
    sums = [np.bincount(flat, weights=ch, minlength=n) for ch in (Lf, af, bf)]
    for k, i in enumerate(keep):
        x, y, w, h, area = stats[i]
        out[k] = [x, y, w, h, area, cents[i][0], cents[i][1],
                  sums[0][i] / counts[i], sums[1][i] / counts[i] - 128, sums[2][i] / counts[i] - 128]
    return out


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, i, j):
        self.p[self.find(i)] = self.find(j)


def glyph_height(comp: np.ndarray) -> float:
    h = comp[:, 3]
    sel = h[(comp[:, 4] >= 15) & (h >= 4) & (h <= 60)]
    return float(np.median(sel)) if len(sel) else 10.0


def _fit(xs, ys):
    if len(xs) < 2 or np.ptp(xs) < 1:
        return 0.0, float(np.median(ys))
    k, c = np.polyfit(xs, ys, 1)
    k = float(np.clip(k, -0.15, 0.15))
    return k, float(np.median(ys - k * xs))


def rows_from_components(comp: np.ndarray, gap_mult: float = 3.2, vtol: float = 0.5, merge_tol: float = 0.9):
    """Chain glyph-sized components into fragments, then fragments into slope-aware rows."""
    Hm = glyph_height(comp)
    x0, y0, w, h = comp[:, 0], comp[:, 1], comp[:, 2], comp[:, 3]
    glyphish = (h >= 0.35 * Hm) & (h <= 3.2 * Hm) & (w <= 6 * Hm) & (comp[:, 4] >= 0.05 * Hm * Hm)
    idx = np.where(glyphish)[0]
    if len(idx) < 3:
        return Hm, []
    core = y0 + np.minimum(h, 1.6 * Hm) * 0.5 + np.maximum(0, h - 1.6 * Hm)  # ignore ascender height
    bottom = y0 + h
    order = idx[np.argsort(x0[idx])]
    xs = x0[order]
    dsu = DSU(len(comp))
    for oi, i in enumerate(order):
        right = x0[i] + w[i]
        hi = np.searchsorted(xs, right + gap_mult * Hm, side="right")
        best, bestd = None, None
        for j in order[oi + 1:hi]:
            d = abs(core[j] - core[i])
            if d < vtol * Hm and (bestd is None or d < bestd):
                best, bestd = j, d
            if d < vtol * Hm and x0[j] < right:  # overlapping pieces of the same glyph
                dsu.union(i, j)
        if best is not None:
            dsu.union(i, best)
    groups: dict[int, list[int]] = {}
    for i in idx:
        groups.setdefault(dsu.find(i), []).append(i)
    fr = []
    for members in groups.values():
        m = np.array(members)
        X0, X1 = float(x0[m].min()), float((x0[m] + w[m]).max())
        if len(m) < 3 or (X1 - X0) < 2.5 * Hm:
            continue
        # baseline from non-descender bottoms (lower 70% of bottoms are typically on the baseline)
        k, c = _fit(comp[m, 5], np.minimum(bottom[m], np.percentile(bottom[m], 70)))
        fr.append({"members": m, "x0": X0, "y0": float(y0[m].min()), "x1": X1,
                   "y1": float((y0[m] + h[m]).max()), "k": k, "c": c, "n": len(m)})
    rows: list[dict] = []
    for f in sorted(fr, key=lambda f: f["x0"]):
        best, bestd = None, None
        for r in rows:
            if not (f["x0"] > r["x1"] - 1.5 * Hm and f["x0"] - r["x1"] < 30 * Hm):
                continue
            xm = (r["x1"] + f["x0"]) / 2
            d = abs((r["k"] * xm + r["c"]) - (f["k"] * xm + f["c"]))
            if d < merge_tol * Hm and (bestd is None or d < bestd):
                best, bestd = r, d
        if best is not None:
            best["frags"].append(f)
            best["x1"] = max(best["x1"], f["x1"]); best["y0"] = min(best["y0"], f["y0"]); best["y1"] = max(best["y1"], f["y1"])
            best["n"] += f["n"]
            m = np.concatenate([g["members"] for g in best["frags"]])
            best["k"], best["c"] = _fit(comp[m, 5], np.minimum(bottom[m], np.percentile(bottom[m], 70)))
        else:
            rows.append({"frags": [f], "x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
                         "k": f["k"], "c": f["c"], "n": f["n"]})
    for r in rows:
        r["ink_width"] = float(sum(f["x1"] - f["x0"] for f in r["frags"]))
        r["members"] = np.concatenate([f["members"] for f in r["frags"]])
        r["base"] = r["k"] * (r["x0"] + r["x1"]) / 2 + r["c"]
    rows = [r for r in rows if r["n"] >= 4]
    rows.sort(key=lambda r: (round(r["base"] / (1.5 * Hm)), r["x0"]))
    return Hm, rows


def rows_rlsa(comp: np.ndarray, shape, smear: float = 2.6, core_frac: float = 0.9):
    """Run-length-smearing line detection on glyph *core bands*.

    Each glyph-sized component paints only a band of height core_frac*Hm above its bottom (so tall
    gallows cannot bridge lines); bands are dilated horizontally by smear*Hm; connected blobs are line
    fragments; fragments on a common (slope-aware) baseline are merged into rows across drawing gaps.
    """
    Hm = glyph_height(comp)
    H, W = shape
    x0, y0, w, h = comp[:, 0], comp[:, 1], comp[:, 2], comp[:, 3]
    glyphish = (h >= 0.35 * Hm) & (h <= 3.2 * Hm) & (w <= 6 * Hm) & (comp[:, 4] >= 0.05 * Hm * Hm)
    idx = np.where(glyphish)[0]
    canvas = np.zeros((H, W), np.uint8)
    band = max(2, int(core_frac * Hm))
    for i in idx:
        b = int(y0[i] + min(h[i], 1.6 * Hm))  # bottom of the core (descenders clipped)
        cv2.rectangle(canvas, (int(x0[i]), max(0, b - band)), (int(x0[i] + w[i]), b), 1, -1)
    k = max(3, int(smear * Hm))
    canvas = cv2.dilate(canvas, np.ones((1, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(canvas, connectivity=8)
    # assign glyph components to blobs by their core-bottom point
    owner: dict[int, list[int]] = {}
    for i in idx:
        b = int(min(H - 1, y0[i] + min(h[i], 1.6 * Hm))) - 1
        cx = int(min(W - 1, x0[i] + w[i] / 2))
        o = lab[max(0, b), cx]
        if o:
            owner.setdefault(o, []).append(i)
    bottom = y0 + np.minimum(h, 1.6 * Hm)
    fr = []
    for o, members in owner.items():
        m = np.array(members)
        X0, X1 = float(x0[m].min()), float((x0[m] + w[m]).max())
        if len(m) < 3 or (X1 - X0) < 2.5 * Hm or st[o, cv2.CC_STAT_HEIGHT] > 3.0 * Hm:
            # very tall blobs are drawings / merged lines: keep out of the row set
            if len(m) >= 3 and st[o, cv2.CC_STAT_HEIGHT] > 3.0 * Hm:
                pass
            continue
        k_, c_ = _fit(comp[m, 5], bottom[m])
        fr.append({"members": m, "x0": X0, "y0": float(y0[m].min()), "x1": X1,
                   "y1": float((y0[m] + h[m]).max()), "k": k_, "c": c_, "n": len(m)})
    rows: list[dict] = []
    for f in sorted(fr, key=lambda f: f["x0"]):
        best, bestd = None, None
        for r in rows:
            if not (f["x0"] > r["x1"] - 1.5 * Hm and f["x0"] - r["x1"] < 30 * Hm):
                continue
            xm = (r["x1"] + f["x0"]) / 2
            d = abs((r["k"] * xm + r["c"]) - (f["k"] * xm + f["c"]))
            if d < 0.8 * Hm and (bestd is None or d < bestd):
                best, bestd = r, d
        if best is not None:
            best["frags"].append(f)
            best["x1"] = max(best["x1"], f["x1"]); best["y0"] = min(best["y0"], f["y0"]); best["y1"] = max(best["y1"], f["y1"])
            best["n"] += f["n"]
            m = np.concatenate([g["members"] for g in best["frags"]])
            best["k"], best["c"] = _fit(comp[m, 5], bottom[m])
        else:
            rows.append({"frags": [f], "x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
                         "k": f["k"], "c": f["c"], "n": f["n"]})
    for r in rows:
        r["ink_width"] = float(sum(f["x1"] - f["x0"] for f in r["frags"]))
        r["members"] = np.concatenate([f["members"] for f in r["frags"]])
        r["base"] = r["k"] * (r["x0"] + r["x1"]) / 2 + r["c"]
    rows = [r for r in rows if r["n"] >= 4]
    rows.sort(key=lambda r: (round(r["base"] / (1.5 * Hm)), r["x0"]))
    return Hm, rows


def rows_profile(comp: np.ndarray, shape, strip_mult: float = 10.0, band_frac: float = 0.6):
    """Piecewise projection-profile line detection (robust for dense, slanted paragraph text).

    1. core image: each glyph-sized component paints a band of band_frac*Hm above its (clipped) bottom
    2. the page is cut into vertical strips (strip_mult*Hm wide); in each strip the horizontal
       projection is smoothed and its peaks are text-line candidates
    3. peaks are chained strip-to-strip (|dy| < 0.6 Hm, may skip one strip) -> line paths
    4. components are assigned to the nearest path at their x (|dy| < 0.7 Hm); rows = paths with >= 4
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    Hm = glyph_height(comp)
    H, W = shape
    x0, y0, w, h = comp[:, 0], comp[:, 1], comp[:, 2], comp[:, 3]
    glyphish = (h >= 0.35 * Hm) & (h <= 3.2 * Hm) & (w <= 6 * Hm) & (comp[:, 4] >= 0.05 * Hm * Hm)
    idx = np.where(glyphish)[0]
    if len(idx) < 4:
        return Hm, []
    bottom = y0 + np.minimum(h, 1.6 * Hm)
    core = np.zeros((H, W), np.float32)
    band = max(2, int(band_frac * Hm))
    for i in idx:
        b = int(bottom[i])
        core[max(0, b - band):b, int(x0[i]):int(x0[i] + w[i])] = 1
    S = max(8, int(strip_mult * Hm))
    peaks = []  # (strip_index, x_center, y)
    for si, xs in enumerate(range(0, W, S)):
        prof = gaussian_filter1d(core[:, xs:xs + S].sum(axis=1), sigma=0.3 * Hm)
        pk, _ = find_peaks(prof, distance=max(2, int(1.3 * Hm)), height=1.2 * Hm)
        peaks += [(si, xs + S / 2, float(y)) for y in pk]
    # chain peaks across strips
    by_strip: dict[int, list] = {}
    for p in peaks:
        by_strip.setdefault(p[0], []).append(p)
    chains, open_ = [], []  # open_: list of chains still extendable
    for si in sorted(by_strip):
        new_open = []
        used = set()
        for ch in open_:
            last = ch[-1]
            if si - last[0] > 2:
                continue
            cands = [p for p in by_strip[si] if id(p) not in used and abs(p[2] - last[2]) < 0.6 * Hm]
            if cands:
                p = min(cands, key=lambda p: abs(p[2] - last[2]))
                used.add(id(p)); ch.append(p); new_open.append(ch)
            elif si - last[0] <= 1:
                new_open.append(ch)
        for p in by_strip[si]:
            if id(p) not in used:
                ch = [p]; chains.append(ch); new_open.append(ch)
        open_ = new_open
    # assign components to paths
    paths_ = [(np.array([p[1] for p in ch]), np.array([p[2] for p in ch])) for ch in chains]
    assign: dict[int, list[int]] = {}
    cx = x0 + w / 2
    for i in idx:
        best, bd = None, 0.7 * Hm
        for ci, (px, py) in enumerate(paths_):
            if cx[i] < px.min() - S or cx[i] > px.max() + S:
                continue
            yy = float(np.interp(cx[i], px, py))
            d = abs((bottom[i] - band / 2) - yy)
            if d < bd:
                best, bd = ci, d
        if best is not None:
            assign.setdefault(best, []).append(i)
    rows = []
    for ci, members in assign.items():
        m = np.array(sorted(members, key=lambda i: x0[i]))
        if len(m) < 4:
            continue
        # split into fragments at large horizontal gaps (drawing interruptions)
        frags, cur = [], [m[0]]
        for a, b in zip(m, m[1:]):
            if x0[b] - (x0[a] + w[a]) > 4 * Hm:
                frags.append(cur); cur = []
            cur.append(b)
        frags.append(cur)
        fr = []
        for f in frags:
            f = np.array(f)
            fr.append({"members": f, "x0": float(x0[f].min()), "x1": float((x0[f] + w[f]).max()),
                       "y0": float(y0[f].min()), "y1": float((y0[f] + h[f]).max()), "n": len(f)})
        k, c = _fit(cx[m], bottom[m])
        rows.append({"frags": fr, "members": m, "x0": fr[0]["x0"], "x1": max(f["x1"] for f in fr),
                     "y0": min(f["y0"] for f in fr), "y1": max(f["y1"] for f in fr), "k": k, "c": c,
                     "n": len(m), "ink_width": float(sum(f["x1"] - f["x0"] for f in fr)),
                     "path": [(float(a), float(b)) for a, b in zip(*paths_[ci])]})
    rows = merge_collinear(rows, comp, Hm)
    for r in rows:
        r["base"] = r["k"] * (r["x0"] + r["x1"]) / 2 + r["c"]
    rows.sort(key=lambda r: (round(r["base"] / (1.2 * Hm)), r["x0"]))
    return Hm, rows


def merge_collinear(rows: list[dict], comp: np.ndarray, Hm: float, tol: float = 0.6) -> list[dict]:
    """Merge rows that continue each other on the same baseline (broken chains, drawing gaps)."""
    x0, w = comp[:, 0], comp[:, 2]
    bottom = comp[:, 1] + np.minimum(comp[:, 3], 1.6 * Hm)
    changed = True
    while changed:
        changed = False
        rows.sort(key=lambda r: r["x0"])
        for a in rows:
            for b in rows:
                if a is b or b["x0"] < a["x1"] - 2 * Hm or b["x0"] - a["x1"] > 30 * Hm:
                    continue
                xm = (a["x1"] + b["x0"]) / 2
                if abs((a["k"] * xm + a["c"]) - (b["k"] * xm + b["c"])) < tol * Hm:
                    a["frags"] += b["frags"]; a["members"] = np.concatenate([a["members"], b["members"]])
                    a["x1"] = max(a["x1"], b["x1"]); a["y0"] = min(a["y0"], b["y0"]); a["y1"] = max(a["y1"], b["y1"])
                    a["n"] += b["n"]; a["ink_width"] += b["ink_width"]; a["path"] = a.get("path", []) + b.get("path", [])
                    m = a["members"]
                    a["k"], a["c"] = _fit(x0[m] + w[m] / 2, bottom[m])
                    rows[:] = [r for r in rows if r is not b]; changed = True
                    break
            if changed:
                break
    return rows


def leaf_interior(lab: np.ndarray, Hm: float) -> np.ndarray:
    """Mask of the leaf, eroded so that edge shadows / binding / page edges are excluded."""
    L = lab[..., 0]
    leaf = (cv2.medianBlur(L, BG_KERNEL) > 60).astype(np.uint8)
    n, lab_, st, _ = cv2.connectedComponentsWithStats(leaf, connectivity=4)
    if n > 1:
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        leaf = (lab_ == big).astype(np.uint8)
    k = max(3, int(3 * Hm))
    return cv2.erode(leaf, np.ones((k, k), np.uint8))


def rows_deskew(comp: np.ndarray, interior: np.ndarray | None = None, region=None):
    """One row per peak of the deskewed baseline profile.

    region: optional (x0, x1) at working scale restricting the components (foldout panels).
    Returns (Hm, rows, skew) where skew = dy/dx removed before profiling.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    Hm = glyph_height(comp)
    x0, y0, w, h = comp[:, 0], comp[:, 1], comp[:, 2], comp[:, 3]
    cx = x0 + w / 2
    bottom = y0 + np.minimum(h, 1.6 * Hm)
    ok = (h >= 0.35 * Hm) & (h <= 3.2 * Hm) & (w <= 6 * Hm) & (comp[:, 4] >= 0.05 * Hm * Hm)
    if interior is not None:
        yy = np.clip(comp[:, 6].astype(int), 0, interior.shape[0] - 1)
        xx = np.clip(comp[:, 5].astype(int), 0, interior.shape[1] - 1)
        ok &= interior[yy, xx] > 0
    if region is not None:
        ok &= (cx >= region[0]) & (cx < region[1])
    idx = np.where(ok)[0]
    if len(idx) < 8:
        return Hm, [], 0.0
    wts = w[idx]
    X, Yb = cx[idx], bottom[idx] - 0.3 * Hm
    best = None
    for t in np.linspace(-0.06, 0.06, 49):
        yp = Yb - t * (X - X.mean())
        prof = np.bincount(np.clip(yp, 0, None).astype(int), weights=wts)
        prof = gaussian_filter1d(prof, 0.25 * Hm)
        sc = float((prof ** 2).sum())
        if best is None or sc > best[0]:
            best = (sc, t, prof)
    _, t, prof = best
    pk, props = find_peaks(prof, distance=max(2, int(1.25 * Hm)), height=1.5 * Hm)
    yp = Yb - t * (X - X.mean())
    rows = []
    if len(pk) == 0:
        return Hm, [], float(t)
    nearest = np.abs(yp[:, None] - pk[None, :]).argmin(axis=1)
    dist = np.abs(yp - pk[nearest])
    for pi in range(len(pk)):
        sel = idx[(nearest == pi) & (dist < 0.75 * Hm)]
        if len(sel) < 4:
            continue
        m = sel[np.argsort(x0[sel])]
        frags, cur = [], [m[0]]
        for a, b in zip(m, m[1:]):
            if x0[b] - (x0[a] + w[a]) > 4 * Hm:
                frags.append(cur); cur = []
            cur.append(b)
        frags.append(cur)
        # drop isolated specks: fragments of < 3 components
        frags = [np.array(f) for f in frags if len(f) >= 3]
        if not frags:
            continue
        m = np.concatenate(frags)
        fr = [{"members": f, "x0": float(x0[f].min()), "x1": float((x0[f] + w[f]).max()),
               "y0": float(y0[f].min()), "y1": float((y0[f] + h[f]).max()), "n": len(f)} for f in frags]
        k, c = _fit(cx[m], bottom[m])
        rows.append({"frags": fr, "members": m, "x0": fr[0]["x0"], "x1": max(f["x1"] for f in fr),
                     "y0": min(f["y0"] for f in fr), "y1": max(f["y1"] for f in fr), "k": k, "c": c,
                     "n": len(m), "ink_width": float(sum(f["x1"] - f["x0"] for f in fr)),
                     "peak_height": float(prof[pk[pi]])})
    for r in rows:
        r["base"] = r["k"] * (r["x0"] + r["x1"]) / 2 + r["c"]
    rows.sort(key=lambda r: r["base"])
    return Hm, rows, float(t)


def align(loci: list[dict], rows: list[dict], Hm: float):
    """Monotone DP alignment of loci (with n_units) to rows (with ink_width). Returns list of (li, ri, cost)."""
    if not loci or not rows:
        return []
    # px per glyph unit: start from medians, refine once from the first alignment
    ratio = np.median([r["ink_width"] for r in rows]) / max(1.0, np.median([l["n_units"] for l in loci]))
    pairs = []
    for _ in range(2):
        n, m = len(loci), len(rows)
        SKIP_LOC = 1.6
        medw = float(np.median([r["ink_width"] for r in rows]))
        # skipping a full-width text row is expensive; skipping a stray fragment is cheap
        skip_row = [0.25 + 1.2 * min(1.0, r["ink_width"] / max(1.0, medw)) for r in rows]
        D = np.full((n + 1, m + 1), np.inf); D[0, 1:] = np.cumsum(skip_row); D[0, 0] = 0
        D[:, 0] = np.arange(n + 1) * SKIP_LOC
        B = np.zeros((n + 1, m + 1), dtype=np.int8)
        for i in range(1, n + 1):
            exp = max(1.0, loci[i - 1]["n_units"]) * ratio
            for j in range(1, m + 1):
                c = abs(math.log((rows[j - 1]["ink_width"] + Hm) / (exp + Hm)))
                opts = (D[i - 1, j - 1] + c, D[i, j - 1] + skip_row[j - 1], D[i - 1, j] + SKIP_LOC)
                k = int(np.argmin(opts)); D[i, j] = opts[k]; B[i, j] = k
        i, j, pairs = n, m, []
        while i > 0 and j > 0:
            if B[i, j] == 0:
                exp = max(1.0, loci[i - 1]["n_units"]) * ratio
                pairs.append((i - 1, j - 1, abs(math.log((rows[j - 1]["ink_width"] + Hm) / (exp + Hm)))))
                i, j = i - 1, j - 1
            elif B[i, j] == 1:
                j -= 1
            else:
                i -= 1
        pairs.reverse()
        if pairs:
            ratio = float(np.median([rows[r]["ink_width"] / max(1, loci[l]["n_units"]) for l, r, _ in pairs]))
    return pairs


def clusters_in_row(comp: np.ndarray, members: np.ndarray, Hm: float):
    """Merge x-overlapping components (pieces of one glyph) -> list of [x0, x1] ordered by x."""
    spans = sorted((float(comp[i, 0]), float(comp[i, 0] + comp[i, 2])) for i in members)
    out = []
    for a, b in spans:
        if out and a < out[-1][1] - 0.15 * Hm:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


# ============================================================================ full pipeline

GLYPH_KINDS = ("char", "rare", "lig", "alt", "unread", "unread_run")


def _detach_outliers(rows: list[dict], Hm: float) -> None:
    """Mark fragments outside the page's main text block (facing-page slivers, far margin labels)."""
    if not rows:
        return
    cxs = np.concatenate([[(f["x0"] + f["x1"]) / 2 for f in r["frags"]] for r in rows])
    lo, hi = np.percentile(cxs, 5) - 3 * Hm, np.percentile(cxs, 95) + 3 * Hm
    for r in rows:
        for f in r["frags"]:
            f["detached"] = not (lo <= (f["x0"] + f["x1"]) / 2 <= hi)
        kept = [f for f in r["frags"] if not f["detached"]] or r["frags"]
        r["ink_width"] = float(sum(f["x1"] - f["x0"] for f in kept))
        r["main_x0"], r["main_x1"] = min(f["x0"] for f in kept), max(f["x1"] for f in kept)


def _boundary_positions(tok_units: list[int]) -> list[float]:
    tot = float(sum(tok_units)) or 1.0
    cum, out = 0, []
    for n in tok_units[:-1]:
        cum += n
        out.append(cum / tot)
    return out


def match_boundaries(q: list[float], p: np.ndarray, size: np.ndarray, n_clusters: int, lam: float = 0.35):
    """Order-preserving assignment of k transcribed boundaries (positions q in [0,1]) to k distinct gaps
    (positions p, sizes in glyph-heights) maximising sum(size) - lam * drift(in clusters). O(k*G)."""
    k, G = len(q), len(p)
    if k == 0 or G < k:
        return [None] * k
    NEG = -1e18
    score = np.full((k, G), NEG); back = np.full((k, G), -1, int)
    for b in range(k):
        gain = size - lam * np.abs(p - q[b]) * n_clusters
        if b == 0:
            score[0] = gain
            continue
        best, arg = NEG, -1
        for g in range(G):
            if g - 1 >= 0 and score[b - 1, g - 1] > best:
                best, arg = score[b - 1, g - 1], g - 1
            if arg >= 0:
                score[b, g] = best + gain[g]; back[b, g] = arg
    g = int(np.argmax(score[k - 1])); out = [0] * k
    for b in range(k - 1, -1, -1):
        out[b] = g; g = back[b, g]
    return out


def process_canvas(job: dict) -> dict:
    """job: {seq, local_path, width, height, pages: [{page_id, region_xywh|None, loci: [...]}]}"""
    inv = 1.0 / SCALE
    im = load(job["local_path"])
    mask, lab = ink_mask(im)
    comp = components(mask, lab)
    Hm0 = glyph_height(comp)
    interior = leaf_interior(lab, Hm0)
    out = {k: [] for k in ("components", "rows", "alignment", "gaps", "boundaries", "qa")}
    seq = job["seq"]
    for i, c in enumerate(comp):
        out["components"].append((seq, i, *[float(v * inv) for v in c[:4]], float(c[4] * inv * inv),
                                   float(c[5] * inv), float(c[6] * inv), float(c[7]), float(c[8]), float(c[9])))
    for pg in job["pages"]:
        region = None
        if pg["region_xywh"] is not None:
            rx, _, rw, _ = pg["region_xywh"]
            region = (rx * SCALE, (rx + rw) * SCALE)
        Hm, rows, skew = rows_deskew(comp, interior, region)
        _detach_outliers(rows, Hm)
        loci = pg["loci"]
        p_loci = [l for l in loci if (l["locus_type"] or "").startswith("P")]
        pairs = align([{"n_units": l["n_units"]} for l in p_loci], rows, Hm) if p_loci else []
        row_ids = []
        for ri, r in enumerate(rows):
            rid = f"{pg['page_id']}:{seq}:{ri}"
            row_ids.append(rid)
            W, Hh = job["width"], job["height"]
            out["rows"].append({
                "row_id": rid, "page_id": pg["page_id"], "seq": seq, "row_idx": ri,
                "x0": max(0.0, r["x0"] * inv), "y0": max(0.0, r["y0"] * inv),
                "x1": min(float(W), r["x1"] * inv), "y1": min(float(Hh), r["y1"] * inv),
                "baseline_slope": r["k"], "baseline_intercept": r["c"] * inv,
                "n_components": int(r["n"]), "ink_width": r["ink_width"] * inv,
                "fragments_xyxy": [[f["x0"] * inv, f["y0"] * inv, f["x1"] * inv, f["y1"] * inv] for f in r["frags"]],
                "fragments_detached": [bool(f["detached"]) for f in r["frags"]],
                "glyph_height_px": Hm * inv, "page_skew": skew,
            })
        widths = []
        for li, ri, cost in pairs:
            L, r = p_loci[li], rows[ri]
            conf = float(math.exp(-2.5 * cost))
            out["alignment"].append({"locus_id": L["locus_id"], "page_id": pg["page_id"], "witness_id": "zl3b",
                                     "row_id": row_ids[ri], "seq": seq, "cost": cost, "confidence": conf,
                                     "n_units": L["n_units"], "row_ink_width": r["ink_width"] * inv})
            widths.append((L["n_units"], r["ink_width"]))
            # --- gaps between ink clusters along the main (non-detached) part of the row
            members = np.concatenate([f["members"] for f in r["frags"] if not f["detached"]] or [r["members"]])
            cl = clusters_in_row(comp, members, Hm)
            gaps = [(cl[k][1], cl[k + 1][0]) for k in range(len(cl) - 1)]
            gsize = np.array([max(0.0, b - a) for a, b in gaps])
            if len(gsize) == 0:
                continue
            ink_before = np.cumsum([b - a for a, b in cl])  # ink coordinate at the end of each cluster
            ink_total = float(ink_before[-1])
            order = np.argsort(-gsize)
            rank = np.empty(len(gsize), int); rank[order] = np.arange(len(gsize))
            for gi, (a, b) in enumerate(gaps):
                out["gaps"].append({"row_id": row_ids[ri], "locus_id": L["locus_id"], "gap_idx": gi,
                                    "x_left": a * inv, "x_right": b * inv, "gap_px": float(gsize[gi] * inv),
                                    "gap_norm": float(gsize[gi] / Hm), "rank_desc": int(rank[gi]),
                                    "ink_pos": float(ink_before[gi] / ink_total)})
            gpos = ink_before[:-1] / ink_total
            gnorm = gsize / Hm
            for w in L["witnesses"]:
                tu = w["token_units"]
                k = len(tu) - 1
                qs = _boundary_positions(tu)
                matched = match_boundaries(qs, gpos, gnorm, len(cl))
                for bi, (pos, kind) in enumerate(zip(qs, w["boundary_kinds"])):
                    near = int(np.argmin(np.abs(gpos - pos)))
                    gi = matched[bi] if matched[bi] is not None else near
                    out["boundaries"].append({
                        "witness_id": w["witness_id"], "locus_id": L["locus_id"], "row_id": row_ids[ri],
                        "boundary_idx": bi, "boundary_kind": kind, "predicted_ink_pos": pos,
                        "gap_idx": gi, "gap_px": float(gsize[gi] * inv), "gap_norm": float(gnorm[gi]),
                        "gap_rank_desc": int(rank[gi]), "in_top_k": bool(rank[gi] < k),
                        "position_error": float(abs(gpos[gi] - pos)),
                        "match_method": "dp" if matched[bi] is not None else "nearest",
                        "nearest_gap_idx": near, "nearest_gap_norm": float(gnorm[near]),
                        "n_gaps_in_row": int(len(gsize)), "n_boundaries": k,
                        "alignment_confidence": conf})
        corr = float(np.corrcoef(*zip(*widths))[0, 1]) if len(widths) >= 3 else None
        out["qa"].append({"page_id": pg["page_id"], "seq": seq, "glyph_height_px": Hm * inv, "skew": skew,
                          "n_rows": len(rows), "n_p_loci": len(p_loci), "n_aligned": len(pairs),
                          "mean_cost": float(np.mean([c for *_, c in pairs])) if pairs else None,
                          "width_units_corr": corr})
    return out
