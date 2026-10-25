#!/usr/bin/env python3
"""Write audio/sample_schedule.json from assets/vo/timing.json, laid out the way app.js does it
(scene = lead pad + VO + tail pad), with plausible SFX cues. For testing mix.py without the browser."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.dirname(HERE)
# Lead/tail pads per scene, copied from SCENES in app.js.
PADS = {"S1": (0.5, 0.7), "S2": (0.3, 0.5), "S3": (0.3, 0.5), "S4": (0.3, 0.4), "S5": (0.3, 0.4), "S6": (0.3, 0.5),
        "S7": (0.3, 0.5), "S8": (0.3, 0.5), "S9": (0.3, 0.5), "S10": (0.3, 0.5), "S11": (0.8, 1.3), "S12": (0.3, 0.8),
        "S13": (0.3, 0.5), "S14": (0.3, 0.5), "S15": (0.3, 0.6), "S16": (0.4, 2.4)}


def build():
    timing = json.load(open(os.path.join(VIDEO, "assets", "vo", "timing.json")))
    cur, vo, scenes, cues = 0.0, [], [], []
    for s in timing["scenes"]:
        lead, tail = PADS.get(s["scene"], (0.3, 0.5))
        dur = lead + s["duration"] + tail
        scenes.append({"id": s["scene"], "start": round(cur, 3), "dur": round(dur, 3)})
        vo.append({"scene": s["scene"], "file": s["file"], "start": round(cur + lead, 3)})
        sid = s["scene"]
        if sid not in ("S1", "S16"):
            cues.append({"t": round(max(0, cur - 0.2), 3), "type": "whoosh"})
        if sid == "S6":
            cues.append({"t": round(cur + lead + 1.6, 3), "type": "count"})
        if sid == "S7":
            cues.append({"t": round(cur + lead + 0.8, 3), "type": "count"})
            cues.append({"t": round(cur + lead + 3.2, 3), "type": "stamp"})
        if sid == "S11":
            cues.append({"t": round(cur + lead + s["duration"] - 0.6, 3), "type": "stamp"})
        if sid == "S12":
            cues.append({"t": round(cur + lead + 1.4, 3), "type": "tick"})
            cues.append({"t": round(cur + lead + 1.55, 3), "type": "stamp"})
        if sid == "S15":
            for i in range(3):
                cues.append({"t": round(cur + lead + 0.6 + i * 2.3, 3), "type": "tick"})
        if sid == "S16":
            cues.append({"t": round(cur + 0.1, 3), "type": "logo"})
        cur += dur
    return {"total": round(cur, 3), "scenes": scenes, "vo": vo, "cues": sorted(cues, key=lambda c: c["t"])}


if __name__ == "__main__":
    sch = build()
    out = os.path.join(HERE, "sample_schedule.json")
    json.dump(sch, open(out, "w"), indent=1)
    print(f"wrote {out}: total {sch['total']}s, {len(sch['vo'])} VO, {len(sch['cues'])} cues")
    print({s["id"]: s["start"] for s in sch["scenes"] if s["id"] in ("S4", "S11", "S12", "S16")})
