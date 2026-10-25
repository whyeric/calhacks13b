# Offset product video

A ~93 s product video with voiceover, built as a web page animated with [Motion](https://motion.dev) and rendered frame by frame to MP4.

**Watch:** `offset-product.mp4` in this folder (1920x1080, 60 fps).

## How it's made

| Part | Files |
|---|---|
| Script, narration, brand, on-screen values | `notes/script.md`, `notes/vo.txt`, `notes/brand.md`, `assets/verify.md` |
| Screenshots of the real app (offline demo) | `capture/run.sh` → `assets/shot-*.png`, `assets/shots.json` |
| Voiceover (AI placeholder, macOS `say`) | `assets/vo/` (`timing.json` drives all scene timing) |
| Player and scenes | `index.html`, `app.js` (engine), `lib.js` (helpers), `scenes/S01.js`–`S16.js` |
| Music and sound effects (synthesized) | `audio/music.py`, `audio/sfx.py`, `audio/mix.py` |
| Render | `record.mjs` |
| Deliverables (web/720p/teaser/captions/poster) | `finish/finish.sh` |

## Run it

Needs Node 22, ffmpeg and Python 3 with numpy/scipy. Playwright comes from `frontend/node_modules`.

```
cd video
python3 -m http.server 8123          # preview: open http://localhost:8123
python3 audio/music.py               # regenerate the music bed (gitignored)
node record.mjs --final              # full render -> out/offset-product.mp4 (about 20 min)
node record.mjs --stills 12,40       # quick stills -> out/scratch/
finish/finish.sh                     # deliverables -> out/deliver/
```

## Replacing the AI voiceover with a recording

`assets/vo/timing.json` is the single source of scene timing (`scene`, `start`, `duration`, `file`, plus `total` and `source`). The shipped track is AI TTS (`"source": "ai-tts"`, macOS `say`, voice Samantha).
To use your own narration: record it reading `notes/vo.txt` (pause briefly between scenes), save it as `assets/vo/user.m4a` (or `.wav`), then run `python3 video/vo-sync.py`.
That finds scene starts using local whisper word timestamps (falling back to the longest pauses via ffmpeg silencedetect, or force it with `--method silence`), copies the recording to `vo/full.m4a`, recuts `vo/S*.m4a`, and rewrites `timing.json` with `"source": "recorded"`.
