"""EDI-klantuitsluiting: klanten die via EDI lopen moeten door onze automatisering
worden genegeerd. Namen komen uit edi_customers.txt (1 naam per regel, # voor comment)."""

from functools import lru_cache
from pathlib import Path

EDI_FILE = Path(__file__).parent / "edi_customers.txt"


@lru_cache(maxsize=1)
def load_edi_customers() -> frozenset[str]:
    if not EDI_FILE.exists():
        return frozenset()
    names = set()
    for line in EDI_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line.lower())
    return frozenset(names)


def is_edi_customer(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() in load_edi_customers()
