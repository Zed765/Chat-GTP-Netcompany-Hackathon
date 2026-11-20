#!/usr/bin/env python3
"""Count words, sentences and the most common terms in text files."""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
SENTENCE_END = re.compile(r"[.!?;]+")
STOP_WORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that", "for", "on"}


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="latin-1")


def words(text):
    return [match.group().lower() for match in WORD.finditer(text)]


def sentences(text):
    return [part.strip() for part in SENTENCE_END.split(text) if part.strip()]


def reading_time(word_count, words_per_minute=220):
    minutes = word_count / words_per_minute
    return f"{minutes:.1f} min" if minutes >= 1 else f"{round(minutes * 60)} s"


def top_terms(tokens, limit):
    counts = Counter(token for token in tokens if token not in STOP_WORDS and len(token) > 2)
    return counts.most_common(limit)


def longest_words(tokens, limit=5):
    """The longest distinct words, longest first; ties are broken alphabetically."""
    return sorted(set(tokens), key=lambda token: (-len(token), token))[:limit]


def lexical_density(tokens):
    """Share of words that are not stop words: a rough measure of how dense a text is."""
    if not tokens:
        return 0.0
    content = sum(1 for token in tokens if token not in STOP_WORDS)
    return round(content / len(tokens), 3)


def summarise(path, limit):
    text = read_text(path)
    tokens = words(text)
    parts = sentences(text)
    average = len(tokens) / len(parts) if parts else 0.0
    return {
        "file": str(path),
        "characters": len(text),
        "words": len(tokens),
        "unique": len(set(tokens)),
        "sentences": len(parts),
        "average_sentence": round(average, 1),
        "reading_time": reading_time(len(tokens)),
        "density": lexical_density(tokens),
        "longest": ", ".join(longest_words(tokens)),
        "top": top_terms(tokens, limit),
    }


def print_summary(summary):
    print(summary["file"])
    keys = ("characters", "words", "unique", "sentences", "average_sentence", "reading_time")
    for key in (*keys, "density", "longest"):
        print(f"  {key.replace('_', ' '):<18}{summary[key]}")
    for term, count in summary["top"]:
        print(f"  {term:<18}{'#' * min(count, 40)} {count}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="text files to analyse")
    parser.add_argument("-n", "--top", type=int, default=10, help="how many terms to list")
    args = parser.parse_args(argv)
    missing = [name for name in args.files if not Path(name).is_file()]
    if missing:
        print(f"not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    for name in args.files:
        print_summary(summarise(name, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
