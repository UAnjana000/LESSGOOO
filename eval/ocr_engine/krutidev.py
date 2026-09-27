"""Kruti Dev 010 (and Walkman Chanakya 905) legacy-font text to Unicode Devanagari.

Used only to build OCR ground truth from the mojibake text layer of the Hindi PDFs (docs/OCR_ENGINE_EVAL.md).
The table and the three reordering passes (ि before its consonant, reph Z after its syllable, ि before a half
consonant) follow the widely used public-domain Kruti Dev 010 -> Unicode converter (Rajesh Kumar Singh's
JavaScript table, the basis of most online converters). Replacements run in table order, so longer glyph
sequences must stay ahead of their prefixes.

Walkman Chanakya 905 shares the Kruti Dev layout except for a few glyphs, handled by CHANAKYA_PRE and
CHANAKYA_GLYPHS (each checked by eye against the rendered CAD Hindi pages): the right-hand hook `Q` after
`o`/`i`/`j` builds क/फ/रु, `”k` is ज़, `=k` is त्र, `/` is ध, `¼` is द्ध, `(`/`)` are ordinary brackets,
`¹`/`º` are `[`/`]`, `·` is `*`, `Ý` is फ्, `Õ` is ै, `_` is `;`, `¶`/`¸` are quotation marks, and the
unmapped glyph U+FFFE is a full stop (in Kruti Dev text it is a hyphen).
"""

from __future__ import annotations

import re
import unicodedata

_PAIRS: list[tuple[str, str]] = [
    ("ñ", "॰"), ("Q+Z", "QZ+"), ("sas", "sa"), ("aa", "a"), (")Z", "र्द्ध"), ("ZZ", "Z"),
    ("‘", "\""), ("’", "\""), ("“", "'"), ("”", "'"),
    ("å", "०"), ("ƒ", "१"), ("„", "२"), ("…", "३"), ("†", "४"), ("‡", "५"), ("ˆ", "६"), ("‰", "७"),
    ("Š", "८"), ("‹", "९"),
    ("¶+", "फ़्"), ("d+", "क़"), ("[+k", "ख़"), ("[+", "ख़्"), ("x+", "ग़"), ("T+", "ज़्"), ("t+", "ज़"),
    ("M+", "ड़"), ("<+", "ढ़"), ("Q+", "फ़"), (";+", "य़"), ("j+", "ऱ"), ("u+", "ऩ"),
    ("Ùk", "त्त"), ("Ù", "त्त्"), ("Dr", "क्त"), ("–", "दृ"), ("—", "कृ"), ("é", "न्न"), ("™", "न्न्"),
    ("=kk", "=k"), ("f=k", "f="),
    ("à", "ह्न"), ("á", "ह्य"), ("â", "हृ"), ("ã", "ह्म"), ("ºz", "ह्र"), ("º", "ह्"), ("í", "द्द"),
    ("{k", "क्ष"), ("{", "क्ष्"), ("=", "त्र"), ("«", "त्र्"),
    ("Nî", "छ्य"), ("Vî", "ट्य"), ("Bî", "ठ्य"), ("Mî", "ड्य"), ("<î", "ढ्य"), ("|", "द्य"), ("K", "ज्ञ"),
    ("}", "द्व"),
    ("J", "श्र"), ("Vª", "ट्र"), ("Mª", "ड्र"), ("<ªª", "ढ्र"), ("Nª", "छ्र"), ("Ø", "क्र"), ("Ý", "फ्र"),
    ("nzZ", "र्द्र"), ("æ", "द्र"), ("ç", "प्र"), ("Á", "प्र"), ("xz", "ग्र"), ("#", "रु"), (":", "रू"),
    ("v‚", "ऑ"), ("vks", "ओ"), ("vkS", "औ"), ("vk", "आ"), ("v", "अ"), ("b±", "ईं"), ("Ã", "ई"), ("bZ", "ई"),
    ("b", "इ"), ("m", "उ"), ("Å", "ऊ"), (",s", "ऐ"), (",", "ए"), ("_", "ऋ"),
    ("ô", "क्क"), ("d", "क"), ("Dk", "क"), ("D", "क्"), ("[k", "ख"), ("[", "ख्"), ("x", "ग"), ("Xk", "ग"),
    ("X", "ग्"), ("Ä", "घ"), ("?k", "घ"), ("?", "घ्"), ("³", "ङ"),
    ("pkS", "चै"), ("p", "च"), ("Pk", "च"), ("P", "च्"), ("N", "छ"), ("t", "ज"), ("Tk", "ज"), ("T", "ज्"),
    (">", "झ"), ("÷", "झ्"), ("¥", "ञ"),
    ("ê", "ट्ट"), ("ë", "ट्ठ"), ("V", "ट"), ("B", "ठ"), ("ì", "ड्ड"), ("ï", "ड्ढ"), ("M+", "ड़"), ("<+", "ढ़"),
    ("M", "ड"), ("<", "ढ"), (".k", "ण"), (".", "ण्"),
    ("r", "त"), ("Rk", "त"), ("R", "त्"), ("Fk", "थ"), ("F", "थ्"), (")", "द्ध"), ("n", "द"), ("/k", "ध"),
    ("èk", "ध"), ("/", "ध्"), ("Ë", "ध्"), ("è", "ध्"), ("u", "न"), ("Uk", "न"), ("U", "न्"),
    ("i", "प"), ("Ik", "प"), ("I", "प्"), ("Q", "फ"), ("¶", "फ्"), ("c", "ब"), ("Ck", "ब"), ("C", "ब्"),
    ("Hk", "भ"), ("H", "भ्"), ("e", "म"), ("Ek", "म"), ("E", "म्"),
    (";", "य"), ("¸", "य्"), ("j", "र"), ("y", "ल"), ("Yk", "ल"), ("Y", "ल्"), ("G", "ळ"), ("o", "व"),
    ("Ok", "व"), ("O", "व्"),
    ("'k", "श"), ("'", "श्"), ("\"k", "ष"), ("\"", "ष्"), ("l", "स"), ("Lk", "स"), ("L", "स्"), ("g", "ह"),
    ("È", "ीं"), ("z", "्र"),
    ("Ì", "द्द"), ("Í", "ट्ट"), ("Î", "ट्ठ"), ("Ï", "ड्ड"), ("Ñ", "कृ"), ("Ò", "भ"), ("Ó", "्य"), ("Ô", "ड्ढ"),
    ("Ö", "झ्"), ("Ø", "क्र"), ("Ù", "त्त्"), ("Ük", "श"), ("Ü", "श्"),
    ("‚", "ॉ"), ("ks", "ो"), ("kS", "ौ"), ("k", "ा"), ("h", "ी"), ("q", "ु"), ("w", "ू"), ("`", "ृ"),
    ("s", "े"), ("S", "ै"),
    ("a", "ं"), ("¡", "ँ"), ("%", "ः"), ("W", "ॅ"), ("•", "ऽ"), ("·", "ऽ"), ("∙", "ऽ"), ("~j", "्र"),
    ("~", "्"), ("\\", "?"), ("+", "़"), (" ः", ":"),
    ("^", "‘"), ("*", "’"), ("Þ", "“"), ("ß", "”"), ("(", ";"), ("¼", "("), ("½", ")"), ("¿", "{"),
    ("À", "}"), ("¾", "="), ("A", "।"), ("-", "."), ("&", "-"), ("Œ", "॰"), ("]", ","), ("@", "/"),
    ("ª", "्र"),
]

MATRAS = "ािीुूृेैोौंःँॅ"
_BETWEEN = r"([zqwsSa¡Wh`]*)"
CHANAKYA_PRE: list[tuple[re.Pattern[str], str]] = [
    (re.compile("o" + _BETWEEN + "Q"), r"d\1"),   # व + hook = क (osQ = के, oqQN = कुछ)
    (re.compile("i" + _BETWEEN + "Q"), r"Q\1"),   # प + hook = फ (fiQj = फिर, izSaQd = फ्रैंक)
    (re.compile(r"jQ(?!\+)"), "#"),               # र + hook = रु (fojQ¼ = विरुद्ध); jQ+ is रफ़
    (re.compile("”k"), "t+"),                     # ज़ (ph”k = चीज़)
    (re.compile("=k"), "="),                      # त्र (ea=kh = मंत्री)
    (re.compile("Õ"), "S"),                       # ै (lhrkjeÕ;k = सीतारमैया)
]
CHANAKYA_GLYPHS = {"¼": "\ue002", "(": "\ue000", ")": "\ue001", "/": "\ue003", "¹": "\ue004",
                   "º": "\ue005", "\ufffe": "\ue006", "·": "\ue007", "Ý": "\ue008", "_": "\ue009",
                   "¶": "\ue00a", "¸": "\ue00b"}
_UNPROTECT = {"\ue000": "(", "\ue001": ")", "\ue002": "द्ध", "\ue003": "ध", "\ue004": "[", "\ue005": "]",
              "\ue006": ".", "\ue007": "*", "\ue008": "फ्", "\ue009": ";", "\ue00a": "“", "\ue00b": "”"}


def _reorder(s: str) -> str:
    s = s.replace("±", "Zं").replace("Æ", "र्f").replace("Ç", "fa").replace("É", "र्fa").replace("Ê", "ीZ")
    # ि is typed before its consonant: move it after the next character (a full consonant after mapping).
    out = list(s)
    i = 0
    while i < len(out):
        if out[i] == "f" and i + 1 < len(out):
            out[i], out[i + 1] = out[i + 1], "ि"
            i += 2
            continue
        i += 1
    s = "".join(out).replace("f", "ि")
    # ि placed on a half consonant belongs after the full consonant that follows it.
    s = re.sub(r"ि्(.)", r"्\1ि", s)
    # Reph Z is typed after its syllable (and its matras): put र् before the syllable's consonant cluster.
    while True:
        pos = s.find("Z")
        if pos <= 0:
            s = s.replace("Z", "र्")
            break
        j = pos - 1
        while j > 0 and s[j] in MATRAS:
            j -= 1
        while j >= 2 and s[j - 1] == "्":
            j -= 2
        s = s[:j] + "र्" + s[j:pos] + s[pos + 1:]
    return s


def convert(text: str, chanakya: bool = False) -> str:
    s = text
    if chanakya:
        for pat, rep in CHANAKYA_PRE:
            s = pat.sub(rep, s)
        for k, v in CHANAKYA_GLYPHS.items():
            s = s.replace(k, v)
    s = s.replace("\ufffe", "&")
    for a, b in _PAIRS:
        if a in s:
            s = s.replace(a, b)
    s = _reorder(s)
    for k, v in _UNPROTECT.items():
        s = s.replace(k, v)
    s = re.sub("([ंँ])([ािीुूृेैोौॅ])", r"\2\1", s)  # anusvara typed before the matra
    return unicodedata.normalize("NFC", s)


def leftover_latin(converted: str) -> int:
    """Latin letters left after conversion: unmapped glyphs, i.e. a sign the conversion is incomplete."""
    return sum(1 for c in converted if ("a" <= c.lower() <= "z") or ("\u00c0" <= c <= "\u024f"))
