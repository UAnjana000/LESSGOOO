"""Generate the SYNTHETIC fixture collection used by tests and the local demo.

Every text below was written for this repository. None of it is a work of, or attributed to,
Dr. B. R. Ambedkar. The "author" (A. N. Example) and the town (Samarpur) are fictional.
Run inside the api container (needs Pillow+raqm, Noto Devanagari fonts, espeak-ng, ffmpeg):

    docker compose run --rm api python /fixtures/generate_fixtures.py --out /fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import subprocess
import tempfile
import textwrap
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

LABEL_EN = "[Synthetic fixture page - not a historical document]"
LABEL_HI = "[कृत्रिम नमूना पृष्ठ - ऐतिहासिक दस्तावेज़ नहीं]"
LABEL_MR = "[कृत्रिम नमुना पान - ऐतिहासिक दस्तऐवज नाही]"

TEXTS: dict[str, list[str]] = {
    "essay": [
        "On Public Reading Rooms\n\n"
        "A reading room is a promise made by a town to every person who walks through its door. The promise "
        "is simple: knowledge kept on a shelf belongs to anyone who can reach for it. In the town of Samarpur "
        "the first reading room opened in 1921 in two rented rooms above a grain shop. It held four hundred "
        "books, three newspapers and a single lamp. The committee that ran it wrote in its first report that "
        "the doors must open before the mills began their shifts and close after they ended, so that workers "
        "could read on the way to work and on the way home.",
        "The committee kept a register of every borrower. By 1925 the register listed more than eleven hundred "
        "names, and nearly half of the borrowers had signed with a thumb impression when they first joined. "
        "The committee organised evening classes so that members could learn to read the books they borrowed. "
        "The report of 1926 says that a reading room should be judged not by the number of books on its shelves "
        "but by the number of people who leave able to read a book they could not read before.",
    ],
    "lecture_clean": [
        f"{LABEL_EN}\nLecture on Education and Work\n\n"
        "Friends, education is not a gift that one class hands to another. It is a tool that every worker "
        "must hold in his own hands. A school that closes its doors at the hour when the labourer is free has "
        "not been built for the labourer. I ask this assembly to support night schools in every ward of the "
        "city, with lamps paid for by the municipality and teachers chosen by the families who send their "
        "children. When a mother can read the notice on the mill gate, no one can deceive her about her wages.",
    ],
    "lecture_degraded": [
        f"{LABEL_EN}\nLecture on Water and the Common Tank\n\n"
        "The common tank in the centre of the village was dug by the labour of all its families, yet for many "
        "years only some families were allowed to draw water from it. A public resource that is closed to part "
        "of the public is not a public resource at all. The village council must publish the rules of the tank "
        "on a board beside the steps, and any person refused water must be able to complain to the council "
        "within one week.",
    ],
    "proceedings": [
        f"{LABEL_EN}\nProceedings of the Samarpur Civic Assembly\nSitting 1\n\n"
        "The Assembly met at eleven o'clock. The Chairman read the motion on the establishment of a municipal "
        "library board. Member Rao said that the board should include at least two members elected by the users "
        "of the reading rooms. Member Desai asked how the board would be funded and whether a small fee would "
        "be charged.",
        f"{LABEL_EN}\n"
        "Member Rao replied that no fee should be charged for reading within the rooms, because a fee at the "
        "door keeps out precisely those who most need to enter. The motion was put to the vote and carried by "
        "twenty-one votes to six. The Assembly adjourned at one o'clock.",
    ],
    "hindi": [
        f"{LABEL_HI}\nसार्वजनिक वाचनालय के बारे में एक पर्चा\n\n"
        "हर शहर में एक सार्वजनिक वाचनालय होना चाहिए जिसके दरवाज़े सभी के लिए खुले हों। पुस्तकें केवल "
        "अलमारियों में रखने के लिए नहीं होतीं, वे पढ़ने के लिए होती हैं। रात्रि पाठशालाएँ मज़दूरों को पढ़ना और "
        "लिखना सिखाती हैं। जब एक माँ मिल के दरवाज़े पर लगी सूचना पढ़ सकती है, तब कोई उसे उसकी मज़दूरी के "
        "बारे में धोखा नहीं दे सकता।",
    ],
    "marathi": [
        f"{LABEL_MR}\nसार्वजनिक पाणवठ्याविषयी निवेदन\n\n"
        "गावातील सार्वजनिक तलाव सर्व कुटुंबांच्या श्रमाने खोदला गेला. तरीही अनेक वर्षे काही कुटुंबांनाच "
        "त्यातून पाणी घेण्याची परवानगी होती. जे सार्वजनिक साधन सर्वांसाठी खुले नाही, ते खरे सार्वजनिक साधन "
        "नाही. ग्रामपंचायतीने तलावाचे नियम पायऱ्यांजवळ फलकावर लावावेत आणि पाणी नाकारलेल्या व्यक्तीला एका "
        "आठवड्यात तक्रार करता यावी.",
    ],
    "manuscript": [
        "Note on the library board, 3 March 1927.\n"
        "Ask the committee to keep the rooms open until ten at night during the harvest months. "
        "Write to the municipality about the lamp oil. Bring the register to the next meeting.",
    ],
    "restricted": [
        "Draft memorandum (synthetic fixture, rights unknown)\n\n"
        "This draft memorandum is held with unknown display rights. It must never be shown to visitors until "
        "the rights register allows display. It mentions a secret reading room budget of forty rupees.",
    ],
    "online_only": [
        "Synthetic newspaper report on the library board\n\n"
        "The Samarpur Gazette reported that the new library board held its first meeting on 12 April 1927 and "
        "resolved to open three branch reading rooms in the mill districts. The report is shown online only.",
    ],
}

AUDIO_SEGMENTS = [
    "This is a synthetic recording made for testing the archive. It is not a historical recording.",
    "The reading room opened in two rented rooms above a grain shop.",
    "Night schools taught members to read the books they borrowed.",
    "A fee at the door keeps out those who most need to enter.",
]

PHOTO_CAPTION = ("Readers at a reading room in the fictional town of Samarpur, around 1925. "
                 "Synthetic illustration generated for testing; not a historical photograph.")

FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
FONT_SANS_OBL = "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf"
FONT_DEVA = "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Regular.ttf"
PAGE = (1654, 2339)  # A4 at 200 dpi


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    layout = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    return ImageFont.truetype(path, size, layout_engine=layout)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, width) or [""])
    return lines


def render_page(text: str, font_path: str, size: int = 38, wrap: int = 62, lang: str = "en",
                page_size: tuple[int, int] = PAGE) -> Image.Image:
    img = Image.new("L", page_size, 250)
    d = ImageDraw.Draw(img)
    font = _font(font_path, size)
    y = 170
    for line in _wrap(text, wrap):
        d.text((150, y), line, font=font, fill=15, language=lang if features.check("raqm") else None)
        y += int(size * (1.9 if lang != "en" else 1.55))
    return img


def degrade(img: Image.Image, seed: int = 3) -> Image.Image:
    rng = random.Random(seed)
    im = img.rotate(2.2, fillcolor=235, expand=False)
    im = im.filter(ImageFilter.GaussianBlur(3.2))
    px = im.load()
    w, h = im.size
    for _ in range(int(w * h * 0.06)):
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = rng.choice((30, 200, 120))
    im = im.point(lambda v: int(110 + v * 0.35))  # low contrast, grey paper
    d = ImageDraw.Draw(im)
    for _ in range(9):  # water stains
        x, y, r = rng.randrange(w), rng.randrange(h), rng.randrange(80, 260)
        d.ellipse((x - r, y - r, x + r, y + r), outline=150, width=rng.randrange(6, 20))
    return im.resize((w // 2, h // 2)).resize((w, h))


def render_spread(left: str, right: str) -> Image.Image:
    a, b = render_page(left, FONT_SERIF), render_page(right, FONT_SERIF)
    spread = Image.new("L", (PAGE[0] * 2 + 60, PAGE[1]), 250)
    spread.paste(a, (0, 0))
    spread.paste(b, (PAGE[0] + 60, 0))
    d = ImageDraw.Draw(spread)
    d.rectangle((PAGE[0], 0, PAGE[0] + 60, PAGE[1]), fill=40)  # binding gutter
    return spread


def render_handwriting(text: str, seed: int = 11) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("L", PAGE, 238)
    font = _font(FONT_SANS_OBL, 46)
    x, y = 140, 220
    for line in _wrap(text, 44):
        x = 140 + rng.randint(-10, 10)
        for word in line.split():
            layer = Image.new("L", (int(font.getlength(word)) + 30, 90), 0)
            ImageDraw.Draw(layer).text((15, 15), word, font=font, fill=255)
            layer = layer.rotate(rng.uniform(-4, 4), resample=Image.BICUBIC)
            img.paste(Image.new("L", layer.size, 45), (x, y + rng.randint(-4, 4)), layer)
            x += int(font.getlength(word)) + rng.randint(22, 40)
        y += 110 + rng.randint(-6, 10)
    return img.filter(ImageFilter.GaussianBlur(0.8))


def render_photo(seed: int = 5) -> Image.Image:
    rng = random.Random(seed)
    w, h = 1600, 1100
    img = Image.new("RGB", (w, h), (120, 96, 70))
    d = ImageDraw.Draw(img)
    for i in range(h):  # warm vertical light gradient
        c = int(90 + 70 * (1 - abs(i - h * 0.35) / h))
        d.line((0, i, w, i), fill=(c + 30, c + 12, c - 12))
    for sx in range(60, w - 60, 250):  # bookshelves
        d.rectangle((sx, 90, sx + 210, 560), fill=(70, 48, 30))
        for row in range(5):
            bx = sx + 8
            while bx < sx + 200:
                bw = rng.randint(12, 26)
                shade = rng.randint(60, 150)
                d.rectangle((bx, 100 + row * 92, bx + bw, 180 + row * 92), fill=(shade, shade - 20, shade - 40))
                bx += bw + 3
    d.rectangle((150, 760, 1450, 800), fill=(80, 55, 35))  # table
    for px in range(260, 1400, 230):  # seated readers (silhouettes)
        d.ellipse((px, 560, px + 90, 650), fill=(45, 35, 28))
        d.rounded_rectangle((px - 25, 640, px + 115, 770), 30, fill=(55, 42, 32))
        d.rectangle((px - 10, 740, px + 100, 760), fill=(225, 215, 190))
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    noise = Image.effect_noise((w, h), 22).convert("L")
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.12)
    d = ImageDraw.Draw(img)
    d.text((30, h - 60), "SYNTHETIC FIXTURE ILLUSTRATION - NOT A HISTORICAL PHOTOGRAPH",
           font=_font(FONT_SERIF, 30), fill=(250, 240, 220))
    return img


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """Minimal PDF with a real text layer (Helvetica, WinAnsi) - no external PDF library needed."""
    objs: list[bytes] = []
    kids = []
    font_id = 3
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"")  # pages placeholder
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for text in pages:
        lines = _wrap(text, 88)
        ops = ["BT", "/F1 11 Tf", "14 TL", "56 790 Td"]
        for ln in lines:
            ops.append(f"({_pdf_escape(ln)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                    b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content_id, font_id))
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{k} 0 R" for k in kids).encode(), len(kids))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def make_audio(out: Path) -> list[dict]:
    """espeak-ng synthetic speech; segment timestamps are exact because we build the file ourselves."""
    segments, frames, params = [], b"", None
    t = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, sentence in enumerate(AUDIO_SEGMENTS):
            wav = Path(tmp) / f"s{i}.wav"
            subprocess.run(["espeak-ng", "-v", "en-gb", "-s", "150", "-w", str(wav), sentence], check=True)
            with wave.open(str(wav)) as w:
                params = params or w.getparams()
                data = w.readframes(w.getnframes())
                dur = int(w.getnframes() * 1000 / w.getframerate())
            gap = b"\x00\x00" * int(params.framerate * 0.5)
            segments.append({"start_ms": t, "end_ms": t + dur, "text": sentence, "speaker": "Synthetic voice",
                             "language": "en"})
            frames += data + gap
            t += dur + 500
        joined = Path(tmp) / "joined.wav"
        with wave.open(str(joined), "wb") as w:
            w.setparams(params)
            w.writeframes(frames)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-c:a", "flac", str(out)], check=True)
    return segments


VIDEO_TITLE = "Synthetic test-pattern video (not a historical recording)"


def make_video(audio: Path, out: Path) -> None:
    """FFmpeg test pattern carrying the synthetic talk, so the video path has an unmistakably fake fixture.
    The audio track is the talk unchanged, so the talk's segment timestamps apply to the video too."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=15",
                    "-i", str(audio), "-shortest", "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac",
                    "-b:a", "64k", "-movflags", "+faststart", "-map_metadata", "-1", "-metadata",
                    f"title={VIDEO_TITLE}", "-metadata",
                    "comment=Synthetic fixture generated by fixtures/generate_fixtures.py", str(out)], check=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_png(img: Image.Image, path: Path) -> None:
    img.save(path, format="PNG", optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    out = Path(ap.parse_args().out)
    (out / "files").mkdir(parents=True, exist_ok=True)
    f = out / "files"
    if not features.check("raqm"):
        print("WARNING: Pillow has no raqm; Devanagari shaping will be wrong. Install libraqm0/libfribidi0.")

    (f / "fx-essay-reading-rooms.pdf").write_bytes(make_pdf(TEXTS["essay"]))
    (f / "fx-restricted-memo.pdf").write_bytes(make_pdf(TEXTS["restricted"]))
    (f / "fx-online-only-report.pdf").write_bytes(make_pdf(TEXTS["online_only"]))
    save_png(render_page(TEXTS["lecture_clean"][0], FONT_SERIF), f / "fx-lecture-education.png")
    save_png(degrade(render_page(TEXTS["lecture_degraded"][0], FONT_SERIF)), f / "fx-lecture-tank-degraded.png")
    save_png(render_spread(*TEXTS["proceedings"]), f / "fx-proceedings-spread.png")
    save_png(render_page(TEXTS["hindi"][0], FONT_DEVA, size=40, wrap=48, lang="hi"), f / "fx-pamphlet-hi.png")
    save_png(render_page(TEXTS["marathi"][0], FONT_DEVA, size=40, wrap=48, lang="mr"), f / "fx-petition-mr.png")
    save_png(render_handwriting(TEXTS["manuscript"][0]), f / "fx-manuscript-note.png")
    render_photo().save(f / "fx-photo-reading-room.jpg", quality=85)
    segments = make_audio(f / "fx-talk-synthetic.flac")
    make_video(f / "fx-talk-synthetic.flac", f / "fx-talk-video-synthetic.mp4")
    # A capture for the live-path demo (not in the seed manifest): a second clean printed page.
    save_png(render_page(f"{LABEL_EN}\nLetter to the Library Board\n\nThe board is asked to publish the list of "
                         "new books every month on the notice board of each reading room, and to allow members "
                         "to suggest titles. Requests from the mill districts should be answered first.",
                         FONT_SERIF), out / "capture-demo-page.png")

    ground_truth = {
        "_note": "Ground truth for SYNTHETIC fixture pages. OCR evaluation on these is a smoke test only; "
                 "real calibration needs real archive pages (spec 10.1).",
        "pages": [
            {"id": "fx-lecture-education-p1", "image": "files/fx-lecture-education.png", "language": "en",
             "doc_class": "printed", "text": TEXTS["lecture_clean"][0], "split": "calibration"},
            {"id": "fx-lecture-tank-degraded-p1", "image": "files/fx-lecture-tank-degraded.png", "language": "en",
             "doc_class": "printed", "text": TEXTS["lecture_degraded"][0], "split": "calibration"},
            {"id": "fx-proceedings-p1", "image": "files/fx-proceedings-spread.png", "half": 0, "language": "en",
             "doc_class": "printed", "text": TEXTS["proceedings"][0], "split": "test"},
            {"id": "fx-proceedings-p2", "image": "files/fx-proceedings-spread.png", "half": 1, "language": "en",
             "doc_class": "printed", "text": TEXTS["proceedings"][1], "split": "test"},
            {"id": "fx-pamphlet-hi-p1", "image": "files/fx-pamphlet-hi.png", "language": "hi",
             "doc_class": "printed", "text": TEXTS["hindi"][0], "split": "test"},
            {"id": "fx-petition-mr-p1", "image": "files/fx-petition-mr.png", "language": "mr",
             "doc_class": "printed", "text": TEXTS["marathi"][0], "split": "test"},
            {"id": "fx-manuscript-note-p1", "image": "files/fx-manuscript-note.png", "language": "en",
             "doc_class": "handwritten", "text": TEXTS["manuscript"][0], "split": "test"},
        ],
        "texts": TEXTS,
        "audio_segments": segments,
        "photo_caption": PHOTO_CAPTION,
    }
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=1), encoding="utf-8")

    manifest = build_manifest(f, segments)
    (out / "manifests").mkdir(exist_ok=True)
    (out / "manifests" / "fixture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
    print(json.dumps({"raqm": features.check("raqm"), "files": sorted(p.name for p in f.iterdir())}, indent=1))


def build_manifest(f: Path, segments: list[dict]) -> dict:
    def file(name: str) -> dict:
        return {"path": f"../files/{name}", "sha256": sha(f / name)}

    common = {"source_institution": "Synthetic fixture collection (this repository)",
              "rights_holder": "Build team (synthetic content written for testing)",
              "basis_for_use": "Original synthetic test content", "evidence": "fixtures/README.md",
              "attribution": "Synthetic fixture - not a work of Dr. B. R. Ambedkar", "date_checked": "2026-09-26",
              "checked_by": "build-agent (fixture)", "is_fixture": True}
    rights = [
        {**common, "source_key": "fx-open", "title": "Synthetic fixtures: display, training and external OCR allowed",
         "display_permission": "allowed", "training_permission": "allowed", "external_processing": "allowed",
         "training_basis": "synthetic content owned by the build team"},
        {**common, "source_key": "fx-no-training", "title": "Synthetic fixtures: display only",
         "display_permission": "allowed", "training_permission": "not_allowed", "external_processing": "not_allowed"},
        {**common, "source_key": "fx-rights-unknown", "title": "Synthetic fixture with unresolved rights",
         "display_permission": "unknown", "training_permission": "unknown", "external_processing": "unknown"},
    ]
    creator = "A. N. Example (fictional synthetic author)"
    items = [
        {"item_key": "fx-essay-reading-rooms", "rights_source_key": "fx-open", "title": "On Public Reading Rooms (synthetic essay)",
         "item_type": "text", "collection": "writings", "doc_class": "born_digital", "languages": ["en"],
         "creator": creator, "date_text": "1926 (fictional)", "date_start": "1926-01-01", "date_certainty": "approximate",
         "files": [file("fx-essay-reading-rooms.pdf")], "page_labels": ["1", "2"],
         "capture": {"work_key": "work-essay", "station": "born-digital"}},
        {"item_key": "fx-lecture-education", "rights_source_key": "fx-open",
         "title": "Lecture on Education and Work (synthetic)", "item_type": "printed_scan", "collection": "speeches",
         "doc_class": "printed", "languages": ["en"], "creator": creator, "date_text": "1929 (fictional)",
         "date_start": "1929-06-01", "date_certainty": "approximate", "files": [file("fx-lecture-education.png")],
         "capture": {"work_key": "work-lecture-education", "station": "fixture-generator", "dpi": 200}},
        {"item_key": "fx-lecture-tank", "rights_source_key": "fx-open",
         "title": "Lecture on Water and the Common Tank (synthetic, degraded scan)", "item_type": "printed_scan",
         "collection": "speeches", "doc_class": "printed", "languages": ["en"], "creator": creator,
         "date_text": "1928 (fictional)", "date_start": "1928-03-01", "date_certainty": "approximate",
         "files": [file("fx-lecture-tank-degraded.png")],
         "capture": {"work_key": "work-lecture-tank", "station": "fixture-generator", "dpi": 200}},
        {"item_key": "fx-proceedings-1", "rights_source_key": "fx-open",
         "title": "Proceedings of the Samarpur Civic Assembly, Sitting 1 (synthetic)", "item_type": "printed_scan",
         "collection": "debates", "doc_class": "printed", "languages": ["en"],
         "creator": "Samarpur Civic Assembly (fictional)", "date_text": "1927 (fictional)", "date_start": "1927-02-10",
         "date_certainty": "exact", "files": [file("fx-proceedings-spread.png")], "page_labels": ["1", "2"],
         "capture": {"work_key": "work-proceedings", "station": "fixture-generator", "dpi": 200, "spread": True}},
        {"item_key": "fx-pamphlet-hi", "rights_source_key": "fx-open",
         "title": "सार्वजनिक वाचनालय पर्चा (कृत्रिम नमूना) / Reading-room pamphlet (synthetic, Hindi)",
         "item_type": "printed_scan", "collection": "writings", "doc_class": "printed", "languages": ["hi"],
         "scripts": ["Deva"], "creator": creator, "date_text": "1930 (fictional)", "date_start": "1930-01-01",
         "date_certainty": "approximate", "files": [file("fx-pamphlet-hi.png")],
         "capture": {"work_key": "work-pamphlet-hi", "station": "fixture-generator", "dpi": 200}},
        {"item_key": "fx-petition-mr", "rights_source_key": "fx-no-training",
         "title": "पाणवठा निवेदन (कृत्रिम नमुना) / Water petition (synthetic, Marathi)", "item_type": "printed_scan",
         "collection": "writings", "doc_class": "printed", "languages": ["mr"], "scripts": ["Deva"],
         "creator": creator, "date_text": "1928 (fictional)", "date_start": "1928-05-01", "date_certainty": "approximate",
         "files": [file("fx-petition-mr.png")], "capture": {"work_key": "work-petition-mr", "station": "fixture-generator"}},
        {"item_key": "fx-manuscript-note", "rights_source_key": "fx-open",
         "title": "Handwritten note on the library board (synthetic)", "item_type": "manuscript",
         "collection": "manuscripts", "doc_class": "handwritten", "languages": ["en"], "creator": creator,
         "date_text": "3 March 1927 (fictional)", "date_start": "1927-03-03", "date_certainty": "exact",
         "files": [file("fx-manuscript-note.png")], "capture": {"work_key": "work-manuscript-note"}},
        {"item_key": "fx-photo-reading-room", "rights_source_key": "fx-open",
         "title": "Readers at the Samarpur reading room (synthetic illustration)", "item_type": "photograph",
         "collection": "photographs", "doc_class": "photograph", "languages": ["en"],
         "date_text": "around 1925 (fictional)", "date_start": "1925-01-01", "date_certainty": "approximate",
         "files": [file("fx-photo-reading-room.jpg")],
         "photo": {"caption": PHOTO_CAPTION, "people": [], "place": "Samarpur (fictional)",
                   "event": "Evening reading hours", "date_text": "around 1925 (fictional)",
                   "date_certainty": "approximate", "photographer": "Synthetic generator",
                   "source_reference": "fixtures/generate_fixtures.py"},
         "capture": {"work_key": "work-photo"}},
        {"item_key": "fx-talk-audio", "rights_source_key": "fx-open",
         "title": "Talk on the reading room (synthetic speech, not a historical recording)", "item_type": "audio",
         "collection": "audio_video", "doc_class": "audio_video", "languages": ["en"],
         "creator": "espeak-ng synthetic voice", "date_text": "2026 (generated)", "date_start": "2026-09-26",
         "date_certainty": "exact", "files": [file("fx-talk-synthetic.flac")], "transcript_draft": segments,
         "capture": {"work_key": "work-talk"}},
        {"item_key": "fx-talk-video", "rights_source_key": "fx-open", "title": VIDEO_TITLE,
         "item_type": "video", "collection": "audio_video", "doc_class": "audio_video", "languages": ["en"],
         "creator": "FFmpeg test pattern + espeak-ng synthetic voice", "date_text": "2026 (generated)",
         "date_start": "2026-09-27", "date_certainty": "exact", "files": [file("fx-talk-video-synthetic.mp4")],
         "transcript_draft": segments, "capture": {"work_key": "work-talk-video"}},
        {"item_key": "fx-restricted-memo", "rights_source_key": "fx-rights-unknown",
         "title": "Draft memorandum (synthetic, rights unknown)", "item_type": "text", "collection": "writings",
         "doc_class": "born_digital", "languages": ["en"], "creator": creator,
         "files": [file("fx-restricted-memo.pdf")], "capture": {"work_key": "work-restricted"}},
        {"item_key": "fx-online-only-report", "rights_source_key": "fx-no-training",
         "title": "Newspaper report on the library board (synthetic, online only)", "item_type": "text",
         "collection": "writings", "doc_class": "born_digital", "languages": ["en"], "access_level": "public_online_only",
         "creator": "The Samarpur Gazette (fictional)", "date_text": "12 April 1927 (fictional)",
         "date_start": "1927-04-12", "date_certainty": "exact", "files": [file("fx-online-only-report.pdf")],
         "capture": {"work_key": "work-online-only"}},
    ]
    return {"manifest_version": 1, "_note": "SYNTHETIC FIXTURES ONLY. Not works of Dr. B. R. Ambedkar.",
            "rights": rights, "items": items}


if __name__ == "__main__":
    main()
