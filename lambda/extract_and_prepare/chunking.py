"""
Ciste funkcije za pripremu chunkova: deljenje teksta i serijalizacija tabela.

Namerno bez ijedne eksterne zavisnosti i bez I/O. Ekstrakcija iz PDF-a i DOCX-a
zavisi od PyMuPDF-a i python-docx-a i zivi odvojeno, u `extractor.py`. Ova
podela nije kozmeticka: zahvaljujuci njoj se pravila chunkovanja i tabela
testiraju lokalno, bez Docker-a i bez ijednog AWS resursa.

Sintaksa je namerno ogranicena na Python 3.9 iako Lambda vrti 3.12 — lokalni
interpreter na razvojnoj masini je 3.9, pa testovi rade bez podizanja venv-a.
"""

from typing import Any, List, Optional, Sequence

# Vrednosti iz specifikacije rada. Fiksne, ne heuristicke: merenja u evaluaciji
# moraju biti uporediva izmedju varijanti A i B, pa parametri chunkovanja ne
# smeju da se menjaju izmedju prolaza.
DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 50


def chunk_text(
    text: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> List[str]:
    """
    Deli tekst na komade fiksne duzine u ZNAKOVIMA, sa preklapanjem.

    Deli se po znakovima, ne po tokenima — tako je zapisano u specifikaciji i
    tako ostaje, jer je deterministicno i nezavisno od tokenizatora modela.

    Poslednji komad je po pravilu kraci od `size` i sa prethodnim deli `overlap`
    znakova. To znaci da moze nositi vrlo malo novog sadrzaja (npr. 26 znakova
    pri size=512, overlap=50). Prihvaceno svesno: alternativa bi bila spajanje
    repa sa prethodnim komadom, cime bi taj komad presao 512 znakova i prekrsio
    fiksnu duzinu.

    Prazan ili sam-beline tekst daje praznu listu, ne komad sa belinama —
    prazni chunkovi bi kasnije zavrsili kao besmisleni vektori u indeksu.
    """
    if size <= 0:
        raise ValueError("size mora biti pozitivan")
    if overlap < 0:
        raise ValueError("overlap ne sme biti negativan")
    if overlap >= size:
        raise ValueError("overlap mora biti manji od size, inace deljenje ne napreduje")

    text = text.strip()
    if not text:
        return []

    step = size - overlap
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        chunks.append(text[start : start + size])
        if start + size >= length:
            break
        start += step

    return chunks


def _cell_to_text(cell: Any) -> str:
    """Prazna celija i None postaju prazan string, da red ne izgubi kolonu."""
    if cell is None:
        return ""
    # Pipe bi razbio Markdown tabelu, pa se bekslesuje. Novi red u celiji se
    # pretvara u razmak iz istog razloga.
    return str(cell).replace("|", "\\|").replace("\n", " ").strip()


def table_to_markdown(
    rows: Sequence[Sequence[Any]],
    header: Optional[Sequence[Any]] = None,
) -> str:
    """
    Serijalizuje tabelu u Markdown, DETERMINISTICKI i bez VLM poziva.

    Tabele su born-digital, dakle struktura je vec poznata iz dokumenta.
    Trositi GPU na opisivanje necega sto se moze procitati tacno bilo bi i
    skupo i manje precizno — model bi mogao da pogresi broj, a parser ne moze.

    Ako `header` nije dat, uzima se prvi red. Redovi razlicite duzine se
    dopunjuju praznim celijama do najsireg reda, umesto da se odbace: bolje
    nepotpun red nego izgubljen podatak.
    """
    all_rows: List[Sequence[Any]] = []
    if header is not None:
        all_rows.append(header)
    all_rows.extend(rows)

    if not all_rows:
        return ""

    width = max(len(row) for row in all_rows)
    if width == 0:
        return ""

    def render(row: Sequence[Any]) -> str:
        cells = [_cell_to_text(c) for c in row]
        cells.extend([""] * (width - len(cells)))
        return "| " + " | ".join(cells) + " |"

    head = all_rows[0]
    body = all_rows[1:]

    lines = [render(head), "| " + " | ".join(["---"] * width) + " |"]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)
