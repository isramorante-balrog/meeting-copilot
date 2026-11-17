"""Tiny local BM25 retriever for the supporting-experience documents (no external deps, <5 ms per query).

Documents are split into ~N-word chunks on paragraph/heading boundaries; the live question is tokenized
(EN/ES stopwords removed, light stemming) and the top-k chunks are returned with their document name.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_STOP = set("""a an and are as at be but by for from has have how i if in is it its of on or that the this to was we
were what when where which who why will with you your our they their them he she his her do does did can could would
should about into over than then there these those been being am just also very more most much
el la los las un una unos unas y o de del al a en es son fue era que como qué cómo con para por se su sus lo le les mi
mis tu tus nos este esta estos estas ese esa eso aquel aquella pero más muy ya no si sí hay ser estar he ha han
cuál cuáles cuándo dónde quién quiénes puedes puede podría podrías nuestro nuestra nuestros nuestras""".split())


def _norm(word: str) -> str:
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    # light stemming: plural / verb endings
    for suf in ("ciones", "cion", "mente", "ing", "ies", "ed", "es", "s"):
        if len(w) > 5 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w


def tokenize(text: str) -> list[str]:
    return [_norm(w.strip(".,;:")) for w in re.findall(r"[a-zA-ZÀ-ÿ0-9][a-zA-ZÀ-ÿ0-9\-_.]{1,}", text)
            if w.strip(".,;:").lower() not in _STOP and len(w.strip(".,;:")) > 1]


def _split_big(p: str, target_words: int) -> list[str]:
    """Split an oversized paragraph into ~target_words pieces: by sentences when punctuation exists,
    otherwise by fixed word windows."""
    sents = [x for x in re.split(r"(?<=[.!?;])\s+", p) if x]
    if len(sents) <= 1:
        words = p.split()
        return [" ".join(words[k:k + target_words]) for k in range(0, len(words), target_words)]
    out, buf, n = [], [], 0
    for sent in sents:
        w = len(sent.split())
        if w > target_words * 1.5:
            if buf:
                out.append(" ".join(buf))
                buf, n = [], 0
            out.extend(_split_big(sent.replace(".", ". "), target_words))
            continue
        if n + w > target_words and buf:
            out.append(" ".join(buf))
            buf, n = [], 0
        buf.append(sent)
        n += w
    if buf:
        out.append(" ".join(buf))
    return out


def chunk_text(text: str, target_words: int = 300) -> list[str]:
    """Split on blank lines / headings, then pack paragraphs into ~target_words chunks.
    A heading always stays attached to the text that follows it."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=#{1,6}\s)", text) if p.strip()]
    units: list[tuple[str, bool]] = []  # (text, is_heading)
    for p in paras:
        # "## Heading\nbody..." in one paragraph -> split the heading line off
        hm = re.match(r"^(#{1,6}\s[^\n]*)\n(.+)$", p, flags=re.S)
        if hm:
            units.append((hm.group(1).strip(), True))
            p = hm.group(2).strip()
        is_heading = bool(re.match(r"^(#{1,6}\s|[A-Z][^\n]{3,80}:\s*$)", p)) and len(p.split()) <= 25
        if is_heading:
            units.append((p, True))
        elif len(p.split()) > target_words * 1.6:
            units.extend((x, False) for x in _split_big(p, target_words))
        else:
            units.append((p, False))
    chunks: list[str] = []
    cur: list[str] = []
    n = 0
    pending_heading: str | None = None
    for txt, is_heading in units:
        if is_heading:
            if cur and n >= target_words * 0.4:
                chunks.append("\n\n".join(cur))
                cur, n = [], 0
            pending_heading = txt
            continue
        piece = f"{pending_heading}\n\n{txt}" if pending_heading else txt
        pending_heading = None
        w = len(piece.split())
        if cur and n + w > target_words:
            chunks.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(piece)
        n += w
    if pending_heading:
        cur.append(pending_heading)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


class BM25Index:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[dict] = []        # {"name", "text", "tf": Counter, "len": int, "idx": int}
        self.df: Counter = Counter()
        self.avg_len = 1.0

    def build(self, documents: list[tuple[str, str]], target_words: int = 300) -> None:
        self.docs, self.df = [], Counter()
        for name, text in documents:
            for i, chunk in enumerate(chunk_text(text, target_words)):
                toks = tokenize(chunk)
                if len(toks) < 4:
                    continue
                tf = Counter(toks)
                self.docs.append({"name": name, "text": chunk, "tf": tf, "len": len(toks), "idx": i})
                self.df.update(tf.keys())
        self.avg_len = (sum(d["len"] for d in self.docs) / len(self.docs)) if self.docs else 1.0

    def search(self, query: str, k: int = 3, min_score: float = 0.5, boost: str | None = None,
               boost_weight: float = 0.6, avoid: str | None = None, avoid_weight: float = 0.8) -> list[dict]:
        """`boost` (e.g. today's session focus) adds its terms at a reduced weight, so chunks matching the
        declared focus rank higher without drowning the actual question. `avoid` (the names of the story
        already told) subtracts weight, so chunks about a *different* project surface for the next answer
        (story rotation); the penalty is capped so a chunk that is the only match still wins."""
        q = tokenize(query)
        bterms = set(tokenize(boost)) - set(q) if boost else set()
        aterms = set(tokenize(avoid)) - set(q) if avoid else set()
        if (not q and not bterms) or not self.docs:
            return []
        N = len(self.docs)
        scored = []
        for d in self.docs:
            s = 0.0
            for term, w in [(t, 1.0) for t in set(q)] + [(t, boost_weight) for t in bterms] + [(t, -avoid_weight) for t in aterms]:
                f = d["tf"].get(term)
                if not f:
                    continue
                idf = math.log(1 + (N - self.df[term] + 0.5) / (self.df[term] + 0.5))
                s += w * idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * d["len"] / self.avg_len))
            if aterms:
                s = max(s, 0.05 * sum(1 for t in set(q) if d["tf"].get(t)))  # never below a sliver of its raw matches
            if s > 0:
                scored.append((s, d))
        scored.sort(key=lambda x: -x[0])
        out = []
        for s, d in scored[:k]:
            if s < min_score and out:
                break
            out.append({"name": d["name"], "text": d["text"], "score": round(s, 2), "chunk": d["idx"]})
        return out

    def size(self) -> int:
        return len(self.docs)
