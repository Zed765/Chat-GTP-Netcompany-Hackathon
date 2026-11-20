"""Greek-aware text normalisation shared by the term matcher and the vault's entity linking.

`entity_key` is the important one: mentions of one entity in different case, accents,
inflection or script ("Μαρίας", "ΜΑΡΙΑ", "Maria") get the same key.
"""

import re
import unicodedata

_DIGRAPHS = {
    "ου": "ou",
    "αι": "ai",
    "ει": "ei",
    "οι": "oi",
    "γγ": "ng",
    "γκ": "gk",
    "γχ": "nch",
    "μπ": "mp",
    "ντ": "nt",
    "τσ": "ts",
    "τζ": "tz",
}
_LETTERS = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th",
    "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p",
    "ρ": "r", "σ": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
}  # fmt: skip
_VOICED = set("αεηιουωβγδζλμνρ")
_GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Greeklish spellings that stand for the same sound, collapsed to one form.
_LATIN_VARIANTS = (
    ("ph", "f"),
    ("kh", "ch"),
    ("oy", "u"),
    ("ou", "u"),
    ("ei", "i"),
    ("oi", "i"),
    ("ai", "e"),
    ("y", "i"),
    ("w", "o"),
    ("b", "v"),
    ("mp", "v"),
    ("nt", "d"),
    ("gk", "g"),
    ("c", "k"),
)
# Longest first. Covers the nominative, genitive, accusative and vocative of names.
_ENDINGS = ("ous", "ou", "os", "is", "as", "es", "on", "us", "a", "e", "i", "o", "s", "u")
_MIN_STEM = 3


def fold(text: str) -> str:
    """Lower-case and strip accents, so "Μαρία", "ΜΑΡΙΑ" and "μαρια" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.replace("ς", "σ")


def has_greek(text: str) -> bool:
    return bool(_GREEK.search(text))


def transliterate(text: str) -> str:
    """Folded Greek to Latin, following ELOT 743. Non-Greek characters pass through."""
    source = fold(text)
    out: list[str] = []
    index = 0
    while index < len(source):
        pair = source[index : index + 2]
        if pair in _DIGRAPHS:
            out.append(_DIGRAPHS[pair])
            index += 2
            continue
        if pair in ("αυ", "ευ", "ηυ"):
            following = source[index + 2 : index + 3]
            out.append(_LETTERS[pair[0]] + ("v" if following in _VOICED and following else "f"))
            index += 2
            continue
        out.append(_LETTERS.get(source[index], source[index]))
        index += 1
    return "".join(out)


def latin_key(word: str) -> str:
    """A spelling-tolerant Latin form of one word, for comparing Greek with Greeklish."""
    key = transliterate(word)
    for variant, canonical in _LATIN_VARIANTS:
        key = key.replace(variant, canonical)
    return re.sub(r"(.)\1+", r"\1", key)


def stem(word_key: str) -> str:
    """Drop a Greek case ending from a `latin_key`, keeping at least three letters."""
    for ending in _ENDINGS:
        if word_key.endswith(ending) and len(word_key) - len(ending) >= _MIN_STEM:
            return word_key[: -len(ending)]
    return word_key


def word_keys(text: str) -> list[str]:
    return [stem(latin_key(word)) for word in _WORD.findall(text)]


def entity_key(text: str) -> str:
    """One key per entity, whatever the case, accents, inflection or script of the mention."""
    return " ".join(word_keys(text))
