from civic_hub.collect import collect_source
from civic_hub.sources import Item, Source, to_days
from civic_hub.store import DB


def src(track_removed=True):
    return Source("t-src", "Test", "ca", "test", "https://example.org", lambda: [], track_removed=track_removed)


def test_to_days():
    assert to_days("33 days") == 33
    assert to_days("3 weeks") == 21
    assert to_days("4 months") == 120
    assert to_days("No processing time available") is None
    assert to_days(None) is None


def test_baseline_then_changes(tmp_path):
    db = DB(f"sqlite:///{tmp_path}/t.db")
    db.migrate()
    s = src()
    # first run = baseline: stored, no change events
    n, c = collect_source(db, s, [Item("a", "A", "10 days", number=10), Item("b", "B", "5 days", number=5)])
    db.commit()
    assert (n, c) == (2, 0)
    # second run: a changed, b removed, c new
    n, c = collect_source(db, s, [Item("a", "A", "12 days", number=12), Item("c", "C", "1 day", number=1)])
    db.commit()
    kinds = sorted(r["change_type"] for r in db.rows("SELECT change_type FROM changes"))
    assert kinds == ["changed", "new", "removed"]
    ch = db.rows("SELECT old_number,new_number FROM changes WHERE change_type='changed'")[0]
    assert (ch["old_number"], ch["new_number"]) == (10, 12)
    # unchanged run logs nothing
    _, c = collect_source(db, s, [Item("a", "A", "12 days"), Item("c", "C", "1 day")])
    assert c == 0
    # history kept
    assert len(db.rows("SELECT * FROM observations WHERE item_key='a'")) == 2


def test_rotating_feed_does_not_report_removed(tmp_path):
    db = DB(f"sqlite:///{tmp_path}/t.db")
    db.migrate()
    s = src(track_removed=False)
    collect_source(db, s, [Item("n1", "News 1", {"p": 1})])
    _, c = collect_source(db, s, [Item("n2", "News 2", {"p": 2})])
    assert c == 1
    assert db.rows("SELECT change_type FROM changes")[0]["change_type"] == "new"
