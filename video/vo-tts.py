#!/usr/bin/env python3
"""Placeholder AI voiceover from notes/vo.txt (macOS `say`), so scene timing works before a recording.

Usage: python3 video/vo-tts.py                 write assets/vo/S*.m4a, full.m4a and timing.json ("source": "ai-tts")
       python3 video/vo-tts.py --onsets S9 S12  print word onsets (s into each clip) for those scenes

Format matches the shipped track: voice Samantha at 185 wpm, AAC 22.05 kHz mono, about 32 kb/s, clips joined
with 0.35 s gaps in full.m4a. Durations are read from the uncompressed `say` output (AAC adds priming).
Word onsets: whisper isn't required. The onset of word i is the length of `say` reading words 0..i-1,
which is close enough to place captions (check with record.mjs --stills).
"""
import argparse, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VO_TXT = os.path.join(HERE, "notes", "vo.txt")
OUT = os.path.join(HERE, "assets", "vo")
VOICE, RATE, GAP = "Samantha", 185, 0.35


def scenes():
    text = open(VO_TXT).read()
    return [(m.group(1), " ".join(m.group(2).split()))
            for m in re.finditer(r"^(S\d+):\s*(.*?)(?=^S\d+:|\Z)", text, re.S | re.M)]


def say(text, path):
    subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", path, text], check=True)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path], text=True)
    return float(out.strip())


def aac(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ar", "22050", "-ac", "1",
                    "-c:a", "aac", "-b:a", "32k", dst], check=True)


def onsets(text, tmp):
    words, out = text.split(), []
    for i, w in enumerate(words):
        if i == 0:
            out.append((w, 0.0)); continue
        p = os.path.join(tmp, "prefix.aiff"); say(" ".join(words[:i]), p)
        out.append((w, round(duration(p), 2)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onsets", nargs="*", help="scene ids to print word onsets for (default: write clips)")
    a = ap.parse_args()
    sc = scenes()
    with tempfile.TemporaryDirectory() as tmp:
        if a.onsets is not None:
            for sid, text in sc:
                if not a.onsets or sid in a.onsets:
                    print(sid, " ".join(f"{w}@{t:.2f}" for w, t in onsets(text, tmp)))
            return
        rows, t, parts = [], 0.0, []
        for sid, text in sc:
            raw = os.path.join(tmp, f"{sid}.aiff"); say(text, raw)
            d = round(duration(raw), 3)
            aac(raw, os.path.join(OUT, f"{sid}.m4a"))
            rows.append({"scene": sid, "file": f"vo/{sid}.m4a", "duration": d, "start": round(t, 3)})
            parts.append(raw); t += d + GAP
        # full.m4a: the clips with GAP seconds of silence between them.
        gap = os.path.join(tmp, "gap.aiff")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                        "-t", str(GAP), gap], check=True)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for i, p in enumerate(parts):
                f.write(f"file '{p}'\n")
                if i < len(parts) - 1:
                    f.write(f"file '{gap}'\n")
        joined = os.path.join(tmp, "full.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-ar", "22050", "-ac", "1", joined], check=True)
        aac(joined, os.path.join(OUT, "full.m4a"))
        total = round(rows[-1]["start"] + rows[-1]["duration"], 3)
    # Drop clips for scenes that no longer exist.
    keep = {r["file"].split("/")[1] for r in rows}
    for f in os.listdir(OUT):
        if re.fullmatch(r"S\d+\.m4a", f) and f not in keep:
            os.remove(os.path.join(OUT, f))
    timing = {"source": "ai-tts", "voice": VOICE, "rate_wpm": RATE, "gap": GAP, "scenes": rows,
              "full": "vo/full.m4a", "total": total}
    json.dump(timing, open(os.path.join(OUT, "timing.json"), "w"), indent=2)
    for r in rows:
        print(f"{r['scene']:>4}  start {r['start']:7.2f}  dur {r['duration']:6.2f}")
    print(f"total VO {total:.2f}s")


if __name__ == "__main__":
    sys.exit(main())
