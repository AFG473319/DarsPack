"""Generate the labelled synthetic test set (مجموعه‌ی آزمون ساختگی).

Builds the set described in eval/benchmark-plan.md: N realistic
Persian-named dummy files, plus planted *exact duplicates* (same bytes,
different names) and *version conflicts* (same name, different content).
labels.json records the ground truth so detection accuracy can be
measured automatically. Deterministic per seed — every run with the
same seed produces the same bytes, so reported numbers are reproducible.

Usage:
    python eval/make_testset.py --out eval/_generated/testset --count 120
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SUBJECTS = ["ریاضی", "علوم", "فارسی", "عربی", "دینی", "انگلیسی",
            "مطالعات اجتماعی", "هنر", "کار و فناوری"]
KINDS = ["نمونه سوال", "جزوه", "کاربرگ", "تکلیف"]
GRADES = ["هفتم", "هشتم", "نهم"]
CONFLICT_DIR = "دوباره دریافت شده"   # like a real re-download folder


def make_testset(out: Path, count: int = 120, seed: int = 1405) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    labels = {"files": [], "duplicates": [], "conflicts": [], "versions": []}
    seen_names = set()

    def content() -> bytes:
        return bytes(rng.getrandbits(8) for _ in range(rng.randint(512, 8192)))

    # 1) unique base files — each is named with «فصل N» (chapter) or
    # «درس N» (lesson): real libraries mix both, and the labels record
    # which one the filename carries so M10 can measure each column
    while len(labels["files"]) < count:
        subject = rng.choice(SUBJECTS)
        kind = rng.choice(KINDS)
        if rng.random() < 0.7:
            unit, number = "فصل", rng.randint(1, 12)
            chapter, lesson = number, None
        else:
            unit, number = "درس", rng.randint(1, 12)
            chapter, lesson = None, number
        name = f"{kind} {subject} {rng.choice(GRADES)} {unit} {number}.pdf"
        if name in seen_names:
            continue
        seen_names.add(name)
        (out / name).write_bytes(content())
        labels["files"].append({"name": name, "subject": subject,
                                "chapter": chapter, "lesson": lesson})

    # 2) planted exact duplicates: same bytes under a different name
    for i in range(max(1, count // 10)):
        base = labels["files"][rng.randrange(count)]
        copy_name = f"{Path(base['name']).stem} — نسخه {i + 1}.pdf"
        (out / copy_name).write_bytes((out / base["name"]).read_bytes())
        labels["duplicates"].append([base["name"], copy_name])

    # 2b) planted near-duplicates: the browser's re-download pattern —
    # same display name plus « (1)», DIFFERENT bytes (the ground truth
    # for the R4-lite likely-versions detector, which must group them)
    labels["versions"] = []
    for i in range(max(2, count // 20)):
        base = labels["files"][rng.randrange(count)]
        redownload = f"{Path(base['name']).stem} (1).pdf"
        if redownload in seen_names:
            continue
        seen_names.add(redownload)
        (out / redownload).write_bytes(content())
        labels["versions"].append([base["name"], redownload])

    # 3) planted conflicts: same name, different bytes, in a subfolder
    conflict_dir = out / CONFLICT_DIR
    conflict_dir.mkdir(exist_ok=True)
    for _ in range(max(2, count // 25)):
        base = labels["files"][rng.randrange(count)]
        (conflict_dir / base["name"]).write_bytes(content())
        labels["conflicts"].append(
            [base["name"], f"{CONFLICT_DIR}/{base['name']}"])

    (out / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    return labels


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/_generated/testset")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--seed", type=int, default=1405)
    args = parser.parse_args()
    labels = make_testset(Path(args.out), args.count, args.seed)
    print(f"{len(labels['files'])} files, "
          f"{len(labels['duplicates'])} duplicate pairs, "
          f"{len(labels['conflicts'])} conflicts, "
          f"{len(labels['versions'])} near-duplicate versions → {args.out}")
