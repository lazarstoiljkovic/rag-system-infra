"""
Sklapanje izvucenih elemenata u chunkove spremne za manifest.

Ovo je granica izmedju dva sveta: `extractor.py` zna za PyMuPDF i python-docx
i vraca sirove elemente, a ovde se od njih pravi ono sto ide u manifest i
kasnije u OpenSearch. Granica je namerno ovde jer se ceo ovaj korak testira
bez ijedne eksterne zavisnosti.

Sintaksa ogranicena na Python 3.9 iz istog razloga kao u `chunking.py`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, chunk_text, table_to_markdown

TEXT = "text"
TABLE = "table"
IMAGE = "image"

VALID_KINDS = (TEXT, TABLE, IMAGE)


@dataclass
class Element:
    """
    Jedan izvuceni element dokumenta, pre chunkovanja.

    `kind` odredjuje koje polje nosi sadrzaj:
      text   -> `text`
      table  -> `rows` (+ opciono `header`)
      image  -> `image_ref`, dok `text` ostaje prazan do captioning-a
    """

    kind: str
    page: Optional[int] = None
    text: str = ""
    rows: Sequence[Sequence[Any]] = field(default_factory=list)
    header: Optional[Sequence[Any]] = None
    image_ref: Optional[str] = None

    def __post_init__(self):
        if self.kind not in VALID_KINDS:
            raise ValueError(
                "nepoznat kind: {} (dozvoljeni: {})".format(self.kind, ", ".join(VALID_KINDS))
            )
        if self.kind == IMAGE and not self.image_ref:
            raise ValueError("element tipa image mora imati image_ref")


def build_chunks(
    elements: Sequence[Element],
    document_id: str,
    source_uri: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Dict[str, Any]]:
    """
    Pretvara elemente u listu chunkova za manifest.

    Grananje po tipu je srz ovog koraka:

      text   Deli se na vise chunkova fiksne duzine.
      table  Ostaje JEDAN chunk, serijalizovan u Markdown. Ne deli se — tabela
             presecena napola gubi zaglavlje i postaje besmislena pri pretrazi.
      image  Daje jedan chunk sa `image_ref` i PRAZNIM tekstom. Tekst popunjava
             `CaptionChunk` kasnije, pozivom ka VLM-u. Zato ovde nema nijednog
             GPU poziva — ekstrakcija je CPU-bound i mora ostati takva.

    `chunk_id` je determinisicki (`documentId#00000`), pa ponovni ingestion
    istog dokumenta prepisuje postojece dokumente u indeksu umesto da pravi
    duplikate.
    """
    chunks: List[Dict[str, Any]] = []

    def add(chunk_type: str, text: str, page: Optional[int], image_ref: Optional[str]):
        chunks.append(
            {
                "chunk_id": "{}#{:05d}".format(document_id, len(chunks)),
                "document_id": document_id,
                "source_uri": source_uri,
                "chunk_type": chunk_type,
                "text": text,
                "page": page,
                "image_ref": image_ref,
            }
        )

    for element in elements:
        if element.kind == TEXT:
            for piece in chunk_text(element.text, size=size, overlap=overlap):
                add(TEXT, piece, element.page, None)

        elif element.kind == TABLE:
            markdown = table_to_markdown(element.rows, header=element.header)
            if markdown:
                add(TABLE, markdown, element.page, None)

        elif element.kind == IMAGE:
            # Tekst ostaje prazan namerno: popunjava ga captioning korak.
            add(IMAGE, "", element.page, element.image_ref)

    return chunks


def pending_manifest(
    chunks: Sequence[Dict[str, Any]],
    document_id: str,
    source_uri: str,
) -> Dict[str, Any]:
    """
    Manifest koji `ExtractAndPrepare` ostavlja u S3, a Step Functions cita.

    `counts` nije ukras: po njemu se u `FinalizeIngestion` proverava da je broj
    indeksiranih chunkova jednak broju pripremljenih, bez ponovnog citanja
    celog manifesta.
    """
    counts = {TEXT: 0, TABLE: 0, IMAGE: 0}
    for chunk in chunks:
        counts[chunk["chunk_type"]] += 1

    return {
        "document_id": document_id,
        "source_uri": source_uri,
        "total": len(chunks),
        "counts": counts,
        "chunks": list(chunks),
    }
