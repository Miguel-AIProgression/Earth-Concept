import edi_exclusions
from edi_exclusions import is_edi_customer


def _set_edi(monkeypatch, names):
    edi_exclusions.load_edi_customers.cache_clear()
    monkeypatch.setattr(
        edi_exclusions, "load_edi_customers", lambda: frozenset(names)
    )


def test_geen_klant_is_niet_edi(monkeypatch):
    edi_exclusions.load_edi_customers.cache_clear()
    assert is_edi_customer(None) is False
    assert is_edi_customer("") is False


def test_onbekende_klant_niet_edi(monkeypatch):
    _set_edi(monkeypatch, set())
    assert is_edi_customer("Minor Hotels Europe") is False


def test_edi_klant_herkend(monkeypatch):
    _set_edi(monkeypatch, {"albert heijn b.v.", "jumbo supermarkten"})
    assert is_edi_customer("Albert Heijn B.V.") is True
    assert is_edi_customer("Jumbo Supermarkten") is True


def test_case_insensitive_en_whitespace(monkeypatch):
    _set_edi(monkeypatch, {"albert heijn b.v."})
    assert is_edi_customer("  ALBERT heijn B.V. ") is True


def test_comment_regels_genegeerd(tmp_path, monkeypatch):
    f = tmp_path / "e.txt"
    f.write_text("# kop\nKlant X\n\n# meer\nKlant Y\n", encoding="utf-8")
    monkeypatch.setattr(edi_exclusions, "EDI_FILE", f)
    edi_exclusions.load_edi_customers.cache_clear()
    assert edi_exclusions.load_edi_customers() == frozenset({"klant x", "klant y"})
    edi_exclusions.load_edi_customers.cache_clear()


def test_leeg_bestand_geeft_lege_set(tmp_path, monkeypatch):
    f = tmp_path / "e.txt"
    f.write_text("# alleen comments\n\n", encoding="utf-8")
    monkeypatch.setattr(edi_exclusions, "EDI_FILE", f)
    edi_exclusions.load_edi_customers.cache_clear()
    assert edi_exclusions.load_edi_customers() == frozenset()
    edi_exclusions.load_edi_customers.cache_clear()
