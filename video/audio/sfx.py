#!/usr/bin/env python3
"""Synthesize the understated SFX kit into audio/sfx/*.wav (deterministic).

  whoosh  soft airy pass, 0.5 s, pans left to right
  tick    UI click
  stamp   low soft thump for DECLINED / Approved
  count   subtle rising ticks for count-ups (~0.9 s)
  logo    warm swell into a D-major chime (matches the music's key)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsp import SR, filt, make_ir, reverb, sos, undb, write_wav  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sfx")


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def _pan(mono, p):
    return np.stack([mono * np.cos(p * np.pi / 2), mono * np.sin(p * np.pi / 2)], axis=1)


def _norm(x, peak_db):
    return x * undb(peak_db) / max(np.max(np.abs(x)), 1e-9)


def whoosh(rng):
    t = _t(0.55)
    x = t / t[-1]
    noise = rng.standard_normal(len(t))
    # Sweep a band up then down by crossfading fixed bands (smooth, no filter zipper).
    bands = [filt(noise, sos("band", b)) for b in ([200, 600], [500, 1400], [1200, 3200])]
    w = [np.clip(1 - 2 * x, 0, 1), np.sin(np.pi * x), np.sin(np.pi * np.clip(x * 1.4 - 0.2, 0, 1)) * 0.5]
    sig = sum(b * wi for b, wi in zip(bands, w))
    env = np.sin(np.pi * x ** 0.8) ** 2
    sig *= env
    p = 0.25 + 0.5 * x
    st = np.stack([sig * np.cos(p * np.pi / 2), sig * np.sin(p * np.pi / 2)], axis=1)
    return _norm(filt(st, sos("low", 4000)), -6)


def tick(rng):
    t = _t(0.06)
    body = np.sin(2 * np.pi * 1450 * t) * np.exp(-t / 0.006) + 0.6 * np.sin(2 * np.pi * 620 * t) * np.exp(-t / 0.012)
    click = filt(rng.standard_normal(len(t)) * np.exp(-t / 0.0015), sos("band", [1500, 4000]))
    sig = (body + 0.3 * click) * np.minimum(1, t / 0.0008)
    return _norm(_pan(sig, 0.5), -8)


def stamp(rng):
    t = _t(0.7)
    f = 72 + 95 * np.exp(-t / 0.03)  # pitch drop: the "thud"
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = (np.sin(ph) + 0.3 * np.sin(2 * ph)) * np.exp(-t / 0.13) * np.minimum(1, t / 0.002)
    knock = filt(rng.standard_normal(len(t)), sos("band", [180, 900])) * np.exp(-t / 0.018)
    paper = filt(rng.standard_normal(len(t)), sos("band", [900, 2500])) * np.exp(-t / 0.01) * 0.15
    sig = body + 0.6 * knock + paper
    st = _pan(sig, 0.5)
    st = st + 0.12 * reverb(st, make_ir(0.6, pre=0.008, seed=3))
    return _norm(st, -4)


def count(rng):
    n = 9
    total = 0.9
    # Accelerating ticks with rising pitch; the last one is a touch brighter.
    times = total * (1 - (1 - np.linspace(0, 1, n)) ** 1.6)
    out = np.zeros((int((total + 0.15) * SR), 2))
    for i, tt in enumerate(times):
        t = _t(0.05)
        f = 900 * 2 ** (i / (n - 1) * 0.9)
        s = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.009) * np.minimum(1, t / 0.0008)
        s *= 0.55 + 0.45 * i / (n - 1)
        i0 = int(tt * SR)
        out[i0:i0 + len(s)] += _pan(s, 0.4 + 0.2 * i / (n - 1))
    return _norm(filt(out, sos("low", 5000)), -10)


def logo(rng):
    t = _t(3.6)
    sig = np.zeros((len(t), 2))
    # Swell: soft Dmaj9 pad rising into the chime.
    sw = np.clip(t / 0.7, 0, 1) ** 2 * np.exp(-np.maximum(t - 0.7, 0) / 0.9)
    for m, p in ((50, 0.4), (57, 0.6), (61, 0.35), (64, 0.65), (66, 0.5)):
        f = 440 * 2 ** ((m - 69) / 12)
        for h, a in ((1, 1), (2, 0.35), (3, 0.12)):
            sig += _pan(a * np.sin(2 * np.pi * f * h * t + rng.uniform(0, 6)) * sw * 0.18, p)
    # Chime: two soft bells (D6, A6) with slightly inharmonic partials, struck at the top of the swell.
    for m, at, g, p in ((86, 0.62, 1.0, 0.45), (93, 0.74, 0.55, 0.6)):
        f = 440 * 2 ** ((m - 69) / 12)
        tt = np.maximum(t - at, 0)
        on = (t >= at) * np.minimum(1, tt / 0.003)
        bell = sum(a * np.sin(2 * np.pi * f * r * tt) * np.exp(-tt / d)
                   for r, a, d in ((1, 1, 1.4), (2.0, 0.3, 0.7), (2.76, 0.12, 0.35), (5.4, 0.03, 0.15)))
        sig += _pan(bell * on * g * 0.35, p)
    sig = filt(sig, sos("low", 6500))
    sig = sig + 0.35 * reverb(sig, make_ir(2.4, seed=11))
    fade = np.clip((t[-1] - t) / 0.5, 0, 1)[:, None]
    return _norm(sig * fade, -5)


KIT = {"whoosh": whoosh, "tick": tick, "stamp": stamp, "count": count, "logo": logo}


def main():
    os.makedirs(OUT, exist_ok=True)
    for i, (name, fn) in enumerate(KIT.items()):
        x = fn(np.random.default_rng(100 + i))
        write_wav(os.path.join(OUT, f"{name}.wav"), x, seed=i)
        print(f"sfx/{name}.wav {len(x) / SR:.2f}s")


if __name__ == "__main__":
    main()
