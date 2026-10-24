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
    labels = {"files": [], "duplicates": [], "conflicts": []}
    seen_names = set()

    def content() -> bytes:
        return bytes(rng.getrandbits(8) for _ in range(rng.randint(512, 8192)))

    # 1) unique base files
    while len(labels["files"]) < count:
        subject = rng.choice(SUBJECTS)
        kind = rng.choice(KINDS)
        name = f"{kind} {subject} {rng.choice(GRADES)} فصل {rng.randint(1, 12)}.pdf"
        if name in seen_names:
            continue
        seen_names.add(name)
        (out / name).write_bytes(content())
        labels["files"].append({"name": name, "subject": subject,
                                "chapter": None})

    # 2) planted exact duplicates: same bytes under a different name
    for i in range(max(1, count // 10)):
        base = labels["files"][rng.randrange(count)]
        copy_name = f"{Path(base['name']).stem} — نسخه {i + 1}.pdf"
        (out / copy_name).write_bytes((out / base["name"]).read_bytes())
        labels["duplicates"].append([base["name"], copy_name])

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
          f"{len(labels['conflicts'])} conflicts → {args.out}")
