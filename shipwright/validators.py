"""Deterministic metadata rules from the playbook. The critic agent calls these as tools;
the submitter refuses to write metadata that fails them. No LLM judgment here — these are
Apple's actual limits plus the three-name doctrine, and they must never be "creatively"
reinterpreted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LIMITS = {"name": 30, "subtitle": 30, "keywords": 100, "description": 4000, "promotionalText": 170}
FILL = {"name": 27, "subtitle": 27, "keywords": 97}  # playbook: fill ≥27/≥27/≥97
STOPWORDS = {"a", "an", "and", "the", "for", "of", "to", "in", "on", "with", "your", "&", "-", "·", "—", ":"}
BANNED_KEYWORD_TOKENS = {"app", "apps", "free", "best", "top", "new"}
COMPETITOR_BRANDS = {"alfred", "raycast", "1password", "lastpass", "notion", "evernote",
                     "apple", "iphone", "ios", "siri"}
PRICE_RE = re.compile(r"(\$|₹|€|£)\s?\d|\b\d+(\.\d{2})?\s?(usd|inr|eur|gbp)\b|\b\d+\.99\b", re.I)


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+]+", s.lower()) if w not in STOPWORDS}


def _singular(w: str) -> str:
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2] + "e" not in (w,):
        return w[:-2] if w.endswith(("shes", "ches", "xes", "sses")) else w[:-1]
    return w[:-1] if w.endswith("s") else w


def _is_plural_dupe(w: str, words: set[str]) -> bool:
    return w.endswith("s") and _singular(w) in words


def validate(meta: dict) -> Verdict:
    """meta keys: name, subtitle, keywords, description, promotionalText (optional)."""
    p: list[str] = []
    for k, lim in LIMITS.items():
        v = meta.get(k) or ""
        if len(v) > lim:
            p.append(f"{k} is {len(v)} chars, limit {lim}")
        if k in FILL and v and len(v) < FILL[k]:
            p.append(f"{k} is {len(v)} chars, fill to ≥{FILL[k]} (wasted ranking space)")
    for k in ("name", "subtitle", "keywords"):
        if not meta.get(k):
            p.append(f"{k} is empty")

    # cross-field repetition: Apple combines name+subtitle+keywords into phrases; a repeat is wasted chars
    nw, sw, kw = _words(meta.get("name", "")), _words(meta.get("subtitle", "")), _words(meta.get("keywords", ""))
    for a, b, la, lb in ((nw, sw, "name", "subtitle"), (nw, kw, "name", "keywords"), (sw, kw, "subtitle", "keywords")):
        dup = sorted(a & b)
        if dup:
            p.append(f"word(s) {dup} repeated across {la} and {lb}")

    # keyword field hygiene
    kwf = meta.get("keywords", "")
    if ", " in kwf or " ," in kwf:
        p.append("keywords must be comma-separated with NO spaces")
    toks = [t.strip() for t in kwf.lower().split(",") if t.strip()]
    if any(" " in t for t in toks):
        p.append("keywords must be single words (Apple combines them into phrases itself)")
    if len(set(toks)) != len(toks):
        p.append("duplicate tokens in keywords")
    bad = sorted(set(toks) & BANNED_KEYWORD_TOKENS)
    if bad:
        p.append(f"banned keyword tokens {bad} ('app', 'free', 'best' are ignored/penalised)")
    all_words = nw | sw | set(toks)
    plurals = sorted(t for t in toks if _is_plural_dupe(t, all_words))
    if plurals:
        p.append(f"plural duplicates in keywords {plurals} (Apple matches singular/plural already)")
    brands = sorted(all_words & COMPETITOR_BRANDS)
    if brands:
        p.append(f"competitor/Apple brand words {brands} (4.1 / 2.3.7 rejection risk)")
    if "&amp;" in (meta.get("name", "") + meta.get("subtitle", "")):
        p.append("use literal & not &amp;")

    # no hardcoded self-price anywhere (store renders regional price; mismatches get rejected)
    for k in ("description", "promotionalText", "subtitle"):
        if PRICE_RE.search(meta.get(k) or ""):
            p.append(f"{k} contains a hardcoded price — say 'pay once', never a number")
    if "app" in nw:
        p.append("the word 'app' in the name wastes 3 chars and is ignored for ranking")
    return Verdict(ok=not p, problems=p)


def validate_subscription_description(s: str) -> Verdict:
    """Subscription localization description caps at 55 chars — error index row."""
    return Verdict(ok=len(s) <= 55, problems=[] if len(s) <= 55 else [f"{len(s)} chars, max 55"])
