"""
Grupisanje chunkova u batch-eve i spajanje sa vektorima. Ciste funkcije.

Specifikacija izricito trazi BATCH poziv, ne poziv po chunk-u. Razlog je
merljiv: po pozivu se placa rezija HTTP-a i prolaz kroz model, pa bi hiljadu
chunkova znacilo hiljadu odlazaka na GPU umesto tridesetak.
"""

from typing import Any, Dict, Iterable, Iterator, List, Sequence

# Kompromis izmedju broja poziva i velicine tela zahteva. Prevelik batch
# produzava jedan poziv preko Lambda timeout-a i tezi je za ponovni pokusaj;
# premali vraca problem koji batch treba da resi.
DEFAULT_BATCH_SIZE = 32


def chunked(items: Sequence[Any], size: int = DEFAULT_BATCH_SIZE) -> Iterator[List[Any]]:
    """Deli niz na liste duzine `size`; poslednja je krata ako ne deli tacno."""
    if size <= 0:
        raise ValueError("size mora biti pozitivan")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def embeddable_text(chunk: Dict[str, Any]) -> str:
    """
    Tekst koji ide u embedding model.

    Za chunk poreklom od slike to je CAPTION, jer je on jedini tekstualni
    nosilac te slike. Ovo je mesto na kome se vidi da sistem pretrazuje
    iskljucivo tekstualni vektorski prostor: i slike se embeduju kroz isti
    tekstualni model, preko svog opisa. Nema zajednicke vektorizacije teksta
    i slike.
    """
    return chunk.get("text") or ""


def attach_embeddings(
    chunks: Sequence[Dict[str, Any]],
    vectors: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Spaja chunkove sa odgovarajucim vektorima, po REDOSLEDU.

    Servis vraca rezultate u redosledu ulaza, pa je poklapanje pozicijsko.
    Zato se duzine proveravaju: tiho krace poklapanje bi vezalo vektor za
    pogresan chunk, a takva greska se u indeksu ne vidi — samo pretraga pocne
    da vraca besmislice.
    """
    if len(chunks) != len(vectors):
        raise ValueError(
            "broj chunkova ({}) i vektora ({}) se ne poklapa".format(
                len(chunks), len(vectors)
            )
        )

    out: List[Dict[str, Any]] = []
    for chunk, vector in zip(chunks, vectors):
        enriched = dict(chunk)
        enriched["dense_vector"] = vector["dense"]
        enriched["sparse_weights"] = vector.get("sparse") or {}
        out.append(enriched)
    return out


def drop_empty(chunks: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Izbacuje chunkove bez teksta.

    Chunk slike kojoj captioning nije uspeo ostaje praznog teksta. Njegov
    embedding bio bi vektor praznog stringa — tacka u prostoru koja nista ne
    znaci, ali se pojavljuje u rezultatima pretrage. Bolje ga nema.
    """
    return [c for c in chunks if embeddable_text(c).strip()]
