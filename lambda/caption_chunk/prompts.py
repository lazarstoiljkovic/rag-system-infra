"""
Promptovi za captioning slika. Ciste konstante i cist izbor — bez mreze.

Specifikacija rada trazi DVA RAZLICITA prompta, ne jedan opsti. Razlog je
merni, ne estetski: varijanta A ablacije daje generatoru iskljucivo caption
umesto slike, pa je caption jedini nosilac vizuelne informacije. Opsti prompt
tipa "opisi sliku" daje opis koji zvuci lepo a ne sadrzi podatke potrebne za
odgovor — recimo, kaze da grafikon "prikazuje rast" bez ijedne vrednosti sa
ose. Varijanta A bi tada gubila od varijante B zbog losih promptova, a ne zbog
odsustva slike, i ablacija bi merila pogresnu stvar.
"""

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
    "Ovo je dijagram arhitekture softverskog sistema. Opisi ga precizno i "
    "iscrpno, na srpskom jeziku:\n"
    "1. Navedi SVE komponente i njihove tacne nazive onako kako pisu na slici.\n"
    "2. Za svaku vezu navedi koje dve komponente spaja i KOJI JE PRAVAC "
    "strelice (od koje ka kojoj).\n"
    "3. Navedi tip veze ako je oznacen (HTTP, gRPC, red poruka, i slicno).\n"
    "4. Navedi grupisanja i granice ako postoje (VPC, podmreza, klaster).\n"
    "Ne tumaci i ne dodaji zakljucke kojih nema na slici."
)

# Kod grafikona je kriticna TACNA VREDNOST. Opis bez brojeva je za varijantu A
# bezvredan, jer se iz njega ne moze odgovoriti ni na jedno kvantitativno pitanje.
CHART_PROMPT = (
    "Ovo je grafikon sa podacima. Opisi ga precizno i iscrpno, na srpskom "
    "jeziku:\n"
    "1. Navedi tip grafikona (linijski, stubicasti, tortni, i slicno).\n"
    "2. Navedi naziv i jedinicu obe ose, kao i opseg vrednosti.\n"
    "3. Navedi TACNE VREDNOSTI svake tacke ili stubica koje mozes procitati, "
    "zajedno sa pripadajucom oznakom na osi.\n"
    "4. Navedi legendu i naziv svake serije ako ih ima.\n"
    "Ako neku vrednost ne mozes pouzdano procitati, napisi da je necitljiva "
    "umesto da je pogodis."
)


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
