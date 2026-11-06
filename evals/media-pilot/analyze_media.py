"""Measure pilot media: frame sheets, last frame and audio energy windows.

Needs ffmpeg/ffprobe on PATH and Pillow. Writes evidence next to the run:
  analysis/<id>.json, analysis/<id>-sheet.jpg, media/<id>-last.png
Audio results are energy measurements only; they do not identify words.
"""
from __future__ import annotations

import argparse
import array
import json
import math
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels",
                             "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def grab(path, second, target):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{second:.3f}", "-i", str(path),
                    "-frames:v", "1", str(target)], check=True)


def last_frame(path, target):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.5", "-i", str(path),
                    "-update", "1", "-q:v", "1", str(target)], check=True)


def sheet(images, labels, target, columns=4, width=480):
    tiles = []
    for image_path in images:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            image.thumbnail((width, width * 2))
            tiles.append(image.copy())
    rows = math.ceil(len(tiles) / columns)
    cell_h = max(t.height for t in tiles) + 24
    canvas = Image.new("RGB", (columns * width, rows * cell_h), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (tile, label) in enumerate(zip(tiles, labels)):
        x, y = (index % columns) * width, (index // columns) * cell_h
        canvas.paste(tile, (x + (width - tile.width) // 2, y + 22))
        draw.text((x + 6, y + 4), label, fill="black")
    canvas.save(target, quality=82)


def audio_windows(path, window=0.1):
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                             "-f", "s16le", "-"], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        return {"has_audio": False, "detail": result.stderr.decode("utf-8", "replace")[:300]}
    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    size = int(16000 * window)
    levels = []
    for start in range(0, len(samples), size):
        chunk = samples[start:start + size]
        if not chunk:
            break
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        levels.append(round(20 * math.log10(rms / 32768) if rms > 0 else -120.0, 1))
    ordered = sorted(levels)
    floor = ordered[len(ordered) // 10]
    threshold = max(floor + 12, -45)
    loud, start = [], None
    for index, level in enumerate(levels + [-120.0]):
        if level >= threshold and start is None:
            start = index
        elif level < threshold and start is not None:
            if index - start >= 2:
                loud.append([round(start * window, 1), round(index * window, 1)])
            start = None
    return {"has_audio": True, "window_s": window, "floor_dbfs_p10": floor, "threshold_dbfs": threshold,
            "peak_dbfs": max(levels), "loud_intervals_s": loud,
            "levels_dbfs_per_window": levels}


def analyze_video(run_dir, record_id, step):
    video = next((run_dir / "media").glob(f"{record_id}-1.mp4"))
    info = probe(video)
    duration = float(info["format"]["duration"])
    frames_dir = run_dir / "analysis" / "frames" / record_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    times = [round(t * step, 2) for t in range(int(duration / step) + 1) if t * step < duration - 0.05]
    paths = []
    for second in times:
        target = frames_dir / f"t{second:05.1f}.jpg"
        grab(video, second, target)
        paths.append(target)
    last = run_dir / "media" / f"{record_id}-last.png"
    last_frame(video, last)
    paths.append(last)
    labels = [f"{record_id} t={t:.1f}s" for t in times] + [f"{record_id} last"]
    sheet(paths, labels, run_dir / "analysis" / f"{record_id}-sheet.jpg")
    result = {"id": record_id, "file": str(video.relative_to(run_dir)), "probe": info, "duration_s": duration,
              "frame_times_s": times, "last_frame": str(last.relative_to(run_dir)), "audio": audio_windows(video)}
    (run_dir / "analysis" / f"{record_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                           encoding="utf-8")
    summary = {k: result[k] for k in ("id", "duration_s")}
    summary["audio_loud_intervals_s"] = result["audio"].get("loud_intervals_s")
    print(json.dumps(summary, ensure_ascii=False))


def analyze_images(run_dir, record_ids, name):
    paths, labels = [], []
    for record_id in record_ids:
        for path in sorted((run_dir / "media").glob(f"{record_id}-*.png")) + sorted((run_dir / "media").glob(f"{record_id}-*.jp*g")):
            paths.append(path)
            labels.append(path.stem)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    sheet(paths, labels, run_dir / "analysis" / f"{name}-sheet.jpg", columns=min(3, len(paths)), width=640)
    print(json.dumps({"sheet": f"analysis/{name}-sheet.jpg", "images": [str(p.name) for p in paths]}))


def frame_strip(run_dir, record_id, start, end, step):
    video = next((run_dir / "media").glob(f"{record_id}-1.mp4"))
    frames_dir = run_dir / "analysis" / "frames" / record_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths, labels, second = [], [], start
    while second <= end + 1e-6:
        target = frames_dir / f"dense-{second:06.2f}.jpg"
        grab(video, second, target)
        paths.append(target)
        labels.append(f"{record_id} t={second:.2f}s")
        second = round(second + step, 3)
    name = f"{record_id}-dense-{start:g}-{end:g}"
    sheet(paths, labels, run_dir / "analysis" / f"{name}.jpg", columns=4, width=400)
    print(json.dumps({"sheet": f"analysis/{name}.jpg", "frames": len(paths)}))


def spectrum(run_dir, record_id):
    video = next((run_dir / "media").glob(f"{record_id}-1.mp4"))
    target = run_dir / "analysis" / f"{record_id}-spectrum.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-lavfi",
                    "showspectrumpic=s=1200x400:legend=1:scale=log:fscale=lin:stop=8000", str(target)], check=True)
    print(json.dumps({"spectrum": f"analysis/{record_id}-spectrum.jpg"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("video")
    v.add_argument("id")
    v.add_argument("--step", type=float, default=1.0)
    i = sub.add_parser("images")
    i.add_argument("--name", required=True)
    i.add_argument("ids", nargs="+")
    f = sub.add_parser("frames")
    f.add_argument("id")
    f.add_argument("--start", type=float, required=True)
    f.add_argument("--end", type=float, required=True)
    f.add_argument("--step", type=float, default=0.25)
    s = sub.add_parser("spectrum")
    s.add_argument("id")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    if args.command == "video":
        analyze_video(run_dir, args.id, args.step)
    elif args.command == "images":
        analyze_images(run_dir, args.ids, args.name)
    elif args.command == "frames":
        frame_strip(run_dir, args.id, args.start, args.end, args.step)
    else:
        spectrum(run_dir, args.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
