"""
Promptovi za captioning slika. Ciste konstante i cist izbor — bez mreze.

Specifikacija rada trazi DVA RAZLICITA prompta, ne jedan opsti. Razlog je
merni, ne estetski: varijanta A ablacije daje generatoru iskljucivo caption
umesto slike, pa je caption jedini nosilac vizuelne informacije. Opsti prompt
tipa "opisi sliku" daje opis koji zvuci lepo a ne sadrzi podatke potrebne za
odgovor — recimo, kaze da grafikon "prikazuje rast" bez ijedne vrednosti sa
ose. Varijanta A bi tada gubila od varijante B zbog losih promptova, a ne zbog
odsustva slike, i ablacija bi merila pogresnu stvar.

Oba prompta odvajaju UPUTSTVA od OBLIKA ODGOVORA (sablon sa kratkim poljima).
Prva verzija je nabrajala zahteve kao numerisanu listu, i integracioni prolaz
2026-09-26 je pokazao dve mane:

  - Model je "odjekivao" prompt: caption grafikona je ponavljao naslove
    zahteva ("TACNE VREDNOSTI svake tacke...") i zavrsnu recenicu o
    necitljivim vrednostima. Taj tekst ulazi u embedding i BM25 kao sum, a
    isti je u svakom captionu — pa svi captioni lice jedni na druge.
  - Caption dijagrama je izostavio jednu od sest strelica (ruter -> cvor A),
    iako je smer ostalih pet bio tacan.

Sablon resava prvo, a pravilo "jedna stavka po strelici" uz zavrsnu proveru
cilja drugo. Drugi prolaz (isti dan) je potvrdio da je izostavljena strelica
resena, ali je model posle popunjenog sablona prepisao ceo blok "Pravila:".
Zato su pravila sada PRE sablona (sablon je poslednji, pa ga model nastavlja),
a `clean_caption` deterministicki odseca sve od reda "Pravila:" — ako se odjek
ipak pojavi, ne sme stici do embedding-a.
"""

import re

DIAGRAM = "diagram"
CHART = "chart"

# Reci koje u odgovoru modela znace "grafik". "graf" nije podniz reci
# "dijagram" (tamo je "gram"), pa nema laznog pogotka.
CHART_MARKERS = ("grafik", "graf", "chart", "stubic", "tortni", "linijski")

CLASSIFY_PROMPT = (
    "Da li je ovo dijagram arhitekture (komponente povezane strelicama) "
    "ili grafikon sa podacima (linijski, stubicasti, tortni)? "
    "Odgovori iskljucivo jednom recju: dijagram ili grafikon."
)

# Trazi se ono sto se iz slike NE MOZE rekonstruisati kasnije: imena komponenti,
# tip veze i PRAVAC strelica. Pravac je cest izvor gresaka u RAG odgovorima, jer
# "A zove B" i "B zove A" imaju istu listu komponenti.
DIAGRAM_PROMPT = (
    "Opisi dijagram arhitekture softverskog sistema sa slike, na srpskom jeziku.\n"
    "Pravila:\n"
    "- Za SVAKU strelicu na slici napisi tacno jednu stavku pod Veze. PRAVAC je "
    "od komponente iz koje strelica izlazi ka komponenti u koju ulazi.\n"
    "- Pre nego sto zavrsis, proveri da nijedna strelica nije izostavljena.\n"
    "- Tip veze (HTTP, gRPC, red poruka i slicno) navedi samo ako pise na slici.\n"
    "- Ne tumaci i ne dodaji nista cega nema na slici.\n\n"
    "Odgovor napisi tacno u ovom obliku, bez uvoda i bez ponavljanja ovih "
    "uputstava:\n\n"
    "Komponente: <nazivi svih komponenti, tacno kako pisu na slici>\n"
    "Veze:\n"
    "- <izvor> -> <odrediste>: <oznaka veze sa slike, ili bez oznake>\n"
    "Granice: <grupisanja i granice (VPC, podmreza, klaster) i koje komponente "
    "obuhvataju, ili nema>"
)

# Kod grafikona je kriticna TACNA VREDNOST. Opis bez brojeva je za varijantu A
# bezvredan, jer se iz njega ne moze odgovoriti ni na jedno kvantitativno pitanje.
CHART_PROMPT = (
    "Opisi grafikon sa slike, na srpskom jeziku.\n"
    "Pravila:\n"
    "- Navedi TACNE VREDNOSTI za svaku tacku ili stubic: ispisane na grafikonu, "
    "a ako nisu ispisane, procitane sa ose.\n"
    "- Nazive, oznake i jedinice prepisi tacno kako pisu na slici.\n"
    "- Ako vrednost ne mozes pouzdano procitati, upisi necitljivo umesto da je "
    "pogodis.\n\n"
    "Odgovor napisi tacno u ovom obliku, bez uvoda i bez ponavljanja ovih "
    "uputstava:\n\n"
    "Naslov: <naslov grafikona, ili nema>\n"
    "Tip: <linijski, stubicasti, tortni, ili drugi>\n"
    "X osa: <naziv i jedinica>\n"
    "Y osa: <naziv, jedinica i opseg>\n"
    "Vrednosti:\n"
    "- <oznaka na osi ili u legendi>: <vrednost>\n"
    "Legenda: <nazivi serija, ili nema>"
)


# Red kojim pocinje odjek uputstava u odgovoru modela.
_ECHO = re.compile(r"^\s*\**\s*pravila\s*\**\s*:", re.IGNORECASE | re.MULTILINE)


def clean_caption(raw: str) -> str:
    """
    Odseca odjek uputstava: sve od prvog reda koji pocinje sa "Pravila:".

    Deterministicka zastita iza prompta. Odjek je sum koji je ISTI u svakom
    captionu, pa bi u embedding-u i BM25 cinio da svi captioni lice jedni na
    druge — sto je gore od obicnog suma.
    """
    text = raw or ""
    match = _ECHO.search(text)
    if match:
        text = text[: match.start()]
    return text.strip()


def classify(raw_answer: str) -> str:
    """
    Svodi slobodan odgovor modela na `diagram` ili `chart`.

    Podrazumevano `diagram`: korpus je tehnicka dokumentacija, gde su dijagrami
    arhitekture cesci. Kad je klasifikacija neodlucna, jeftinije je pogresiti u
    korist cesceg slucaja.
    """
    text = (raw_answer or "").strip().lower()
    for marker in CHART_MARKERS:
        if marker in text:
            return CHART
    return DIAGRAM


def prompt_for(kind: str) -> str:
    return CHART_PROMPT if kind == CHART else DIAGRAM_PROMPT
