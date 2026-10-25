#!/usr/bin/env python3
"""Finish the Offset product video: deliverables + QC, from out/offset-product.mp4.

    python3 video/finish/finish.py                 # all deliverables into out/deliver/
    python3 video/finish/finish.py --in other.mp4  # finish a different master
    options: --root <video dir>  --out <dir>  --poster-time <s>  --skip-encodes (captions/QC only)

Writes to out/deliver/:
  offset-product-1080p.mp4  master (stream copy + faststart; audio re-mastered only if > 1.5 LU off -16 LUFS)
  offset-product-web.mp4    1080p H.264 ~7 Mbps, 48 kHz stereo AAC, +faststart (Devpost/YouTube)
  offset-product-720p.mp4   < 15 MB (Slack)
  teaser-15s.mp4            hook -> hedge card -> DECLINED -> logo, crossfaded
  captions.srt / .vtt       vo.txt timed to the real on-video VO starts
  poster.png                untouched still (logo end card by default)
  contact-sheet.png         one frame every 3 s
  schedule.json, qc.json    the schedule used and every QC measurement
Needs ffmpeg/ffprobe on PATH; node + Playwright (frontend/node_modules) for the schedule and the poster still.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET_LUFS, LUFS_TOL = -16.0, 1.5
WEB_KBPS, SLACK_MAX_MB = 7000, 15
TEASER_LEN, XFADE = 15.0, 0.5
MAX_CHARS, MAX_LINES = 42, 2
BACKDROP = [(0x14, 0x3c, 0x2a), (0x12, 0x2b, 0x1f), (0x0f, 0x1a, 0x14)]  # #stage gradient: --deep, mean, --night

issues = []


def warn(msg):
    issues.append(msg)
    print("  ! " + msg)


def run(cmd, capture=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r.stdout + r.stderr if capture else None


def ff(*a):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a])


def probe(path):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path], capture=True))
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    num, den = map(int, v.get("r_frame_rate", "30/1").split("/"))
    return {"duration": float(j["format"]["duration"]), "size_mb": os.path.getsize(path) / 1e6,
            "kbps": round(int(j["format"].get("bit_rate", 0)) / 1000), "vcodec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
            "width": v.get("width"), "height": v.get("height"), "fps": num / den, "v_start": float(v.get("start_time", 0)),
            "acodec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate", 0) or 0), "channels": a.get("channels"),
            "a_start": float(a.get("start_time", 0)) if a else None}


def loudness(path):
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"], capture=True)
    summ = out[out.rfind("Summary:"):]
    get = lambda k: float(re.search(k + r":\s+(-?[\d.]+|-inf)", summ).group(1).replace("-inf", "-200"))
    return {"I": get("I"), "LRA": get("LRA"), "TP": get("Peak")}


def silences(path, start=0.0, dur=None, noise="-40dB", d=0.12):
    """[(silence_start, silence_end)] in absolute seconds of `path`."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start)] + (["-t", str(dur)] if dur else []) + \
          ["-i", path, "-map", "0:a:0", "-af", f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"]
    out = run(cmd, capture=True)
    s = [float(x) + start for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    e = [float(x) + start for x in re.findall(r"silence_end: (-?[\d.]+)", out)]
    return list(zip(s, e + [math.inf] * (len(s) - len(e))))


# ---------- schedule ----------
def load_schedule(root, out_dir):
    """Prefer out/schedule.json (written by the recorder), else ask the page, else fall back to timing.json."""
    src = os.path.join(root, "out", "schedule.json")
    data = None
    if os.path.exists(src):
        data, how = json.load(open(src)), "out/schedule.json"
    else:
        try:
            r = subprocess.run(["node", os.path.join(HERE, "dump-schedule.mjs"), root], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                data, how = json.loads(r.stdout), "page (window.__video.schedule)"
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    if data is None:
        t = json.load(open(os.path.join(root, "assets", "vo", "timing.json")))
        data = {"total": t["total"], "schedule": [{"id": s["scene"], "start": s["start"], "dur": s["duration"],
                                                   "voStart": s["start"], "voDur": s["duration"], "file": "assets/" + s["file"]}
                                                  for s in t["scenes"]]}
        how = "assets/vo/timing.json (no holds: real video times unknown)"
        warn("schedule fell back to timing.json; caption times ignore scene lead-ins")
    if isinstance(data, dict) and isinstance(data.get("schedule"), dict):
        data = data["schedule"]  # dump-schedule.mjs wraps the page's object
    if isinstance(data, dict) and "scenes" in data:
        # record.mjs / page format: scenes [{id, start, dur}] + vo [{scene, file, start, duration}]
        vo = {v["scene"]: v for v in data.get("vo", [])}
        sched = [{"id": sc["id"], "start": sc["start"], "dur": sc["dur"],
                  "voStart": vo.get(sc["id"], {}).get("start", sc["start"]), "voDur": vo.get(sc["id"], {}).get("duration", sc["dur"]),
                  "file": vo.get(sc["id"], {}).get("file", "")} for sc in data["scenes"]]
    else:
        sched = data["schedule"] if isinstance(data, dict) else data
    total = data.get("total") if isinstance(data, dict) else None
    total = total or max(s["start"] + s["dur"] for s in sched)
    json.dump({"source": how, "total": total, "schedule": sched}, open(os.path.join(out_dir, "schedule.json"), "w"), indent=2)
    return sched, total, how


# ---------- captions ----------
def wrap(words):
    """Best 1-2 line split of `words` within MAX_CHARS, or None if it doesn't fit."""
    text = " ".join(words)
    if len(text) <= MAX_CHARS:
        return [text]
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if len(a) <= MAX_CHARS and len(b) <= MAX_CHARS:
            score = abs(len(a) - len(b)) - (12 if re.search(r"[,:;]$", a) else 0)  # balanced, prefer breaking after punctuation
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best and best[1]


def lines_for(words):
    """wrap(), but a cue made of two sentences breaks between them."""
    text = " ".join(words)
    parts = re.split(r"(?<=[.?!])\s+", text)
    if len(text) > MAX_CHARS and len(parts) == 2 and all(len(x) <= MAX_CHARS for x in parts):
        return parts
    return wrap(words)


def chunk(words):
    """Split words into cues of <= MAX_LINES x MAX_CHARS, cutting at sentence/clause ends where possible."""
    if wrap(words):
        return [words]
    best = None
    for i in range(1, len(words)):
        if not wrap(words[:i]):
            break
        rest = chunk(words[i:])
        pen = 0 if re.search(r"[.?!]$", words[i - 1]) else 1 if re.search(r"[,:;]$", words[i - 1]) else 3
        cost = (len(rest), pen)  # fewest cues, then cleanest break
        if best is None or cost < best[0]:
            best = (cost, [words[:i]] + rest)
    return best[1]


def build_cues(vo_lines, sched):
    cues = []
    for s in sched:
        text = vo_lines.get(s["id"])
        if not text:
            warn(f"no VO line for {s['id']} in vo.txt")
            continue
        sentences = re.split(r"(?<=[.?!])\s+", text.strip())
        groups = []
        for g in (g for sent in sentences for g in chunk(sent.split())):
            # Fold short sentences together ("Knicks games? Nothing there.") instead of flashing them one by one.
            if groups and len(wrap(groups[-1])) == 1 and len(wrap(g)) == 1 and \
                    (len(" ".join(groups[-1] + g)) <= MAX_CHARS or len(" ".join(groups[-1])) + len(" ".join(g)) <= 2 * MAX_CHARS):
                groups[-1] = groups[-1] + g
            else:
                groups.append(g)
        n = sum(len(g) for g in groups)
        t = s["voStart"]
        for g in groups:
            d = s["voDur"] * len(g) / n
            cues.append((t, t + d, lines_for(g)))
            t += d
    return cues


def ts(t, sep):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def write_captions(cues, out_dir):
    with open(os.path.join(out_dir, "captions.srt"), "w") as f:
        for i, (a, b, lines) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a, ',')} --> {ts(b, ',')}\n" + "\n".join(lines) + "\n\n")
    with open(os.path.join(out_dir, "captions.vtt"), "w") as f:
        f.write("WEBVTT\n\n")
        for i, (a, b, lines) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a, '.')} --> {ts(b, '.')}\n" + "\n".join(lines) + "\n\n")
    longest = max(len(l) for _, _, ls in cues for l in ls)
    cps = max(sum(len(l) for l in ls) / (b - a) for a, b, ls in cues)
    if cps > 25:
        warn(f"fastest caption reads at {cps:.1f} chars/s (> 25)")
    return {"cues": len(cues), "longest_line": longest, "max_lines": max(len(ls) for *_, ls in cues), "max_cps": round(cps, 1)}


# ---------- encodes ----------
def x264_2pass(src, dst, vf, kbps, akbps, tmp, extra=()):
    log = os.path.join(tmp, os.path.basename(dst) + ".log")
    common = ["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-pix_fmt", "yuv420p",
              "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.15)}k", "-bufsize", f"{kbps * 2}k", "-g", str(round(2 * probe(src)["fps"])), "-passlogfile", log, *extra]
    ff(*common, "-pass", "1", "-an", "-f", "mp4", os.devnull)
    ff(*common, "-pass", "2", "-c:a", "aac", "-b:a", f"{akbps}k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", dst)


def master(src, dst, lufs, tmp):
    p = probe(src)
    vcopy = p["vcodec"] == "h264" and p["pix_fmt"] == "yuv420p"
    vargs = ["-c:v", "copy"] if vcopy else ["-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p"]
    if not vcopy:
        warn(f"master video is {p['vcodec']}/{p['pix_fmt']}; re-encoded to h264/yuv420p")
    if abs(lufs["I"] - TARGET_LUFS) <= LUFS_TOL:
        ff("-i", src, "-map", "0:v:0", "-map", "0:a:0", *vargs, "-c:a", "copy", "-movflags", "+faststart", dst)
        return "pass-through"
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a:0", "-af",
         f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture=True)).group(0))
    af = (f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    ff("-i", src, "-map", "0:v:0", "-map", "0:a:0", *vargs, "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
       "-movflags", "+faststart", dst)
    warn(f"loudness {lufs['I']:.1f} LUFS was > {LUFS_TOL} LU off target; audio re-mastered to {TARGET_LUFS}")
    return "re-mastered audio (loudnorm 2-pass)"


def teaser(src, dst, sched, root, tmp):
    """Hook (S1) -> hedge card (S11) -> DECLINED (S12, last sentence) -> logo (S16 with the full tagline), crossfaded,
    ending in a fade to black. Inner cuts land in VO pauses so no word is clipped; the logo hold absorbs the slack."""
    fps = probe(src)["fps"]
    by = {s["id"]: s for s in sched}

    def pauses(s):
        """Middles of the VO pauses inside a scene, from its own VO clip (music and sound cues fill the gaps in the mix)."""
        clip = os.path.join(root, s.get("file") or "")
        sil = silences(clip, noise="-35dB", d=0.1) if os.path.isfile(clip) else []
        return [s["voStart"] + (a + b) / 2 for a, b in sil if 0.3 < a and b < s["voDur"] - 0.3]

    def pause_near(s, frac):
        want = s["voStart"] + frac * s["voDur"]
        return min(pauses(s), key=lambda g: abs(g - want), default=want)

    s1, s10, s11, s16 = by["S1"], by["S11"], by["S12"], by["S16"]   # hedge card, decline (after the S4 principles card)
    vo_end = lambda s: s["voStart"] + s["voDur"]
    hook = (s1["start"], min(s1["start"] + s1["dur"], vo_end(s1) + XFADE))  # "Rain on a Saturday empties the shop."
    decline = (pause_near(s11, 0.68) - 0.1, min(s11["start"] + s11["dur"], vo_end(s11) + 0.6))  # "So Offset says no..." + stamp
    logo_min, logo_max = vo_end(s16) + 1.0 - s16["start"], s16["dur"]  # always the whole tagline; the end fade if it fits
    fixed = (hook[1] - hook[0]) + (decline[1] - decline[0]) - 3 * XFADE
    # Hedge card: run to the latest VO pause that still leaves room for the logo ("...cover the measured loss").
    ends = sorted(g + 0.15 for g in pauses(s10)) or [vo_end(s10)]
    fit = [e for e in ends if fixed + (e - s10["start"]) + logo_min <= TEASER_LEN + 0.05]
    hedge = (s10["start"], fit[-1] if fit else ends[0])
    logo = (s16["start"], s16["start"] + min(logo_max, max(logo_min, TEASER_LEN - fixed - (hedge[1] - hedge[0]))))
    segs = [hook, hedge, decline, logo]
    inputs, fc, off = [], [], 0.0
    for i, (a, b) in enumerate(segs):
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src]
        fc.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={fps:g}[v{i}];[{i}:a]asetpts=PTS-STARTPTS,aresample=48000[a{i}]")
    pv, pa = "v0", "a0"
    for i in range(1, 4):
        off += (segs[i - 1][1] - segs[i - 1][0]) - XFADE
        fc.append(f"[{pv}][v{i}]xfade=transition=fade:duration={XFADE}:offset={off:.3f}[vx{i}];"
                  f"[{pa}][a{i}]acrossfade=d={XFADE}:c1=tri:c2=tri[ax{i}]")
        pv, pa = f"vx{i}", f"ax{i}"
    total = off + segs[3][1] - segs[3][0]
    fc.append(f"[{pv}]fade=t=out:st={total - 0.6:.3f}:d=0.6[vout];[{pa}]afade=t=out:st={total - 0.6:.3f}:d=0.6[aout]")
    ff(*inputs, "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-crf", "18",
       "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", dst)
    return [{"from": round(a, 2), "to": round(b, 2)} for a, b in segs]


def font():
    for f in ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Menlo.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(f):
            return f


def contact_sheet(src, dst, dur, fps, every=3, cols=6):
    step = round(every * fps)
    n = int(round(dur * fps) - 1) // step + 1
    rows = math.ceil(n / cols)
    label = ""
    if font() and "drawtext" in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout:
        label = (f",drawtext=fontfile='{font()}':text='%{{pts\\:hms}}':x=8:y=h-th-8:fontsize=18:fontcolor=white:"
                 "box=1:boxcolor=black@0.6:boxborderw=4")
    ff("-i", src, "-vf", f"select='not(mod(n\\,{step}))',scale=384:-2{label},tile={cols}x{rows}:padding=4:margin=4:color=0x0f1a14",
       "-fps_mode", "vfr", "-frames:v", "1", "-update", "1", dst)
    return n


def poster(root, src, dst, t, tmp):
    """A clean still from the page itself (record.mjs --stills); falls back to the master frame."""
    r = subprocess.run(["node", os.path.join(root, "record.mjs"), "--stills", f"{t:.2f}", "--out", tmp],
                       capture_output=True, text=True, cwd=root)
    png = os.path.join(tmp, f"t{t:06.2f}.png")  # record.mjs's naming
    if r.returncode == 0 and os.path.exists(png):
        shutil.copyfile(png, dst)
        return "record.mjs --stills"
    warn(f"record.mjs --stills failed ({r.returncode}); poster taken from the master instead")
    ff("-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-update", "1", dst)
    return "master frame"


# ---------- QC ----------
def first_frame(src):
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", src, "-frames:v", "1", "-vf", "scale=64:36",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    avg = tuple(round(sum(p[c] for p in px) / len(px)) for c in range(3))
    near_bd = min(max(abs(a - b) for a, b in zip(avg, bd)) for bd in BACKDROP) <= 14
    black = max(avg) <= 6
    return {"avg_rgb": "#%02x%02x%02x" % avg, "black": black, "backdrop": near_bd}


def black_runs(src):
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-vf", "blackdetect=d=0.05:pix_th=0.02:pic_th=0.98",
               "-an", "-f", "null", "-"], capture=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", out)]


def gray(args, w=480, h=270, vf=True):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, *(["-vf", f"scale={w}:{h}"] if vf else []), "-pix_fmt", "gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)


def scene_timing(root, src, sched, fps, tmp, spread=3):
    """Video side: render page stills just after a few scene starts (mid-crossfade, where every frame differs)
    and find which master frame matches best. Offset 0 means the picture sits exactly on the schedule."""
    import numpy as np
    step = 0.05 if abs(fps * 0.05 - round(fps * 0.05)) < 1e-6 else 1 / fps  # 2-decimal times that land on frames
    picks = sched[1:: max(1, len(sched) // 5)]
    times = [round(round((s["start"] + 0.2) / step) * step, 2) for s in picks]
    d = os.path.join(tmp, "timing")
    r = subprocess.run(["node", os.path.join(root, "record.mjs"), "--stills", ",".join(f"{t:.2f}" for t in times), "--out", d],
                       capture_output=True, text=True, cwd=root)
    if r.returncode != 0:
        warn(f"scene timing check skipped: record.mjs --stills failed ({r.returncode})")
        return []
    idx = sorted({round(t * fps) + k for t in times for k in range(-spread, spread + 1)})
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    frames = dict(zip(idx, gray(["-i", src, "-fps_mode", "vfr", "-vf", f"select='{sel}',scale=480:270"], vf=False)))
    res = []
    for s, t in zip(picks, times):
        still = gray(["-i", os.path.join(d, f"t{t:06.2f}.png")])[0]
        n0 = round(t * fps)
        mse = {k: float(np.mean((frames[n0 + k] - still) ** 2)) for k in range(-spread, spread + 1) if n0 + k in frames}
        best = min(mse, key=mse.get)
        psnr = 10 * math.log10(255 ** 2 / max(mse[best], 1e-6))
        res.append({"id": s["id"], "t": t, "best_offset_frames": best, "psnr": round(psnr, 1)})
    return res


def pcm(path, start=0.0, dur=None, rate=8000):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, start):.3f}"] + (["-t", f"{dur:.3f}"] if dur else []) +
                         ["-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def av_sync(src, sched, root, fps, rate=8000, search=0.5):
    """Find each VO clip in the master's audio by cross-correlation (works under music/SFX) and compare to its scheduled start."""
    import numpy as np
    res = []
    for s in sched:
        f = os.path.join(root, s.get("file") or "")
        if not os.path.isfile(f):
            continue
        clip = pcm(f, rate=rate)
        a0 = max(0.0, s["voStart"] - search)
        mix = pcm(src, a0, len(clip) / rate + 2 * search, rate)
        if len(mix) < len(clip) or not clip.any():
            res.append({"id": s["id"], "vo_start": round(s["voStart"], 3), "found": None, "off_ms": None, "ok": False})
            continue
        n = 1 << (len(mix) + len(clip)).bit_length()
        xc = np.fft.irfft(np.fft.rfft(mix, n) * np.conj(np.fft.rfft(clip, n)), n)[: len(mix) - len(clip) + 1]
        lag = int(np.argmax(xc))
        seg = mix[lag:lag + len(clip)]
        corr = float(np.dot(seg, clip) / (np.linalg.norm(seg) * np.linalg.norm(clip) + 1e-9))
        got = a0 + lag / rate
        res.append({"id": s["id"], "vo_start": round(s["voStart"], 3), "found": round(got, 4), "corr": round(corr, 2),
                    "off_ms": round((got - s["voStart"]) * 1000, 1), "ok": abs(got - s["voStart"]) <= 1 / fps and corr > 0.3})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--in", dest="src")
    ap.add_argument("--out")
    ap.add_argument("--poster-time", type=float, help="seconds into the video (default: logo end card, 1.5 s before the end)")
    ap.add_argument("--skip-encodes", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    src = os.path.abspath(a.src or os.path.join(root, "out", "offset-product.mp4"))
    out = os.path.abspath(a.out or os.path.join(root, "out", "deliver"))
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="finish-")
    qc = {"input": src}

    print(f"input  {src}")
    p = probe(src)
    qc["input_probe"] = p
    fps = p["fps"]
    print(f"  {p['width']}x{p['height']} {p['fps']:.2f}fps {p['vcodec']}/{p['pix_fmt']} {p['duration']:.2f}s; audio {p['acodec']} "
          f"{p['sample_rate']} Hz x{p['channels']}")
    if p["sample_rate"] and p["sample_rate"] < 44100:
        warn(f"master audio is {p['sample_rate']} Hz (TTS rate); web/720p/teaser are resampled to 48 kHz stereo")
    if abs(p["v_start"] - (p["a_start"] or 0)) > 0.001:
        warn(f"stream start offset: video {p['v_start']}s vs audio {p['a_start']}s")

    sched, total, how = load_schedule(root, out)
    qc["schedule_source"], qc["schedule_total"] = how, total
    print(f"schedule  {len(sched)} scenes, {total:.2f}s, from {how}")
    if abs(p["duration"] - total) > 1 / fps + 0.05:
        warn(f"master runs {p['duration']:.2f}s but the schedule is {total:.2f}s (stale or partial render?)")
    if not 85 <= p["duration"] < 120:
        warn(f"duration {p['duration']:.2f}s is outside 85-120s")

    lufs = loudness(src)
    qc["loudness_input"] = lufs
    print(f"loudness  I {lufs['I']:.1f} LUFS  LRA {lufs['LRA']:.1f} LU  TP {lufs['TP']:.1f} dBTP")
    if lufs["TP"] > -1.0:
        warn(f"true peak {lufs['TP']:.1f} dBTP is above -1 dBTP")

    vo_lines = dict(re.findall(r"^(S\d+):\s*(.+)$", open(os.path.join(root, "notes", "vo.txt")).read(), re.M))
    cues = build_cues(vo_lines, sched)
    qc["captions"] = write_captions(cues, out)
    print(f"captions  {qc['captions']}")

    deliver = {}
    if not a.skip_encodes:
        m = os.path.join(out, "offset-product-1080p.mp4")
        qc["master_mode"] = master(src, m, lufs, tmp)
        deliver[m] = None
        print(f"master    {qc['master_mode']}")

        web = os.path.join(out, "offset-product-web.mp4")
        x264_2pass(m, web, "scale=1920:1080:flags=lanczos", WEB_KBPS, 192, tmp, ["-level", "4.1"])
        deliver[web] = None
        print("web       done")

        small = os.path.join(out, "offset-product-720p.mp4")
        dur = probe(m)["duration"]
        kbps = min(2500, int((SLACK_MAX_MB * 0.9 * 8e3) / dur) - 96)
        x264_2pass(m, small, "scale=1280:720:flags=lanczos", kbps, 96, tmp)
        if os.path.getsize(small) >= SLACK_MAX_MB * 1e6:
            warn("720p is over 15 MB")
        deliver[small] = None
        print(f"720p      done ({kbps} kbps video)")

        tz = os.path.join(out, "teaser-15s.mp4")
        qc["teaser_segments"] = teaser(m, tz, sched, root, tmp)
        deliver[tz] = None
        print(f"teaser    {qc['teaser_segments']}")

    pt = a.poster_time if a.poster_time is not None else sched[-1]["start"] + sched[-1]["dur"] - 1.5  # logo card, before the end fade
    qc["poster"] = {"time": round(pt, 2), "via": poster(root, src, os.path.join(out, "poster.png"), pt, tmp)}
    qc["contact_sheet_frames"] = contact_sheet(src, os.path.join(out, "contact-sheet.png"), p["duration"], fps)

    # QC
    qc["first_frame"] = ff0 = first_frame(src)
    print(f"first frame avg {ff0['avg_rgb']}: " + ("BLACK" if ff0["black"] else "backdrop (deliberate fade-in)" if ff0["backdrop"] else "content"))
    if ff0["black"]:
        warn("first frame is black")
    qc["black_runs"] = br = black_runs(src)
    br = [r for r in br if r[1] < p["duration"] - 1.5]  # the closing fade to black is deliberate
    if br:
        warn(f"black frames at {br}")
    qc["scene_timing"] = cuts = scene_timing(root, src, sched, fps, tmp)
    stale = [c for c in cuts if c["psnr"] < 30]  # the still doesn't look like any nearby frame: page changed since the render
    cuts = [c for c in cuts if c["psnr"] >= 30]
    if stale:
        warn(f"page stills don't match the master at {[c['id'] for c in stale]} (PSNR < 30): app.js changed after this render?")
    bad_cuts = [c for c in cuts if abs(c["best_offset_frames"]) > 1]
    offs = ", ".join(f"{c['id']} {c['best_offset_frames']:+d}" for c in cuts)
    print(f"scene timing {len(cuts) - len(bad_cuts)}/{len(cuts)} page stills match the master within 1 frame ({offs})")
    if bad_cuts:
        warn(f"picture off the schedule by > 1 frame: {[(c['id'], c['best_offset_frames']) for c in bad_cuts]}")
    qc["av_sync"] = sync = av_sync(src, sched, root, fps)
    bad = [s for s in sync if not s["ok"] and s["vo_start"] < p["duration"]]
    print(f"A/V sync  {sum(s['ok'] for s in sync)}/{len(sync)} VO clips found within 1 frame of scheduled start; "
          f"worst {max((abs(s['off_ms']) for s in sync if s['off_ms'] is not None), default=0)} ms")
    if bad:
        warn(f"VO onsets off by > 1 frame: {[(s['id'], s['off_ms']) for s in bad]}")

    print("\ndeliverables")
    for f in sorted(os.listdir(out)):
        path = os.path.join(out, f)
        line = f"  {f:28s} {os.path.getsize(path) / 1e6:7.2f} MB"
        if f.endswith(".mp4"):
            q, l = probe(path), loudness(path)
            qc.setdefault("outputs", {})[f] = {**q, "lufs": l}
            line += f"  {q['duration']:6.2f}s  {q['width']}x{q['height']}  {q['kbps']} kbps  {l['I']:.1f} LUFS  TP {l['TP']:.1f}"
        print(line)
    qc["issues"] = issues
    json.dump(qc, open(os.path.join(out, "qc.json"), "w"), indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    print("\nissues: " + ("none" if not issues else f"{len(issues)}"))
    for i in issues:
        print("  - " + i)


if __name__ == "__main__":
    main()
