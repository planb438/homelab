import os
from datetime import date
from sitekit import hqbackup


class Resp:
    def __init__(self, code, content=b"x"): self.status_code, self.content = code, content


class Sess:
    def get(self, url, params=None, timeout=None):
        return Resp(403) if "BADBADBADBADBADBADBAD" in url else Resp(200, b"PK-xlsx")


def test_parse():
    s = hqbackup.parse_sheets("# c\nParkingClub — HQ|15vDw2on9SefyBm-aA7lXj7iSaSlQjWY0dPS2svkqZxY\nbad line\nX|short")
    assert s == [("ParkingClub — HQ", "15vDw2on9SefyBm-aA7lXj7iSaSlQjWY0dPS2svkqZxY")]


def test_run_and_prune(tmp_path):
    old = tmp_path / "2020-01-01"; old.mkdir()
    ok, failed = hqbackup.run(Sess(), [("A HQ", "A" * 30), ("B", "BADBADBADBADBADBADBAD")], str(tmp_path), 30, date(2026, 11, 26))
    assert ok == 1 and failed == ["B"]
    assert (tmp_path / "2026-11-26" / "A_HQ.xlsx").read_bytes() == b"PK-xlsx"
    assert not old.exists()
