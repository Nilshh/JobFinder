"""Unit-Tests für Helfer in server.py. Testen reine Funktionen ohne Flask-Context."""
import os
import sys
import tempfile

# Testumgebung vor Import des Moduls setzen
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import expand_titles, _keyword_match_score, _job_key, _merge_kw


def test_expand_titles_adds_synonyms():
    result = expand_titles(["CTO"])
    assert "CTO" in result
    assert "Chief Technology Officer" in result
    assert "VP Engineering" in result


def test_expand_titles_case_insensitive():
    result = expand_titles(["cto"])
    assert any("Technology" in t for t in result)


def test_expand_titles_no_duplicates():
    result = expand_titles(["CTO", "VP of Engineering"])
    # CTO und VP of Engineering teilen sich Synonyme, aber keine Duplikate
    assert len(result) == len(set(result))


def test_expand_titles_unknown_term():
    result = expand_titles(["Komponist"])
    assert result == ["Komponist"]


def test_keyword_match_score_no_overlap():
    score = _keyword_match_score("CTO mit Python-Erfahrung", "Lkw-Fahrer gesucht")
    assert 0.0 <= score <= 0.3


def test_keyword_match_score_high_overlap_beats_no_overlap():
    profile = "Erfahrener CTO mit Python, Kubernetes, PostgreSQL, Cloud-Architektur"
    job_match = "Wir suchen einen CTO mit Python-Erfahrung und Kubernetes-Know-how"
    job_nomatch = "Lkw-Fahrer Klasse C gesucht für regionale Touren"
    score_high = _keyword_match_score(profile, job_match)
    score_low  = _keyword_match_score(profile, job_nomatch)
    assert score_high > score_low
    assert score_high > 0.0


def test_keyword_match_score_empty():
    assert _keyword_match_score("", "etwas") == 0.0
    assert _keyword_match_score("etwas", "") == 0.0


def test_job_key_uses_url():
    key = _job_key({"redirect_url": "https://example.com/job/123"})
    assert key == "https://example.com/job/123"


def test_job_key_falls_back_to_title_and_company():
    key = _job_key({"title": "CTO", "company": {"display_name": "Acme"}})
    assert "CTO" in key
    assert "Acme" in key


def test_job_key_truncates():
    long_url = "https://example.com/" + "x" * 300
    key = _job_key({"redirect_url": long_url})
    assert len(key) <= 180


def test_merge_kw_dedups_and_keeps_order():
    result = _merge_kw(["CTO", "CIO"], ["CIO", "CDO"])
    assert result == ["CTO", "CIO", "CDO"]


def test_merge_kw_empty_lists():
    assert _merge_kw([], []) == []
    assert _merge_kw(["a"], []) == ["a"]
    assert _merge_kw([], ["b"]) == ["b"]
