"""
Izvodjenje identifikatora i S3 kljuceva. Ciste funkcije, bez boto3.

Izdvojeno iz `handler.py` da bi se pravila imenovanja testirala lokalno.
Imena nisu kozmetika: `document_id` ulazi u `chunk_id`, a `chunk_id` je
_id dokumenta u OpenSearch-u, pa od determinizma ovih funkcija zavisi da li
ponovni ingestion prepisuje postojece dokumente ili pravi duplikate.
"""

import os
import re
from typing import Tuple

RAW_PREFIX = "raw/"
IMAGES_PREFIX = "images/"
MANIFEST_PREFIX = "manifests/"

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def document_id_from_key(key: str) -> str:
    """
    `raw/Prirucnik v2 (final).pdf` -> `Prirucnik_v2_final.pdf` bez ekstenzije.

    Sve sto nije slovo, cifra, tacka, crta ili donja crta postaje jedna donja
    crta. Cilj nije lepota nego STABILNOST: isti kljuc uvek daje isti id, pa je
    ponovni ingestion idempotentan.
    """
    name = key[len(RAW_PREFIX):] if key.startswith(RAW_PREFIX) else key
    name = os.path.basename(name)
    name = os.path.splitext(name)[0]
    cleaned = _SAFE.sub("_", name).strip("._")
    # Trazi se bar jedan alfanumericki znak. Bez ove provere kljuc poput
    # `raw/.pdf` prolazi kao document_id ".pdf", jer os.path.splitext vodecu
    # tacku smatra imenom a ne ekstenzijom. Isto vazi za `raw/.DS_Store`, koji
    # bi napravio prefiks `manifests/.DS_Store/`.
    if not any(c.isalnum() for c in cleaned):
        raise ValueError("iz kljuca '{}' nije moguce izvesti document_id".format(key))
    return cleaned


def image_key(document_id: str, index: int, suffix: str) -> str:
    """Kljuc slike u `images/`. Ovo je vrednost koja zavrsi u `image_ref`."""
    ext = (suffix or "png").lstrip(".").lower()
    ext = _SAFE.sub("", ext) or "png"
    return "{}{}/{:03d}.{}".format(IMAGES_PREFIX, document_id, index, ext)


def manifest_keys(document_id: str) -> Tuple[str, str]:
    """
    Dva objekta, namerno odvojena:

      chunks.json    CIST JSON NIZ, bez omotaca. Takav ga cita DistributedMap
                     preko ItemReader-a. Omotac sa metapodacima bi ga pokvario.
      manifest.json  metapodaci i brojaci, za FinalizeIngestion i dijagnostiku.

    Podela postoji zbog tvrdog limita Step Functions-a od 256KB na velicinu
    stanja: lista chunkova ne sme da prodje kroz izlaz Lambde, nego samo
    pokazivac na nju.
    """
    base = "{}{}/".format(MANIFEST_PREFIX, document_id)
    return base + "chunks.json", base + "manifest.json"
