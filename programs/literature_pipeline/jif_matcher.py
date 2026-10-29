"""JIF(Journal Impact Factor)の参照TSVと、論文の雑誌・発行年との照合、JIFのtier(階層)。

`scripts/backfill_jif.py`・`scripts/match_jif.py`・`scripts/jif_reference_add.py` が使う。
発行年と同じ年のJIFだけを使い(ISSN/eISSN + 年 → 誌名 + 年の順)、別の年の値で埋めない。
参照TSVの形式は `docs/data_dictionary/jif_reference_v1.md`。
(旧世代のTSVパイプライン `pipeline.py` から、2026-10 に切り出した。)
"""
from __future__ import annotations

import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

JIF_REFERENCE_REQUIRED = ("jif_data_year", "jif")
JIF_FIELDS = (
    "jif",
    "jif_data_year",
    "jcr_release_year",
    "jif_source",
    "jif_reference_version",
    "jif_match_status",
    "jif_match_key",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as source:
        return [dict(row) for row in csv.DictReader(source, delimiter="\t")]


def normalize_issn(value: str) -> str:
    return re.sub(r"[^0-9X]", "", (value or "").upper())


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def loose_title(value: str) -> str:
    """Journal-title key that survives PubMed's decorations.

    PubMed stores "The Journal of urology" and "Journal of clinical oncology : official journal of
    the American Society of Clinical Oncology", while JCR (and the ISSN-less All Years exports,
    which match on title alone) say "JOURNAL OF UROLOGY". Drop a leading "The" and everything
    after a colon, and treat "&" as "and".
    """
    text = (value or "").split(":")[0] or (value or "")
    text = re.sub(r"^\s*the\s+", "", text, flags=re.IGNORECASE).replace("&", " and ")
    return normalize_title(text)


def title_keys(value: str) -> tuple[str, ...]:
    """Strict key first, then the loose one (deduplicated, empty keys dropped)."""
    return tuple(dict.fromkeys(key for key in (normalize_title(value), loose_title(value)) if key))


class JIFMatcher:
    def __init__(self, reference: Path | Sequence[Path] | None):
        if reference is None:
            self.reference_paths: list[Path] = []
        elif isinstance(reference, Path):
            self.reference_paths = [reference]
        else:
            self.reference_paths = list(reference)
        self.rows: list[dict[str, str]] = []
        self.by_identifier: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.by_title: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.titles_seen: set[str] = set()
        for reference_path in self.reference_paths:
            reference_rows = read_tsv(reference_path)
            self.rows.extend(reference_rows)
        if self.rows:
            missing = [field for field in JIF_REFERENCE_REQUIRED if field not in self.rows[0]]
            if missing:
                raise ValueError(f"JIF reference lacks required columns: {', '.join(missing)}")
        years = [int(row["jif_data_year"]) for row in self.rows if row.get("jif_data_year", "").strip().isdigit()]
        self.latest_data_year = max(years, default=0)
        for row in self.rows:
            year = row.get("jif_data_year", "").strip()
            for identifier in (row.get("issn", ""), row.get("eissn", "")):
                normalized = normalize_issn(identifier)
                if normalized and year:
                    bucket = self.by_identifier.setdefault((normalized, year), [])
                    # ISSN == eISSN for some journals; without this the same row lands twice
                    # and match() reports it as ambiguous_match against itself.
                    if not any(row is existing for existing in bucket):
                        bucket.append(row)
            for title_field in ("journal_title", "journal_abbreviation"):
                for title in title_keys(row.get(title_field, "")):
                    self.titles_seen.add(title)
                    if year:
                        bucket = self.by_title.setdefault((title, year), [])
                        if row not in bucket:
                            bucket.append(row)

    @staticmethod
    def _collapse_agreeing(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        """Rows for the same journal-year that carry the same JIF are one fact, not an ambiguity.

        Happens when a later JCR export adds categories for a year already loaded (a journal listed
        under several categories appears in both files). Genuinely different JIFs stay separate, so
        they still report ambiguous_match rather than silently picking one. Of agreeing rows the
        newest reference_version is kept, so the audit trail points at the latest source.
        """
        unique: dict[tuple[str, str], dict[str, str]] = {}
        for row in candidates:
            try:
                jif = str(Decimal(row.get("jif", "").strip()).normalize())  # "2" and "2.0" agree
            except InvalidOperation:
                jif = row.get("jif", "").strip()
            key = (jif, row.get("jif_data_year", "").strip())
            current = unique.get(key)
            if current is None or row.get("reference_version", "") > current.get("reference_version", ""):
                unique[key] = row
        return list(unique.values())

    def _lookup(self, article: Mapping[str, str], year: str) -> tuple[list[dict[str, str]], str]:
        for field in ("issn", "eissn"):
            identifier = normalize_issn(article.get(field, ""))
            if identifier:
                matches = self.by_identifier.get((identifier, year), [])
                if matches:
                    return matches, f"{field}:{identifier}"
        for field in ("journal_title", "journal_abbrev"):
            for title in title_keys(article.get(field, "")):
                matches = self.by_title.get((title, year), [])
                if matches:
                    return matches, f"{field}:{title}"
        return [], ""

    def match(self, article: Mapping[str, str]) -> dict[str, str]:
        year = article.get("publication_year", "").strip()
        empty = {field: "" for field in JIF_FIELDS}
        empty["jif_data_year"] = year
        if not self.reference_paths:
            empty["jif_match_status"] = "reference_not_loaded"
            return empty
        if not year:
            empty["jif_match_status"] = "publication_year_missing"
            return empty

        candidates, match_key = self._lookup(article, year)
        status = "exact"
        if not candidates and year.isdigit() and int(year) > self.latest_data_year:
            # The JIF of this publication year is not out yet (the newest JCR year is older). Borrow the
            # journal's previous-year JIF as a provisional value; a later JCR release replaces it with
            # the confirmed one. Never done for a year that is already covered: there a missing row is a
            # fact (not indexed / suppressed) and would stay "provisional" forever.
            prior, prior_key = self._lookup(article, str(int(year) - 1))
            prior = [row for row in self._collapse_agreeing(prior) if row.get("jif", "").strip()]
            if len(prior) == 1:
                candidates, match_key, status = prior, prior_key, "prior_year"

        candidates = self._collapse_agreeing(candidates)
        if len(candidates) > 1:
            empty["jif_match_status"] = "ambiguous_match"
            empty["jif_match_key"] = match_key
            return empty
        if not candidates:
            identifiers = [normalize_issn(article.get(key, "")) for key in ("issn", "eissn")]
            journal_exists = any(
                identifier and any(key[0] == identifier for key in self.by_identifier)
                for identifier in identifiers
            ) or any(  # title-only references (single-journal "All Years" exports carry no ISSN)
                title in self.titles_seen
                for field in ("journal_title", "journal_abbrev")
                for title in title_keys(article.get(field, ""))
            )
            empty["jif_match_status"] = "year_not_found" if journal_exists else "journal_not_found"
            return empty

        reference = candidates[0]
        empty.update({
            "jif": reference.get("jif", ""),
            "jif_data_year": reference.get("jif_data_year", year),
            "jcr_release_year": reference.get("jcr_release_year", ""),
            "jif_source": reference.get("source", ""),
            "jif_reference_version": reference.get("reference_version", ""),
            "jif_match_status": status if reference.get("jif", "").strip() else "suppressed_or_unavailable",
            "jif_match_key": match_key,
        })
        return empty


def jif_tier(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if number < 1:
        return "low"
    if number < 3:
        return "moderate"
    if number < 5:
        return "high"
    return "very-high"
