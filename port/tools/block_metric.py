#!/usr/bin/env python3
"""Measures a 16x16 block grid in a screenshot (blocky lighting on AMD/Windows).

The game renders at an internal resolution (1080p by default) and the capture may be scaled
(2560x1440: one 16 px block is ~21.3 px). For a region of the image (the ground, by default the
lower left, away from the HUD) it computes the edge energy between neighbouring columns and
rows, then:

  - autocorrelation of that 1D edge profile at the expected block period (higher = gridded);
  - phase fold: the edge energy folded modulo the period into 16 phase bins; a block grid puts
    its energy in one bin, so peak/median well above 1 means a grid aligned to the period.

Natural content scores close to 1.0 on the fold and close to 0 on the autocorrelation.

Usage: block_metric.py shot.png [more.png ...] [--region x,y,w,h] [--internal-width 1920]
       [--block 16] [--csv out.csv]
Region values are fractions of the image (0..1) when all are <= 1, pixels otherwise.
Needs numpy and Pillow (MSYS2: mingw-w64-clang-x86_64-python-{numpy,pillow}).
"""
import argparse
import csv
import sys

import numpy as np
from PIL import Image

DEFAULT_REGION = (0.03, 0.55, 0.55, 0.40)  # lower left: ground, no HUD prompts or FPS overlay
BINS = 16


def luminance(path):
    img = Image.open(path).convert('RGB')
    rgb = np.asarray(img, dtype=np.float64) / 255.0
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def crop(lum, region):
    h, w = lum.shape
    if all(v <= 1.0 for v in region):
        x, y, rw, rh = (region[0] * w, region[1] * h, region[2] * w, region[3] * h)
    else:
        x, y, rw, rh = region
    x0, y0 = int(round(x)), int(round(y))
    x1, y1 = min(w, x0 + int(round(rw))), min(h, y0 + int(round(rh)))
    if x1 - x0 < 64 or y1 - y0 < 64:
        sys.exit(f'region too small: {x0},{y0} to {x1},{y1}')
    return lum[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)


def edge_profile(lum, axis):
    """Mean |difference| between neighbouring columns (axis=1) or rows (axis=0)."""
    diff = np.abs(np.diff(lum, axis=axis))
    return diff.mean(axis=0 if axis == 1 else 1)


def autocorr_at(profile, period):
    p = profile - profile.mean()
    denom = float(np.dot(p, p))
    if denom == 0.0:
        return 0.0
    lo, hi = int(np.floor(period)), int(np.ceil(period))
    def ac(lag):
        return float(np.dot(p[:-lag], p[lag:])) / denom if lag < len(p) else 0.0
    if lo == hi:
        return ac(lo)
    t = period - lo
    return (1 - t) * ac(lo) + t * ac(hi)


def best_lag(profile, lo, hi):
    p = profile - profile.mean()
    denom = float(np.dot(p, p)) or 1.0
    lags = range(max(2, lo), min(hi, len(p) - 1) + 1)
    values = [float(np.dot(p[:-k], p[k:])) / denom for k in lags]
    i = int(np.argmax(values))
    return list(lags)[i], values[i]


def phase_fold(profile, period):
    # Edge between pixel i and i+1 sits at i + 0.5.
    pos = np.arange(len(profile)) + 0.5
    phase = np.floor((pos % period) / period * BINS).astype(int) % BINS
    sums = np.bincount(phase, weights=profile, minlength=BINS)
    counts = np.bincount(phase, minlength=BINS).astype(np.float64)
    means = sums / np.maximum(counts, 1)
    med = float(np.median(means)) or 1e-12
    return float(means.max()) / med, int(np.argmax(means))


def measure(path, region, internal_width, block):
    lum = luminance(path)
    h, w = lum.shape
    period = block * w / internal_width
    roi, box = crop(lum, region)
    out = {'file': path, 'size': f'{w}x{h}', 'region': ','.join(map(str, box)),
           'period_px': round(period, 2)}
    for name, axis in (('x', 1), ('y', 0)):
        prof = edge_profile(roi, axis)
        fold, phase = phase_fold(prof, period)
        lag, lag_val = best_lag(prof, int(period * 0.5), int(period * 3))
        out[f'ac_{name}'] = round(autocorr_at(prof, period), 3)
        out[f'fold_{name}'] = round(fold, 3)
        out[f'phase_{name}'] = phase
        out[f'best_lag_{name}'] = lag
        out[f'best_ac_{name}'] = round(lag_val, 3)
    out['score'] = round((out['fold_x'] + out['fold_y']) / 2, 3)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images', nargs='+')
    ap.add_argument('--region', default=','.join(map(str, DEFAULT_REGION)))
    ap.add_argument('--internal-width', type=float, default=1920)
    ap.add_argument('--block', type=float, default=16)
    ap.add_argument('--csv')
    args = ap.parse_args()
    region = tuple(float(v) for v in args.region.split(','))
    if len(region) != 4:
        sys.exit('--region needs x,y,w,h')
    rows = [measure(p, region, args.internal_width, args.block) for p in args.images]
    keys = list(rows[0])
    for r in rows:
        print(f"{r['file']}: {r['size']}, period {r['period_px']} px, region {r['region']}")
        print(f"  fold x {r['fold_x']} y {r['fold_y']}  (score {r['score']}; ~1.0 = no grid)")
        print(f"  autocorr at period x {r['ac_x']} y {r['ac_y']}; "
              f"best lag x {r['best_lag_x']} ({r['best_ac_x']}) y {r['best_lag_y']} ({r['best_ac_y']})")
    if args.csv:
        with open(args.csv, 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=keys)
            wr.writeheader()
            wr.writerows(rows)


if __name__ == '__main__':
    main()
