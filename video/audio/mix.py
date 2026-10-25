#!/usr/bin/env python3
"""Mix the Offset soundtrack: VO + SFX at cue times + a music bed ducked under the voice.

  python3 audio/mix.py <schedule.json> <out.m4a|out.wav> [--static-music] [--no-music] [--no-sfx]

Schedule (window.__video.schedule; extra keys are ignored):
  {"total": 92.47,
   "scenes": [{"id": "S1", "start": 0.0, "dur": 3.09}, ...],          optional, aligns the music
   "vo":     [{"scene": "S1", "file": "vo/S1.m4a", "start": 0.5}, ...], start = when the VO begins
   "cues":   [{"t": 9.1, "type": "whoosh"}, ...]}                        whoosh|tick|stamp|count|logo, optional "gain" (dB)
Also accepted: a bare array of scene entries like app.js emits today
({id, start, dur, voStart, voDur, file: "assets/vo/S1.m4a"}, VO placed at voStart), or {total, schedule: [...]}.
Files resolve against video/assets/, then video/. `time`/`at` work for `t`, `sfx`/`name` for `type`, `id` for `scene`.

The music is rendered for this timeline by music.py (tempo set so the logo lands on the tonic, lift at
the approval), cached in audio/.cache/; --static-music uses audio/music.wav instead. Ducking: -10 dB under
speech, 150 ms attack, 400 ms release, with lookahead. Music fades in 1.5 s and out over the last 3 s.
Master: -16 LUFS integrated, -1 dBTP ceiling (limited at -1.5 to leave room for the AAC encoder), AAC 192k.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsp import SR, limit, lufs, read_audio, true_peak_db, undb, write_wav  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.dirname(HERE)
TARGET_LUFS, CEILING = -16.0, -1.5
MUSIC_REL_DB = -8.0   # un-ducked music vs the voice (so about -18 dB under speech)
DUCK_DB, ATTACK, RELEASE, LOOKAHEAD, HOLD = -10.0, 0.15, 0.40, 0.12, 0.25
# SFX gain (dB) applied to each peak-normalized file, relative to a voice at -16 LUFS.
SFX_GAIN = {"whoosh": -9.0, "tick": -8.0, "stamp": -5.0, "count": -7.0, "logo": -4.0}
DUCKED_SFX = {"logo"}  # long, tonal cues that would mask speech: ducked 1.8x deeper than the music (-18 dB)
SFX_ALIAS = {"swoosh": "whoosh", "transition": "whoosh", "click": "tick", "thump": "stamp", "decline": "stamp",
             "declined": "stamp", "approve": "stamp", "approved": "stamp", "countup": "count", "count-up": "count",
             "chime": "logo", "end": "logo"}


def first(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def resolve(f):
    if not f:
        return None
    for p in (f, os.path.join(VIDEO, "assets", f), os.path.join(VIDEO, f), os.path.join(VIDEO, "assets", f.removeprefix("assets/"))):
        if os.path.isfile(p):
            return p
    return None


def parse(sch):
    if isinstance(sch, list):
        sch = {"schedule": sch}
    rows = first(sch, "vo", "schedule", "clips", default=[]) or []
    vo, scenes = [], list(first(sch, "scenes", default=[]) or [])
    for r in rows:
        sid = first(r, "scene", "id")
        start = first(r, "voStart", "start", "t")
        path = resolve(first(r, "file", "src", "path"))
        if "voStart" in r and "start" in r and sid and not first(sch, "scenes"):
            scenes.append({"id": sid, "start": r["start"], "dur": r.get("dur")})
        if start is None or not path:
            print(f"mix: skipping VO {sid or r} (no start or file not found)", file=sys.stderr)
            continue
        vo.append({"scene": sid, "path": path, "start": float(start)})
    cues = []
    for c in first(sch, "cues", "sfx", default=[]) or []:
        t, ty = first(c, "t", "time", "at", "start"), str(first(c, "type", "sfx", "name", default="")).lower()
        ty = SFX_ALIAS.get(ty, ty)
        if t is None or ty not in SFX_GAIN:
            print(f"mix: skipping cue {c}", file=sys.stderr)
            continue
        if any(o["type"] == ty and abs(o["t"] - float(t)) < 0.05 for o in cues):
            continue  # the same cue twice would just double its level
        cues.append({"t": float(t), "type": ty, "gain": float(c.get("gain", 0))})
    total = first(sch, "total", "duration")
    starts = {str(s.get("id")): float(s["start"]) for s in scenes if s.get("start") is not None}
    for v in vo:  # no scene table: approximate scene starts from VO starts
        if v["scene"]:
            starts.setdefault(v["scene"], max(0.0, v["start"] - 0.3))
    return vo, cues, starts, (float(total) if total else None)


def place(bus, x, t, gain=1.0):
    i0 = int(round(t * SR))
    if i0 >= len(bus):
        return
    if i0 < 0:
        x, i0 = x[-i0:], 0
    x = x[: len(bus) - i0]
    bus[i0:i0 + len(x)] += x * gain


def duck_curve(vo_bus, vo_lufs):
    """Gain (linear, per sample) for the music: DUCK_DB while speech is present, smooth attack/release."""
    hop = int(0.01 * SR)
    n = len(vo_bus) // hop + 1
    m = np.pad(vo_bus.mean(1), (0, n * hop - len(vo_bus)))
    rms = 10 * np.log10(np.maximum((m.reshape(n, hop) ** 2).mean(1), 1e-12))
    speech = rms > vo_lufs - 26
    # Hold through short gaps, and start early so the attack has finished when the word lands.
    sp = speech.copy()
    for k in range(1, int(HOLD / 0.01) + 1):
        sp[k:] |= speech[:-k]
    for k in range(1, int(LOOKAHEAD / 0.01) + 1):
        sp[:-k] |= speech[k:]
    target = np.where(sp, DUCK_DB, 0.0)
    g = np.empty(n)
    cur = 0.0
    a_dn, a_up = np.exp(-0.01 / (ATTACK / 3)), np.exp(-0.01 / (RELEASE / 3))  # ~95% of the move within ATTACK / RELEASE
    for i, v in enumerate(target):
        a = a_dn if v < cur else a_up
        cur = v + (cur - v) * a
        g[i] = cur
    gs = np.interp(np.arange(len(vo_bus)) / hop, np.arange(n), g)
    last = (np.flatnonzero(speech)[-1] + 1) * 0.01 if speech.any() else 0.0
    return undb(gs), sp.mean(), last


def get_music(starts, total, static, last_word):
    if not static:
        try:
            import music
            mk = {k: starts.get(k) for k in ("S4", "S12", "S13", "S16")}
            if mk["S16"] is None and starts:
                mk["S16"] = max(starts.values())
            mk["end"] = round(last_word + 0.15, 2)  # resolve after the closing line, not under it
            key = hashlib.sha1(json.dumps([mk, round(total, 2), open(music.__file__).read()], sort_keys=True).encode()).hexdigest()[:12]
            cache = os.path.join(HERE, ".cache", f"music-{key}.wav")
            if os.path.isfile(cache):
                return read_audio(cache), "cached render"
            x, arr = music.render(mk, length=total + 1.0, verbose=True)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            write_wav(cache, x)
            return x, f"rendered {arr.bpm:.1f} bpm, lift {arr.t(arr.b_lift):.2f}s, logo {arr.t(arr.n_logo):.2f}s, resolve {arr.t_end:.2f}s"
        except Exception as e:  # never block the video on the music
            print(f"mix: music render failed ({e}); using music.wav", file=sys.stderr)
    return read_audio(os.path.join(HERE, "music.wav")), "music.wav"


def ffmpeg_stats(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    j = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    return float(j["input_i"]), float(j["input_tp"]), float(j["input_lra"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schedule")
    ap.add_argument("out")
    ap.add_argument("--static-music", action="store_true", help="use audio/music.wav as is")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--no-sfx", action="store_true")
    a = ap.parse_args()

    vo, cues, starts, total = parse(json.load(open(a.schedule)))
    if not vo:
        sys.exit("mix: no usable VO clips in the schedule")
    clips = [(v, read_audio(v["path"])) for v in vo]
    if total is None:
        total = max(v["start"] + len(x) / SR for v, x in clips) + 2.5
    n = int(round(total * SR))

    vo_bus = np.zeros((n, 2))
    for v, x in clips:
        place(vo_bus, x, v["start"])
    vo_l = lufs(vo_bus)
    norm = undb(TARGET_LUFS - vo_l)  # bring everything to "voice at -16" before mixing
    vo_bus *= norm

    duck, frac, last_word = duck_curve(vo_bus, TARGET_LUFS)
    bed = np.zeros((n, 2))
    if not a.no_sfx:
        kit, ducked = {}, np.zeros((n, 2))
        for c in cues:
            if c["type"] not in kit:
                kit[c["type"]] = read_audio(os.path.join(HERE, "sfx", c["type"] + ".wav"))
            place(ducked if c["type"] in DUCKED_SFX else bed, kit[c["type"]], c["t"], undb(SFX_GAIN[c["type"]] + c["gain"]))
        bed += ducked * (duck ** 1.8)[:, None]

    note = "none"
    if not a.no_music:
        mus, note = get_music(starts, total, a.static_music, last_word)
        mus = np.pad(mus, ((0, max(0, n - len(mus))), (0, 0)))[:n]
        mus *= undb(TARGET_LUFS + MUSIC_REL_DB - lufs(mus))
        t = np.arange(n) / SR
        # Fade out over the last 3 s, but never start before the closing line has finished.
        f0 = min(max(total - 3.0, last_word + 0.15), total - 0.8)
        fade = np.sin(np.pi / 2 * np.clip(t / 1.5, 0, 1)) ** 2 * np.cos(np.pi / 2 * np.clip((t - f0) / (total - f0), 0, 1)) ** 2
        bed += mus * (duck * fade)[:, None]
        note += f", ducked {frac:.0%} of the time, last word {last_word:.2f}s, fade-out from {f0:.2f}s"

    # VO over everything else, per clip (loudness over the clip's span).
    over = {}
    for v, x in clips:
        i0, i1 = int(v["start"] * SR), min(n, int(v["start"] * SR) + len(x))
        if i1 - i0 > int(0.5 * SR):
            over[v["scene"] or "?"] = lufs(vo_bus[i0:i1]) - lufs(bed[i0:i1])
    mix = vo_bus + bed

    end = np.clip((total - np.arange(n) / SR) / 0.05, 0, 1)  # no click at the cut
    mix *= end[:, None]
    for _ in range(3):  # loudness, then true-peak limit, then correct for what the limiter took
        mix *= undb(TARGET_LUFS - lufs(mix))
        mix = limit(mix, CEILING)
    il, tp = lufs(mix), true_peak_db(mix)

    out = a.out
    if out.lower().endswith(".wav"):
        write_wav(out, mix)
    else:
        with tempfile.TemporaryDirectory() as td:
            w = os.path.join(td, "mix.wav")
            write_wav(w, mix, bits=32)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", w, "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-t", f"{total:.3f}", out], check=True)
    fi, ftp, lra = ffmpeg_stats(out)
    print(f"mix: {out}  {total:.2f}s  {len(vo)} VO, {0 if a.no_sfx else len(cues)} cues, music: {note}")
    worst = min(over, key=over.get)
    print("mix: VO over bed (LU): " + " ".join(f"{k}:{v:.0f}" for k, v in over.items()) + f"  (min {over[worst]:.1f} at {worst})")
    print(f"mix: pre-encode {il:.1f} LUFS / {tp:.1f} dBTP; file (ffmpeg loudnorm) I={fi:.1f} LUFS, TP={ftp:.1f} dBTP, LRA={lra:.1f} LU")


if __name__ == "__main__":
    main()
