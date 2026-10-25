#!/usr/bin/env python3
"""Offset music bed, synthesized from scratch (royalty-free, deterministic: same args give the same file).

  python3 audio/music.py                                  -> audio/music.wav, default timeline (~100 s)
  python3 audio/music.py --markers S4=9.2,S12=56,S13=66.5,S16=85.8 --length 92 --out /tmp/m.wav

Warm and minimal: Imaj7-vi7-IVmaj7-V in D around 84 bpm. Detuned additive pad, felt-piano arpeggios,
a soft sine-bass pulse, a hall reverb and gentle tape-style saturation. The tempo is nudged so the logo
(S16) lands on a bar line; S12 (the decline) thins out; the bar nearest S13 (the approval) opens the
filter and adds an octave lift after a one-bar swell. The closing line is spoken over a quiet held V, and
the music resolves to Dmaj9 and blooms on `end` (the last word of S16), or on the logo if `end` is absent.
mix.py calls render() with the real scene times, so the arrangement follows the picture.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsp import SR, filt, limit, lufs, make_ir, peq, reverb, sos, undb, write_wav  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# Scene starts of the current cut (sample_schedule.json); mix.py passes the real ones.
DEFAULT_MARKERS = {"S4": 10.89, "S12": 66.29, "S13": 77.95, "S16": 93.42, "end": 96.10}
DEFAULT_LENGTH = 100.0

# Chords, cycle position 0..3. bass, pad voicing, arpeggio tones (MIDI).
CHORDS = [
    (38, [50, 54, 57, 61, 64], [62, 66, 69, 73, 76]),  # Dmaj9
    (35, [47, 54, 57, 59, 62], [59, 62, 66, 69, 71]),  # Bm7(11)
    (43, [43, 55, 59, 62, 66], [59, 62, 66, 67, 69]),  # Gmaj7 (bass up an octave, it's warmer)
    (33, [45, 57, 59, 61, 64], [57, 61, 64, 69, 71]),  # A(add9)
]
FINAL = (38, [50, 57, 61, 64, 66, 69], [50, 57, 64, 66, 73, 78])  # Dmaj9, wider


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


class Arrangement:
    """Bar grid and sections derived from scene markers."""

    def __init__(self, markers, length):
        m = {**DEFAULT_MARKERS, **{k: v for k, v in (markers or {}).items() if v is not None}}
        logo = m["S16"]
        bars = max(4, round(logo / (240 / 84)))
        self.bar = logo / bars  # bar length (s), so the logo is exactly bar `bars`
        self.bpm = 240 / self.bar
        self.n_logo = bars
        to_bar = lambda t: int(np.clip(round(t / self.bar), 0, bars))  # noqa: E731
        self.b_main = max(1, to_bar(m["S4"]))
        self.b_pull = max(self.b_main, int(m["S12"] // self.bar))
        self.b_lift = int(np.clip(to_bar(m["S13"]), self.b_pull + 1, bars - 1))
        self.t_end = max(logo, m.get("end") or logo)  # the resolution: after the closing line, never under it
        self.length = max(length, self.t_end + 3)

    def t(self, bar, eighth=0.0):
        return (bar + eighth / 8) * self.bar

    def chord(self, bar):
        return CHORDS[(bar - self.n_logo) % 4]

    def section(self, bar):
        if bar >= self.n_logo:
            return "logo"
        if bar >= self.b_lift:
            return "lift"
        if bar >= self.b_pull:
            return "pull"
        if bar >= self.b_main:
            return "main"
        return "intro"


def automation(arr, points, n, sr):
    """Piecewise-linear curve from (time, value) points, sampled at sr."""
    ts, vs = zip(*sorted(points))
    return np.interp(np.arange(n) / sr, ts, vs)


# ---------------- instruments ----------------

PAD_SR = 24000  # the pad has nothing above ~4 kHz, so render at half rate and upsample


def pad(arr, rng):
    n = int(arr.length * PAD_SR)
    out = np.zeros((n, 2))
    B = arr.bar
    # Filter cutoff and level by section (ramped over about a bar).
    fc_pts = [(0, 420), (arr.t(arr.b_main) - B, 650), (arr.t(arr.b_main), 1000), (arr.t(arr.b_pull), 1000),
              (arr.t(arr.b_pull) + B, 520), (arr.t(arr.b_lift) - 1.5 * B, 560), (arr.t(arr.b_lift), 1900),
              (arr.t(arr.n_logo) - 0.5 * B, 1700), (arr.t(arr.n_logo) + 0.5, 1100), (arr.t_end, 1100),
              (arr.t_end + 0.7, 1600), (arr.length, 900)]
    fc = automation(arr, fc_pts, n, PAD_SR)
    lv_pts = [(0, 0.0), (2.5, 0.5), (arr.t(arr.b_main) - B, 0.55), (arr.t(arr.b_main), 0.8),
              (arr.t(arr.b_pull), 0.85), (arr.t(arr.b_pull) + B, 0.5), (arr.t(arr.b_lift) - B, 0.6), (arr.t(arr.b_lift), 1.0), (arr.t(arr.n_logo) - 0.5 * B, 1.0),
              (arr.t(arr.n_logo) + 0.5, 0.6), (arr.t_end, 0.6), (arr.t_end + 0.7, 1.15), (arr.length, 0.8)]
    lv = automation(arr, lv_pts, n, PAD_SR)
    t_all = np.arange(n) / PAD_SR

    def note(m, t0, t1, gain, att=0.9, rel=1.6):
        i0, i1 = int(max(0, t0) * PAD_SR), min(n, int((t1 + rel) * PAD_SR))
        t = t_all[i0:i1] - t0
        env = np.minimum(1, np.maximum(t, 0) / att) ** 1.5
        env *= np.clip(1 - (t - (t1 - t0)) / rel, 0, 1) ** 2
        f0 = hz(m)
        fcs = fc[i0:i1]
        for det, pan in ((-6, 0.15), (0.0, 0.5), (6, 0.85)):
            f = f0 * 2 ** (det / 1200)
            lfo = 1 + 0.12 * np.sin(2 * np.pi * rng.uniform(0.07, 0.2) * t + rng.uniform(0, 6.3))
            sig = np.zeros_like(t)
            for h in range(1, 17):
                fh = f * h
                if fh > 4200:
                    break
                w = h ** -1.35 / np.sqrt(1 + (fh / fcs) ** 4)
                sig += w * np.sin(2 * np.pi * fh * t + rng.uniform(0, 6.3))
            s = sig * env * lfo * gain
            out[i0:i1, 0] += s * np.cos(pan * np.pi / 2)
            out[i0:i1, 1] += s * np.sin(pan * np.pi / 2)

    for b in range(arr.n_logo):
        _, voicing, _ = arr.chord(b)
        sec = arr.section(b)
        for i, m in enumerate(voicing):
            g = 0.4
            t1 = arr.t_end if b == arr.n_logo - 1 else arr.t(b + 1)  # the last V holds under the closing line
            note(m, arr.t(b) - 0.08, t1 - 0.08, g)
            if sec == "lift" and i >= 2:  # octave shimmer
                note(m + 12, arr.t(b) - 0.08, arr.t(b + 1) - 0.08, 0.13, att=1.4)
    t_logo = arr.t_end
    for i, m in enumerate(FINAL[1]):
        note(m, t_logo - 0.08, arr.length - 1.8, 0.38, att=0.6, rel=1.8)
        if i >= 3:
            note(m + 12, t_logo + 0.3, arr.length - 1.8, 0.12, att=2.0, rel=1.8)
    out *= lv[:, None]
    from scipy.signal import resample_poly
    up = resample_poly(out, 2, 1, axis=0)[: int(arr.length * SR)]
    return filt(up, sos("high", 110))  # leave the low end to the bass


def piano_note(m, vel, rng, dur=None):
    """Felt piano: slightly inharmonic partials, two-stage decay, highs die fast, a soft hammer thump."""
    f0 = hz(m)
    t60 = float(np.interp(m, [45, 85], [5.5, 1.8]))
    L = dur or t60 * 0.9
    t = np.arange(int(L * SR)) / SR
    bright = 900 + 2600 * vel  # felt: harder hits are brighter
    sig = np.zeros_like(t)
    for k in range(1, 13):
        fk = k * f0 * np.sqrt(1 + 0.00035 * k * k)
        if fk > 7000:
            break
        a = k ** -1.1 / np.sqrt(1 + (fk / bright) ** 4)
        dk = t60 / (1 + 0.55 * (k - 1))
        env = 0.65 * np.exp(-6.9 * t / (dk * 0.25)) + 0.35 * np.exp(-6.9 * t / dk)
        for det in (-0.9, 0.9):  # two strings, a hair apart
            sig += 0.5 * a * env * np.sin(2 * np.pi * fk * 2 ** (det / 1200) * t + rng.uniform(0, 6.3))
    sig *= np.minimum(1, t / 0.006)
    nh = min(len(t), int(0.03 * SR))
    thump = rng.standard_normal(nh) * np.exp(-t[:nh] / 0.008)
    sig[:nh] += 0.05 * filt(thump, sos("low", 700))
    if dur:
        sig *= np.clip((L - t) / 0.4, 0, 1)
    return sig * vel


# Eighth-note arpeggio patterns: (eighth, tone index, velocity, octave shift)
PAT_MAIN = [[(0, 0, .70, 0), (2, 2, .50, 0), (3, 3, .44, 0), (5, 4, .44, 0), (6, 2, .38, 0)],
            [(0, 1, .62, 0), (2, 3, .48, 0), (4, 2, .44, 0), (5, 4, .40, 0), (7, 3, .34, 0)]]
PAT_LIFT = [[(0, 0, .74, 0), (1, 2, .40, 0), (2, 3, .50, 0), (3, 4, .42, 0), (4, 2, .36, 1), (5, 4, .46, 0), (6, 3, .40, 0), (7, 1, .30, 1)],
            [(0, 1, .66, 0), (1, 3, .38, 0), (2, 2, .48, 0), (3, 4, .40, 1), (4, 3, .44, 0), (5, 2, .36, 1), (6, 4, .40, 0), (7, 3, .30, 0)]]
PAT_INTRO = [[(0, 3, .42, 0), (5, 4, .30, 0)], [(2, 2, .36, 0)]]
PAT_PULL = [[(0, 0, .50, 0)], [(4, 2, .34, 0)]]


def piano(arr, rng):
    n = int(arr.length * SR)
    out = np.zeros((n, 2))

    def place(m, t0, vel, dur=None):
        s = piano_note(m, vel, rng, dur)
        i0 = int(t0 * SR)
        s = s[: max(0, n - i0)]
        pan = float(np.clip(np.interp(m, [50, 80], [0.35, 0.68]), 0, 1))
        out[i0:i0 + len(s), 0] += s * np.cos(pan * np.pi / 2)
        out[i0:i0 + len(s), 1] += s * np.sin(pan * np.pi / 2)

    pats = {"intro": PAT_INTRO, "main": PAT_MAIN, "pull": PAT_PULL, "lift": PAT_LIFT}
    for b in range(arr.n_logo):
        sec = arr.section(b)
        if sec == "intro" and b == 0:
            continue
        _, _, tones = arr.chord(b)
        for e, ti, v, o in pats[sec][b % 2]:
            jit = rng.normal(0, 0.006)
            place(tones[ti] + 12 * o, max(0, arr.t(b, e) + jit), float(np.clip(v + rng.normal(0, 0.04), 0.1, 1)))
    # Ending: a rolled Dmaj9 and a high answer, after the last word.
    t0 = arr.t_end
    for i, m in enumerate(FINAL[2]):
        place(m, t0 + i * 0.045, 0.62 - 0.04 * i)
    place(81, t0 + 2 * arr.bar / 4, 0.32)
    place(78, t0 + 2.75 * arr.bar / 4, 0.26)
    return out


def bass(arr, rng):
    n = int(arr.length * SR)
    out = np.zeros(n)

    def note(m, t0, dur, vel):
        i0 = int(t0 * SR)
        L = min(int((dur + 0.25) * SR), n - i0)
        if L <= 0:
            return
        t = np.arange(L) / SR
        f = hz(m)
        env = np.minimum(1, t / 0.025) * np.exp(-t / (dur * 1.6)) * np.clip((dur + 0.25 - t) / 0.25, 0, 1)
        s = np.sin(2 * np.pi * f * t) + 0.32 * np.sin(4 * np.pi * f * t) + 0.1 * np.sin(6 * np.pi * f * t)
        out[i0:i0 + L] += s * env * vel

    q = arr.bar / 4
    for b in range(arr.n_logo):
        sec = arr.section(b)
        root = arr.chord(b)[0]
        if sec == "main":
            for beat in range(4):
                note(root, arr.t(b) + beat * q, q * 0.85, 0.55 if beat % 2 == 0 else 0.4)
        elif sec == "pull":
            note(root, arr.t(b), arr.bar * 0.95, 0.45)
        elif sec == "lift":
            for e in range(8):
                note(root + (12 if e == 7 else 0), arr.t(b, e), q * 0.42, 0.55 if e % 2 == 0 else 0.36)
    if arr.t_end > arr.t(arr.n_logo) + 0.3:
        note(arr.chord(arr.n_logo - 1)[0], arr.t(arr.n_logo), arr.t_end - arr.t(arr.n_logo), 0.35)
    note(FINAL[0], arr.t_end, max(1.0, arr.length - arr.t_end - 1.5), 0.6)
    # Pump the bass a little against the beat, for a breathing pulse.
    return np.stack([out, out], axis=1)


def riser(arr, rng):
    """One-bar airy swell into the approval lift."""
    n = int(arr.length * SR)
    out = np.zeros((n, 2))
    t0, t1 = arr.t(arr.b_lift - 1), arr.t(arr.b_lift)
    i0, i1 = int(t0 * SR), int(t1 * SR)
    L = i1 - i0
    x = np.linspace(0, 1, L)
    noise = rng.standard_normal((L, 2))
    # Crossfade three band-limited noises for a rising sweep without a time-varying filter.
    lows = filt(noise, sos("band", [250, 900]))
    mids = filt(noise, sos("band", [900, 2600]))
    highs = filt(noise, sos("band", [2600, 3800]))
    sw = (lows * (1 - x)[:, None] + mids * np.sin(np.pi * x)[:, None] + 0.6 * highs * x[:, None] ** 2)
    env = x ** 2.2 * np.clip((1 - x) / 0.04, 0, 1) ** 0.5
    out[i0:i1] = filt(sw * env[:, None], sos("low", 3500))
    return out


def render(markers=None, length=DEFAULT_LENGTH, target_lufs=-20.0, seed=84, verbose=False):
    arr = Arrangement(markers, length)
    rng = np.random.default_rng(seed)
    if verbose:
        print(f"music: {arr.bpm:.1f} bpm, bar {arr.bar:.3f}s, main@{arr.b_main} pull@{arr.b_pull} "
              f"lift@{arr.b_lift} ({arr.t(arr.b_lift):.2f}s) logo@{arr.n_logo} ({arr.t(arr.n_logo):.2f}s), "
              f"resolve {arr.t_end:.2f}s, {arr.length:.1f}s")
    p = pad(arr, rng) * 0.11
    k = piano(arr, rng) * 0.16
    bs = bass(arr, rng) * 0.10
    rs = riser(arr, rng) * 0.018
    L = min(len(p), len(k), len(bs), len(rs))  # stems can differ by a sample after resampling
    p, k, bs, rs = p[:L], k[:L], bs[:L], rs[:L]
    ir = make_ir(3.4)
    wet = reverb(p * 0.55 + k * 0.45 + rs * 0.8, ir)
    mix = p + k + bs + rs * 0.5 + wet * 0.42
    # Glue: gentle tanh saturation, then tame the top and the very bottom.
    drive = 1.8
    mix = np.tanh(drive * mix) / drive
    mix = filt(mix, sos("high", 32))
    mix = filt(mix, sos("low", 9000, 2))
    mix = peq(mix, 320, -2.5, 0.9)  # clear a little room for the voice
    n = len(mix)
    fade = np.ones(n)
    fo = int(1.8 * SR)
    fade[-fo:] = np.linspace(1, 0, fo) ** 2
    mix *= fade[:, None]
    mix *= undb(target_lufs - lufs(mix))
    mix = limit(mix, -2.0)
    return mix, arr


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markers", help="scene starts (+ end = last word of S16), e.g. S4=9.2,S12=56,S13=66.5,S16=85.8,end=88.6")
    ap.add_argument("--length", type=float, default=DEFAULT_LENGTH)
    ap.add_argument("--out", default=os.path.join(HERE, "music.wav"))
    a = ap.parse_args()
    mk = dict((k, float(v)) for k, v in (kv.split("=") for kv in a.markers.split(","))) if a.markers else None
    mix, _ = render(mk, a.length, verbose=True)
    write_wav(a.out, mix)
    print(f"wrote {a.out}: {len(mix) / SR:.1f}s, {lufs(mix):.1f} LUFS")


if __name__ == "__main__":
    main()
