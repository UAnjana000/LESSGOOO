"""Check that held-out spec 10.1 test questions never appear in training labels (spec 7.3 step 3, 10.1
"Training split").

    python eval/check_training_leakage.py --eval-questions eval/questions/retrieval.json \
        --labels path/to/labels.json [--near 0.8]

eval questions: {"questions": [{"id", "question", "language", "positives": [{"item_key", "anchor"}]}]}
labels:         {"labels":    [{"id", "question", "language", "positives": [{"item_key", "anchor"}], ...}]}

Errors (exit 1): the same question text (after normalisation) in both files.
Warnings: near-duplicate wording (token Jaccard >= --near), and labels whose positives come from the
same item as a held-out question - acceptable only if that work lands in the test split at freeze time.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from typing import Any

from evalkit import load_json

_TOK = re.compile(r"\w+", re.UNICODE)


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower()
    return " ".join(_TOK.findall(t))


def jaccard(a: str, b: str) -> float:
    sa, sb = set(normalise(a).split()), set(normalise(b).split())
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def check(eval_qs: list[dict[str, Any]], labels: list[dict[str, Any]], near: float) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    by_norm = {normalise(lab["question"]): lab for lab in labels}
    label_items: dict[str, list[str]] = {}
    for lab in labels:
        for pos in lab.get("positives", []):
            label_items.setdefault(pos.get("item_key", ""), []).append(str(lab.get("id")))
    for q in eval_qs:
        n = normalise(q["question"])
        if n in by_norm:
            errors.append(f"held-out question {q.get('id')} also appears as training label {by_norm[n].get('id')}")
            continue
        for lab in labels:
            score = jaccard(q["question"], lab["question"])
            if score >= near:
                warnings.append(f"held-out {q.get('id')} ~ label {lab.get('id')} (Jaccard {score:.2f})")
        for pos in q.get("positives", []):
            ids = label_items.get(pos.get("item_key", ""))
            if ids:
                warnings.append(f"held-out {q.get('id')} shares item '{pos['item_key']}' with labels {sorted(set(ids))[:5]}; "
                                "confirm that work is in the test split")
    return errors, warnings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-questions", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--near", type=float, default=0.8)
    args = ap.parse_args()
    errors, warnings = check(load_json(args.eval_questions).get("questions", []),
                             load_json(args.labels).get("labels", []), args.near)
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
