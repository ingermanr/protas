"""Text helpers shared by the search feature."""

from __future__ import annotations

import re
import unicodedata

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase, accent free version of a text."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.casefold()


def tokens(text: str) -> list[str]:
    """Split a text into comparable words."""
    return [normalize(token) for token in TOKEN_PATTERN.findall(text)]


def terms(query: str) -> list[str]:
    """Split a query into search terms."""
    return [term for term in query.split() if term]


def build_match_query(query: str, column: str | None = None) -> str:
    """Build a safe FTS5 match expression out of a user query.

    Every term is quoted, so punctuation can never break the parser, and
    a trailing ``*`` asks for a prefix match.
    """
    parts: list[str] = []
    for raw in terms(query):
        prefix = raw.endswith("*")
        core = raw[:-1] if prefix else raw
        core = core.replace('"', '""')
        if not core:
            continue
        parts.append(f'"{core}"*' if prefix else f'"{core}"')

    if not parts:
        return ""

    expression = " AND ".join(parts)
    if column:
        return f"{column} : ({expression})"
    return expression


def matches(text: str, query_terms: list[str]) -> bool:
    """True when every term appears in the text, ignoring case and accents.

    The rules mirror the full text index: a plain term must match a whole
    word, and a term ending with ``*`` matches any word starting with it.
    """
    words = tokens(text)
    for term in query_terms:
        prefix = term.endswith("*")
        core = term[:-1] if prefix else term
        wanted = tokens(core)
        if not wanted:
            continue
        if prefix:
            if not any(word.startswith(wanted[0]) for word in words):
                return False
        elif not all(word in words for word in wanted):
            return False
    return True


def snippet(text: str, query_terms: list[str], width: int = 90) -> str:
    """Return the most relevant line of a text, trimmed to ``width``."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    best = lines[0]
    for line in lines:
        if matches(line, query_terms):
            best = line
            break

    if len(best) <= width:
        return best
    return best[: width - 1].rstrip() + "…"
