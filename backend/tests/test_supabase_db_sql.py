"""ทดสอบ helper ของ supabase_db (ไม่ต้องมี Postgres จริง)"""
from app.supabase_db import _parse_filter, _parse_order, _parse_select, _where


def test_parse_filter_ops():
    assert _parse_filter("eq.1") == ("=", "1")
    assert _parse_filter("neq.") == ("<>", "")
    assert _parse_filter("gte.2024-01-01") == (">=", "2024-01-01")
    assert _parse_filter("not.in.(angry,sad)") == ("NOT IN", ["angry", "sad"])
    assert _parse_filter("in.(a,b)") == ("IN", ["a", "b"])


def test_parse_select_nested_moods():
    cols, nested = _parse_select("id,name,voice_moods(*)")
    assert nested == "voice_moods"
    assert "id" in cols and "name" in cols
    assert "voice_moods" not in cols


def test_parse_order():
    assert _parse_order("updated_at.desc") == " ORDER BY updated_at DESC"
    assert _parse_order("run_date.desc") == " ORDER BY run_date DESC"


def test_where_builds_and():
    sql, args = _where({"project_id": "eq.p1", "edited": "eq.true", "select": "id"})
    assert "project_id = %s" in sql
    assert "edited = %s" in sql
    assert args == ["p1", "true"]
