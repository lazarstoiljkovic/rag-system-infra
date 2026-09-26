"""
Generator test dokumenta za integracioni prolaz ingestion toka (faza 4).

Pravi jedan mali PDF koji pogadja SVE TRI grane ekstrakcije:

  tekst    vise od 512 znakova, da chunking napravi vise chunkova sa preklopom
  tabela   born-digital, sa iscrtanim linijama — `page.find_tables()` u
           podrazumevanoj strategiji trazi upravo linije
  slike    RASTERSKE (PNG ugradjen u PDF), jer `page.get_images()` ne vidi
           vektorske crteze. Jedan dijagram arhitekture i jedan grafikon, da se
           provere oba captioning prompta.

Sadrzaj je sinteticki: fiktivna kompanija, fiktivan proizvod, izmisljene
vrednosti (port 7419, retencija 96h, pad propusnosti u v3.1...). Namerno —
model ne sme moci da pogodi odgovor bez retrievala.

Zavisnosti: PyMuPDF==1.24.14 (ista verzija kao u Lambdi) i matplotlib.
Nisu deo repoa; pokretanje iz privremenog venv-a:

    python3 -m venv /tmp/corpus-venv
    /tmp/corpus-venv/bin/pip install PyMuPDF==1.24.14 matplotlib
    /tmp/corpus-venv/bin/python corpus/generate_test_document.py
"""

import os
import tempfile

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "test", "kestrel-prirucnik-test.pdf")

# DejaVu dolazi uz matplotlib i ima sve srpske znakove; Base14 fontovi PDF-a
# nemaju slova sa kvacicama.
_TTF = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
FONT = os.path.join(_TTF, "DejaVuSans.ttf")
FONT_BOLD = os.path.join(_TTF, "DejaVuSans-Bold.ttf")

TITLE = "Kestrel 3 — Priručnik za operatere"
SUBTITLE = "Interni dokument · Vranac Sistemi d.o.o. · revizija 3.1-b"

INTRO = (
    "Kestrel je distribuirani red poruka koji Vranac Sistemi razvija za interne "
    "servise za obradu porudžbina. Za razliku od opštih brokera, Kestrel čuva "
    "poruke u segmentisanom dnevniku na lokalnom disku svakog skladišnog čvora, "
    "a redosled isporuke garantuje samo unutar jedne particije. Klijenti se "
    "nikada ne povezuju direktno na skladišne čvorove: sav saobraćaj ide preko "
    "komponente Kestrel Gateway, koja proverava identitet klijenta i prosleđuje "
    "zahtev ruteru particija.\n\n"
    "Ruter particija određuje vodeći čvor za svaku particiju. Upis se smatra "
    "potvrđenim tek kada ga vodeći čvor zapiše u dnevnik; replikacija ka "
    "pratećem čvoru je asinhrona i zato ne produžava latenciju upisa. Posledica "
    "je da pri otkazu vodećeg čvora mogu nestati poruke potvrđene u poslednjih "
    "nekoliko stotina milisekundi. Tim za platformu je ovaj rizik prihvatio "
    "u zamenu za propusnost, uz uslov da se kritični tokovi (plaćanja) oslanjaju "
    "na idempotentne potrošače.\n\n"
    "Nadzorni servis Sova ne proziva čvorove. Svaki skladišni čvor sam šalje "
    "metrike Sovi na svakih 15 sekundi; ako Sova ne primi metrike od čvora "
    "duže od 45 sekundi, proglašava ga nedostupnim i obaveštava dežurnog "
    "inženjera. Parametri iz tabele ispod važe za verziju 3.1 i menjaju se "
    "isključivo kroz konfiguracioni repozitorijum, nikada ručno na čvoru."
)

TABLE_CAPTION = "Tabela 1. Ključni konfiguracioni parametri (Kestrel 3.1)"
TABLE_ROWS = [
    ["Parametar", "Podrazumevano", "Opis"],
    ["kestrel.gateway.port", "7419", "gRPC port komponente Kestrel Gateway"],
    ["kestrel.replication.factor", "2", "Broj kopija svake particije"],
    ["kestrel.segment.max_mb", "768", "Veličina segmenta pre rotacije"],
    ["kestrel.retention.hours", "96", "Čuvanje potvrđenih poruka"],
    ["kestrel.ack.timeout_ms", "2750", "Rok za potvrdu pre ponovne isporuke"],
]

PAGE2_TEXT = (
    "Slika 1 prikazuje tok jedne poruke kroz klaster. Obratiti pažnju na smer "
    "strelica između skladišnih čvorova i Sove: metrike se guraju ka nadzoru, "
    "a ne povlače iz njega.\n\n"
    "Slika 2 prikazuje propusnost izmerenu na referentnom klasteru od tri "
    "čvora. Pad u verziji 3.1 posledica je uvođenja kontrolne sume nad svakim "
    "segmentom; tim ga smatra privremenim i planira ispravku u verziji 3.2."
)

# Vrednosti grafikona, u hiljadama poruka u sekundi.
THROUGHPUT = [("2.1", 18.4), ("2.2", 21.8), ("3.0", 30.2), ("3.1", 27.9)]


def draw_architecture(path):
    """
    Dijagram arhitekture. Nosi ono sto caption mora da uhvati: nazive
    komponenti, tip veze i PRAVAC strelica (metrike idu OD cvorova KA Sovi).
    """
    fig, ax = plt.subplots(figsize=(11, 4.4), dpi=150)
    ax.set_xlim(0, 164)
    ax.set_ylim(0, 60)
    ax.axis("off")

    ax.add_patch(Rectangle((31, 2), 131, 56, fill=False, linestyle="--", linewidth=1.2))
    ax.text(33, 55, "Klaster zona eu-1", fontsize=10, style="italic")

    w, h = 24, 10
    boxes = [
        (2, 25, "Klijent SDK"),
        (34, 25, "Kestrel Gateway"),
        (66, 25, "Ruter particija"),
        (98, 42, "Skladišni čvor A\n(vodeći)"),
        (98, 8, "Skladišni čvor B\n(prateći)"),
        (134, 25, "Sova (nadzor)"),
    ]
    for x, y, label in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4",
                                    facecolor="#e8eef7", edgecolor="#1f3b63", linewidth=1.5))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=10)

    def arrow(start, end, label, lx, ly):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16,
                                     linewidth=1.6, color="#1f3b63"))
        ax.text(lx, ly, label, fontsize=8.5, ha="center",
                bbox=dict(facecolor="white", edgecolor="none", pad=1))

    arrow((26.5, 30), (33.5, 30), "gRPC :7419", 30, 37)
    arrow((58.5, 30), (65.5, 30), "interni RPC", 62, 22)
    arrow((90.5, 32), (97.5, 45), "upis", 91, 41)
    arrow((110, 41.5), (110, 18.5), "replikacija\n(asinhrona)", 118, 29)
    arrow((122.5, 47), (138, 35.5), "metrike (push)", 136, 44)
    arrow((122.5, 13), (138, 24.5), "metrike (push)", 136, 14)

    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def draw_throughput(path):
    """Stubicasti grafikon sa TACNIM vrednostima nad stubicima."""
    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
    labels = ["v" + v for v, _ in THROUGHPUT]
    values = [x for _, x in THROUGHPUT]
    bars = ax.bar(labels, values, color="#3b6ea5")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.5, "{:.1f}".format(value),
                ha="center", fontsize=10)
    ax.set_title("Propusnost Kestrel-a po verziji (klaster od 3 čvora)")
    ax.set_xlabel("Verzija")
    ax.set_ylabel("Hiljade poruka u sekundi")
    ax.set_ylim(0, 35)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _textbox(page, rect, text, size=10.5, bold=False):
    """Tekst sa prelamanjem; greska ako ne stane, da se sadrzaj ne izgubi tiho."""
    rest = page.insert_textbox(
        rect, text, fontsize=size,
        fontname="dvb" if bold else "dv", fontfile=FONT_BOLD if bold else FONT,
    )
    if rest < 0:
        raise ValueError("tekst ne staje u {}: {}...".format(rect, text[:40]))
    return rect.y1 - rest  # donja ivica stvarno zauzetog prostora


def _draw_table(page, x0, y0, col_widths, rows, row_h=20):
    """Tabela sa punom mrezom linija — ono sto `find_tables()` prepoznaje."""
    x1 = x0 + sum(col_widths)
    y1 = y0 + row_h * len(rows)
    for i in range(len(rows) + 1):
        page.draw_line((x0, y0 + i * row_h), (x1, y0 + i * row_h), width=0.8)
    x = x0
    for w in col_widths + [0]:
        page.draw_line((x, y0), (x, y1), width=0.8)
        x += w
    for r, row in enumerate(rows):
        x = x0
        for c, cell in enumerate(row):
            rect = fitz.Rect(x + 4, y0 + r * row_h + 4, x + col_widths[c] - 4, y0 + (r + 1) * row_h)
            _textbox(page, rect, cell, size=9.5, bold=(r == 0))
            x += col_widths[c]
    return y1


def build(output=OUTPUT):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    workdir = tempfile.mkdtemp()
    diagram_png = os.path.join(workdir, "arhitektura.png")
    chart_png = os.path.join(workdir, "propusnost.png")
    draw_architecture(diagram_png)
    draw_throughput(chart_png)

    doc = fitz.open()
    margin = 56
    width, height = fitz.paper_size("a4")

    # --- strana 1: tekst + tabela ---------------------------------------
    page = doc.new_page(width=width, height=height)
    y = _textbox(page, fitz.Rect(margin, margin, width - margin, margin + 30), TITLE,
                 size=17, bold=True)
    y = _textbox(page, fitz.Rect(margin, y + 4, width - margin, y + 24), SUBTITLE, size=9.5)
    y = _textbox(page, fitz.Rect(margin, y + 16, width - margin, y + 460), INTRO)
    y = _textbox(page, fitz.Rect(margin, y + 18, width - margin, y + 36), TABLE_CAPTION,
                 size=10, bold=True)
    _draw_table(page, margin, y + 6, [170, 105, width - 2 * margin - 275], TABLE_ROWS)

    # --- strana 2: dijagram + tekst + grafikon ---------------------------
    page = doc.new_page(width=width, height=height)
    img_w = width - 2 * margin
    diagram_rect = fitz.Rect(margin, margin, width - margin, margin + img_w * 0.40)
    page.insert_image(diagram_rect, filename=diagram_png)
    y = _textbox(page, fitz.Rect(margin, diagram_rect.y1 + 4, width - margin, diagram_rect.y1 + 20),
                 "Slika 1. Tok poruke kroz Kestrel klaster", size=9.5, bold=True)
    y = _textbox(page, fitz.Rect(margin, y + 12, width - margin, y + 150), PAGE2_TEXT)
    chart_rect = fitz.Rect(margin + 60, y + 16, width - margin - 60, y + 16 + (img_w - 120) * 0.6)
    page.insert_image(chart_rect, filename=chart_png)
    _textbox(page, fitz.Rect(margin, chart_rect.y1 + 4, width - margin, chart_rect.y1 + 20),
             "Slika 2. Propusnost po verziji", size=9.5, bold=True)

    doc.set_metadata({"title": TITLE, "author": "Vranac Sistemi d.o.o. (fiktivno)"})
    doc.save(output, garbage=3, deflate=True)
    doc.close()
    return output


if __name__ == "__main__":
    print(build())
