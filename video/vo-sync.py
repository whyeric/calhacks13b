#!/usr/bin/env python3
"""Re-sync scene timing to a human narration recording.

Usage: python video/vo-sync.py [recording] [--outdir video/assets/vo] [--method auto|whisper|silence]
       [--starts 0,3.91,...]   (hand-set scene starts in seconds; overrides --method)

Reads scene text from video/notes/vo.txt ("S1: ..." paragraphs), finds where each
scene starts in the recording, cuts per-scene clips, copies the recording to
<outdir>/full.m4a and rewrites <outdir>/timing.json with "source": "recorded".

Boundary finding: word timestamps from local openai-whisper (aligned to the script
with difflib, so ad-libs and small misreads are tolerated); falls back to ffmpeg
silencedetect, taking the N-1 longest pauses as scene breaks. Check the result: one long pause can be
detected as two, which pushes every later break off by one. Then pass the right starts with --starts.

Each scene also gets "lead" (speech onset after the scene start) and "len" (speech length), from
silencedetect inside the scene, so scenes time their animations to the speech, not to the pauses.
"""
import argparse, difflib, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VO_TXT = os.path.join(HERE, "notes", "vo.txt")
WHISPER_PY = os.environ.get("WHISPER_PY", sys.executable)  # a python with openai-whisper installed


def parse_scenes(path):
    text = open(path).read()
    out = [(m.group(1), " ".join(m.group(2).split()))
           for m in re.finditer(r"^(S\d+):\s*(.*?)(?=^S\d+:|\Z)", text, re.S | re.M)]
    if not out:
        sys.exit(f"no 'S1: ...' scenes found in {path}")
    return out


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path], text=True)
    return float(out.strip())


def whisper_words(rec):
    """Return [(word, start, end)] using openai-whisper, in-process or via WHISPER_PY."""
    code = ("import json,sys,whisper\n"
            "m=whisper.load_model('base')\n"
            "r=m.transcribe(sys.argv[1],word_timestamps=True,language='en')\n"
            "print(json.dumps([(w['word'],w['start'],w['end']) for s in r['segments'] for w in s['words']]))")
    py = sys.executable
    try:
        import whisper  # noqa: F401
    except ImportError:
        if not os.path.exists(WHISPER_PY):
            raise RuntimeError("openai-whisper not available")
        py = WHISPER_PY
    out = subprocess.check_output([py, "-c", code, rec], text=True, stderr=subprocess.DEVNULL)
    return json.loads(out.strip().splitlines()[-1])


def starts_from_whisper(rec, scenes):
    words = [(norm(w), s, e) for w, s, e in whisper_words(rec)]
    words = [x for x in words if x[0]]
    script, scene_first = [], []
    for _, body in scenes:
        scene_first.append(len(script))
        script += [t for t in map(norm, body.split()) if t]
    sm = difflib.SequenceMatcher(None, script, [w for w, _, _ in words], autojunk=False)
    s2t = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            s2t[a + k] = b + k
    if len(s2t) < 0.5 * len(script):
        raise RuntimeError(f"transcript matched only {len(s2t)}/{len(script)} script words")
    starts = [0.0]
    for i in range(1, len(scenes)):
        end = scene_first[i + 1] if i + 1 < len(scenes) else len(script)
        # first matched script word in this scene; back off by how many words were skipped
        hit = next((j for j in range(scene_first[i], end) if j in s2t), None)
        if hit is None:
            raise RuntimeError(f"could not locate {scenes[i][0]} in transcript")
        t_idx = max(0, s2t[hit] - (hit - scene_first[i]))
        t = words[t_idx][1]
        prev_end = words[t_idx - 1][2] if t_idx > 0 else 0.0
        starts.append(round(max(prev_end, t - 0.12), 3))  # lead-in, never before previous word
    return starts


def starts_from_silence(rec, n):
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", rec, "-af",
                          "silencedetect=noise=-35dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ss = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    se = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    gaps = [(e - s, s, e) for s, e in zip(ss, se) if s > 0.05]  # skip leading silence
    if len(gaps) < n - 1:
        raise RuntimeError(f"found {len(gaps)} pauses, need {n - 1}")
    breaks = sorted(gaps, reverse=True)[: n - 1]
    return [0.0] + sorted(round(e - 0.1, 3) for _, _, e in breaks)


def speech_bounds(rec, starts, total):
    """[(lead, len)] per scene: first and last speech (>= 0.2 s runs) inside each scene's range."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", rec, "-af", "silencedetect=noise=-38dB:d=0.12",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    ss = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    se = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    segs, prev = [], 0.0
    for s, e in zip(ss, se):
        if s - prev >= 0.2:
            segs.append((prev, s))
        prev = e
    if total - prev >= 0.2:
        segs.append((prev, total))
    out = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else total
        inside = [(max(x, a), min(y, b)) for x, y in segs if y > a and x < b and min(y, b) - max(x, a) >= 0.2]
        if not inside:
            out.append((0.0, round(b - a, 3)))
            continue
        out.append((round(inside[0][0] - a, 3), round(inside[-1][1] - inside[0][0], 3)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?")
    ap.add_argument("--outdir", default=os.path.join(HERE, "assets", "vo"))
    ap.add_argument("--method", choices=["auto", "whisper", "silence"], default="auto")
    ap.add_argument("--starts", help="comma-separated scene starts (s), one per scene in vo.txt")
    a = ap.parse_args()
    rec = a.recording or next((os.path.join(a.outdir, f"user.{x}") for x in ("m4a", "wav", "mp3")
                               if os.path.exists(os.path.join(a.outdir, f"user.{x}"))), None)
    if not rec or not os.path.exists(rec):
        sys.exit("no recording given and no user.m4a/.wav/.mp3 in outdir")
    scenes = parse_scenes(VO_TXT)
    os.makedirs(a.outdir, exist_ok=True)

    method = a.method
    if a.starts:
        starts = [float(x) for x in a.starts.split(",")]
        if len(starts) != len(scenes):
            sys.exit(f"--starts has {len(starts)} values, vo.txt has {len(scenes)} scenes")
        method = "manual"
    elif method in ("auto", "whisper"):
        try:
            starts = starts_from_whisper(rec, scenes)
            method = "whisper"
        except Exception as e:
            if a.method == "whisper":
                sys.exit(f"whisper failed: {e}")
            print(f"whisper unavailable or failed ({e}); using silencedetect", file=sys.stderr)
            method = "silence"
    if method == "silence":
        starts = starts_from_silence(rec, len(scenes))

    full = os.path.join(a.outdir, "full.m4a")
    if os.path.abspath(rec) != os.path.abspath(full):
        if rec.lower().endswith(".m4a"):
            shutil.copyfile(rec, full)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", rec, "-c:a", "aac",
                            "-b:a", "192k", full], check=True)
    total = round(duration(full), 3)

    rows = []
    bounds = speech_bounds(full, starts, total)
    for i, (name, _) in enumerate(scenes):
        end = starts[i + 1] if i + 1 < len(scenes) else total
        clip = os.path.join(a.outdir, f"{name}.m4a")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", full, "-ss", str(starts[i]),
                        "-to", str(end), "-c:a", "aac", "-b:a", "192k", clip], check=True)
        rows.append({"scene": name, "file": f"vo/{name}.m4a", "start": starts[i],
                     "duration": round(end - starts[i], 3), "lead": bounds[i][0], "len": bounds[i][1]})

    timing = {"source": "recorded", "method": method, "scenes": rows, "full": "vo/full.m4a",
              "total": total}
    json.dump(timing, open(os.path.join(a.outdir, "timing.json"), "w"), indent=2)
    for r in rows:
        print(f"{r['scene']:>4}  start {r['start']:7.2f}  dur {r['duration']:6.2f}  speech {r['lead']:5.2f}+{r['len']:.2f}")
    print(f"total {total:.2f}s via {method}")


if __name__ == "__main__":
    main()
