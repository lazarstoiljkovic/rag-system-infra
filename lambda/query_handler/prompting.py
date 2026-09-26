"""
Prompt za generator, varijante A i B ablacije. Ciste funkcije, bez mreze.

  A  (Opcija 2, MRAG taksonomija): generator vidi SAMO tekst. Za chunk slike to
     je njen caption — sirova slika se nikad ne salje.
  B  (Opcija 3): isto kao A, plus ORIGINALNA slika odmah posle svog captiona,
     dohvacena preko `image_ref`.

Najvaznije pravilo ovog modula: TEKST PROMPTA JE IDENTICAN U A I B. Varijanta B
samo dodaje slike; nijedna rec se ne menja, ne dodaje ni ne izostavlja. Da nije
tako, ablacija bi merila i razliku u tekstu, a ne samo "da li generator vidi
sliku". Pravilo je zakljucano testom.

Posledica istog pravila: sistemski prompt ne pominje slike. Recenica tipa
"koristi i prilozene slike" postojala bi samo u B — ili bi u A govorila o
necemu cega nema.

Ogranicenje servera: vLLM je pokrenut sa `--limit-mm-per-prompt {"image":4}`.
Ako je medju kontekstima vise od cetiri slike, originale dobijaju prve cetiri
po rangu, a ostale ostaju samo sa captionom (kao u A). Koje su slike stvarno
poslate upisuje se u `query-log`, da se u analizi zna gde je ogranicenje vazilo.
"""

import hashlib
from typing import Any, Dict, List, Sequence, Tuple

VARIANT_A = "A"
VARIANT_B = "B"
VARIANTS = (VARIANT_A, VARIANT_B)

# Isti broj kao `--limit-mm-per-prompt` u `ec2-userdata/vllm-bootstrap.sh`.
MAX_IMAGES = 4

SYSTEM_PROMPT = (
    "Ti si asistent za tehnicku dokumentaciju kompanije. Odgovaras na pitanja "
    "iskljucivo na osnovu prilozenih izvora.\n"
    "Pravila:\n"
    "- Ne koristi znanje van prilozenih izvora.\n"
    "- Ako izvori ne sadrze odgovor, napisi da odgovor nije pronadjen u "
    "dokumentaciji.\n"
    "- Posle svake tvrdnje navedi broj izvora u uglastim zagradama, npr. [2].\n"
    "- Odgovaraj na srpskom jeziku, kratko i precizno."
)

_TYPE_LABELS = {"text": "tekst", "table": "tabela", "image": "slika, opis"}


def prompt_fingerprint() -> str:
    """
    Kratak otisak sistemskog prompta, za `query-log`.

    Dva evaluaciona prolaza su uporediva samo ako su isla sa istim promptom.
    Otisak to cini proverljivim bez cuvanja celog prompta u svakom zapisu.
    """
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def context_header(context: Dict[str, Any]) -> str:
    """`[2] (tabela, kestrel-prirucnik-test, str. 1)` — isti u A i B."""
    parts = [_TYPE_LABELS.get(context.get("chunk_type"), "tekst")]
    if context.get("document_id"):
        parts.append(str(context["document_id"]))
    if context.get("page"):
        parts.append("str. {}".format(context["page"]))
    return "[{}] ({})".format(context["rank"], ", ".join(parts))


def images_to_attach(contexts: Sequence[Dict[str, Any]], variant: str) -> List[str]:
    """
    `image_ref`-ovi cije se ORIGINALNE slike salju generatoru.

    U A nijedan. U B prvih MAX_IMAGES chunkova-slika po rangu. Handler cita iz
    S3 tacno ove, i nijednu vise — nema smisla placati S3 poziv za sliku koja
    ne ide u prompt.
    """
    if variant == VARIANT_A:
        return []
    if variant != VARIANT_B:
        raise ValueError("nepoznata varijanta: {}".format(variant))
    refs: List[str] = []
    for context in contexts:
        ref = context.get("image_ref")
        if context.get("chunk_type") == "image" and ref and ref not in refs:
            refs.append(ref)
        if len(refs) == MAX_IMAGES:
            break
    return refs


def build_messages(
    question: str,
    contexts: Sequence[Dict[str, Any]],
    variant: str,
    image_urls: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Poruke za OpenAI-kompatibilan `/v1/chat/completions`.

    `image_urls` je `image_ref -> data URL` za slike koje je handler ucitao
    (u A je prazan). Vraca poruke i listu `image_ref`-ova koji su stvarno
    ugradjeni, redom.
    """
    if variant not in VARIANTS:
        raise ValueError("nepoznata varijanta: {}".format(variant))

    allowed = set(images_to_attach(contexts, variant))
    attached: List[str] = []
    content: List[Dict[str, Any]] = [{"type": "text", "text": "Izvori:"}]

    for context in contexts:
        text = (context.get("text") or "").strip()
        content.append({"type": "text", "text": "{}\n{}".format(context_header(context), text)})

        ref = context.get("image_ref")
        if ref in allowed and ref in image_urls and ref not in attached:
            content.append({"type": "image_url", "image_url": {"url": image_urls[ref]}})
            attached.append(ref)

    content.append({"type": "text", "text": "Pitanje: {}".format(question.strip())})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    return messages, attached


def text_only(messages: Sequence[Dict[str, Any]]) -> List[str]:
    """
    Svi tekstualni delovi poruka, redom. Sluzi testu (i proveri u radu) da je
    tekst u A i B identican.
    """
    texts: List[str] = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            texts.append(content)
            continue
        texts.extend(part["text"] for part in content if part.get("type") == "text")
    return texts
