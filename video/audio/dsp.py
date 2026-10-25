"""Shared DSP for the Offset audio: wav io, ffmpeg decode, reverb, BS.1770 loudness, true-peak limiter."""
import subprocess

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, lfilter, resample_poly, sosfilt

SR = 48000


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


def undb(d):
    return 10 ** (d / 20)


def write_wav(path, x, bits=16, seed=0):
    """Write float stereo/mono audio. 16-bit gets TPDF dither."""
    x = np.asarray(x, dtype=np.float64)
    if bits == 16:
        rng = np.random.default_rng(seed)
        d = (rng.random(x.shape) - rng.random(x.shape)) / 32768
        wavfile.write(path, SR, np.clip(np.round((x + d) * 32767), -32768, 32767).astype(np.int16))
    else:
        wavfile.write(path, SR, x.astype(np.float32))


def read_audio(path):
    """Decode anything ffmpeg reads to float64 stereo at 48 kHz, shape (n, 2)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64).reshape(-1, 2)


def sos(kind, f, order=2):
    return butter(order, f, kind, fs=SR, output="sos")


def filt(x, s):
    return sosfilt(s, x, axis=0)


def make_ir(sec=3.2, pre=0.022, damp=0.35, seed=7):
    """Synthetic stereo hall: decorrelated noise, highs decay faster than lows, soft onset."""
    n = int(sec * 1.6 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    ir = np.zeros((n, 2))
    for ch in range(2):
        noise = rng.standard_normal(n)
        lo = sosfilt(sos("low", 1800), noise)
        hi = sosfilt(sos("low", 6500), noise - lo)
        ir[:, ch] = lo * 10 ** (-3 * t / sec) + 0.4 * hi * 10 ** (-3 * t / (sec * damp))
    ir *= np.minimum(1, t / 0.03)[:, None] ** 2
    ir = np.vstack([np.zeros((int(pre * SR), 2)), ir])
    return ir / np.sqrt(np.sum(ir ** 2) / 2)


def reverb(x, ir, hp=180, lp=7000):
    wet = np.stack([fftconvolve(x[:, c], ir[:, c])[: len(x)] for c in range(2)], axis=1)
    return filt(filt(wet, sos("high", hp)), sos("low", lp))


# ITU-R BS.1770-4 K-weighting at 48 kHz.
_K1 = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
_K2 = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])


def lufs(x):
    """Integrated loudness (gated) of stereo float audio at 48 kHz."""
    y = lfilter(*_K2, lfilter(*_K1, x, axis=0), axis=0)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    if len(y) < blk:
        return -70.0
    p2 = np.cumsum(np.vstack([np.zeros((1, 2)), y ** 2]), axis=0)
    starts = np.arange(0, len(y) - blk + 1, hop)
    ms = ((p2[starts + blk] - p2[starts]) / blk).sum(axis=1)
    lk = -0.691 + 10 * np.log10(np.maximum(ms, 1e-20))
    g = ms[lk > -70]
    if not len(g):
        return -70.0
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    g = ms[(lk > -70) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(g.mean()))


def true_peak_db(x):
    return float(db(np.max(np.abs(resample_poly(x, 4, 1, axis=0)))))


def limit(x, ceiling_db=-1.5, look=0.0015, release=0.08):
    """Lookahead true-peak limiter: gain from 4x-oversampled peaks, min over the lookahead, smooth release."""
    c = undb(ceiling_db)
    pk = np.max(np.abs(resample_poly(x, 4, 1, axis=0)), axis=1)
    pk = np.max(pk[: len(x) * 4].reshape(-1, 4), axis=1) if len(pk) >= len(x) * 4 else np.pad(pk, (0, len(x) * 4 - len(pk))).reshape(-1, 4).max(1)
    need = np.minimum(1.0, c / np.maximum(pk, 1e-12))
    la = max(1, int(look * SR))
    # Min over a forward window, so gain is already down when the peak arrives.
    from scipy.ndimage import minimum_filter1d
    need = minimum_filter1d(need, size=2 * la + 1, mode="nearest")
    g = np.empty_like(need)
    a = np.exp(-1 / (release * SR))
    cur = 1.0
    for i, v in enumerate(need):  # one-pole release, instant attack (the window already looks ahead)
        cur = v if v < cur else v + (cur - v) * a
        g[i] = cur
    # Smooth the attack edge over the lookahead so it doesn't click.
    k = np.hanning(la * 2 + 1)
    g = np.minimum(g, np.convolve(g, k / k.sum(), mode="same"))
    return x * g[:, None]


def peq(x, f, gain_db, q=0.8):
    """RBJ peaking EQ."""
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f / SR
    al = np.sin(w) / (2 * q)
    b = [1 + al * A, -2 * np.cos(w), 1 - al * A]
    a = [1 + al / A, -2 * np.cos(w), 1 - al / A]
    return lfilter(np.array(b) / a[0], np.array(a) / a[0], x, axis=0)
