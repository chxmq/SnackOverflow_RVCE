"""Render the narrated demo video: slides + dashboard captures + Kokoro TTS -> MP4.

Run with the Kokoro venv:  ~/hackathons/.tts/.venv/bin/python deliverables/make_video.py
Expects deliverables/GlycoTwin_Presentation.pdf and figures/dash_*.png to exist.
"""
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from narration import FRAMES  # noqa: E402

OUT = os.path.join(HERE, "video")
os.makedirs(OUT, exist_ok=True)
VOICE = os.environ.get("VOICE", "hm_omega")
SPEED = float(os.environ.get("SPEED", "1.0"))


def run(*a):
    subprocess.run(a, check=True)


def slides():
    pdf = os.path.join(HERE, "GlycoTwin_Presentation.pdf")
    run("pdftoppm", "-png", "-scale-to-x", "1920", "-scale-to-y", "1080", pdf, os.path.join(OUT, "slide"))
    # pdftoppm names slide-01.png ... ; normalise to slideNN.png
    for f in os.listdir(OUT):
        if f.startswith("slide-") and f.endswith(".png"):
            os.replace(os.path.join(OUT, f), os.path.join(OUT, "slide" + f[6:].zfill(6)))


def image_for(key):
    if key.startswith("slide"):
        return os.path.join(OUT, f"{key}.png")
    return os.path.join(ROOT, "figures", f"{key}.png")


def tts(only=None):
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")
    durs = {}
    for key, txt in FRAMES:
        wav = os.path.join(OUT, f"{key}.wav")
        if only and key not in only:
            continue
        if not os.path.exists(wav):
            audio = np.concatenate([a for _, _, a in pipe(txt, voice=VOICE, speed=SPEED, split_pattern=r"\n+")])
            pad = np.zeros(int(24000 * 0.6), dtype=audio.dtype)
            sf.write(wav, np.concatenate([pad, audio, pad]), 24000)
        durs[key] = sf.info(wav).duration
        print(key, round(durs[key], 1), flush=True)
    return durs


def render():
    parts = []
    for key, _ in FRAMES:
        img, wav = image_for(key), os.path.join(OUT, f"{key}.wav")
        mp4 = os.path.join(OUT, f"{key}.mp4")
        run("ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "2", "-i", img, "-i", wav,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,format=yuv420p",
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-r", "2",
            "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-af", "loudnorm=I=-16:TP=-1.5", "-shortest", mp4)
        parts.append(mp4)
    lst = os.path.join(OUT, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    final = os.path.join(HERE, "GlycoTwin_Demo.mp4")
    run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
        "-movflags", "+faststart", final)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", final],
                               capture_output=True, text=True).stdout)
    print("video", final, f"{dur / 60:.1f} min")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("tts", "all"):
        json.dump(tts(), open(os.path.join(OUT, "durations.json"), "w"), indent=1)
    if step in ("slides", "all"):
        slides()
    if step in ("render", "all"):
        render()
