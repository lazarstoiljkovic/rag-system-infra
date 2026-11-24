"""
Statistika za poredjenje varijanti A i B (odeljak 2.5.4 rada). Ciste funkcije,
samo standardna biblioteka — bez scipy-ja, da testovi rade bez instalacije.

McNemar-ov test za uparene binarne ishode:
  b = pitanja na kojima je tacna samo A
  c = pitanja na kojima je tacna samo B
Pitanja na kojima su obe tacne ili obe netacne ne nose informaciju o razlici.

Tacan oblik (binomni) je osnovni, jer je neslaganja malo — na 47 pitanja ih
je bilo nekoliko. Aproksimacija hi-kvadratom se daje samo radi poredjenja.
"""

import math
from typing import Dict, Iterable, List, Sequence, Tuple


def paired_counts(a: Sequence[bool], b: Sequence[bool]) -> Dict[str, int]:
    """Tabela 2x2 za uparene ishode iste duzine."""
    if len(a) != len(b):
        raise ValueError("nizovi ishoda moraju biti iste duzine")
    counts = {"both": 0, "only_a": 0, "only_b": 0, "neither": 0}
    for x, y in zip(a, b):
        if x and y:
            counts["both"] += 1
        elif x:
            counts["only_a"] += 1
        elif y:
            counts["only_b"] += 1
        else:
            counts["neither"] += 1
    return counts


def mcnemar_exact(b: int, c: int) -> float:
    """
    Dvostrana p-vrednost tacnog McNemar-ovog testa.

    Pod hipotezom da razlike nema, b ~ Binomial(b + c, 1/2). Verovatnoca ishoda
    bar ovako neravnomernog: 2 * P(X <= min(b, c)), ograniceno na 1.
    """
    if b < 0 or c < 0:
        raise ValueError("broj neslaganja ne moze biti negativan")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def mcnemar_chi2(b: int, c: int) -> Tuple[float, float]:
    """
    Statistika sa korekcijom za neprekidnost i njena p-vrednost (1 stepen
    slobode). Za chi2 sa jednim stepenom slobode vazi P(X > x) = erfc(sqrt(x/2)).
    """
    if b + c == 0:
        return 0.0, 1.0
    stat = (abs(b - c) - 1) ** 2 / (b + c)
    return stat, math.erfc(math.sqrt(stat / 2))


def holm(pvalues: Sequence[float]) -> List[float]:
    """
    Holm-Bonferroni korekcija za vise poredjenja nad istim skupom pitanja.

    Kad se sedam oblika pretrage poredi sa osnovom, verovatnoca da bar jedno
    p padne ispod 0.05 slucajno je znatno veca od 5%. Holm je uniformno jaci od
    obicnog Bonferroni-ja: najmanje p se mnozi sa m, sledece sa m - 1 i tako
    dalje, uz monotonost (korigovana vrednost ne sme pasti ispod prethodne).
    Vraca korigovane vrednosti istim redom kao ulaz.
    """
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for position, i in enumerate(order):
        running = max(running, min(1.0, (m - position) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def cohen_kappa(pairs: Iterable[Tuple[bool, bool]]) -> float:
    """
    Slaganje dva ocenjivaca (npr. sudija i rucna ocena) iznad slucajnog.
    1 = potpuno slaganje, 0 = koliko bi se slozili slucajno.
    """
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return float("nan")
    observed = sum(1 for x, y in pairs if x == y) / n
    p_x = sum(1 for x, _ in pairs if x) / n
    p_y = sum(1 for _, y in pairs if y) / n
    expected = p_x * p_y + (1 - p_x) * (1 - p_y)
    if expected == 1:
        return 1.0 if observed == 1 else float("nan")
    return (observed - expected) / (1 - expected)


def mean(values: Iterable[float]) -> float:
    """Prosek bez NaN vrednosti (metrika koja nije uspela se ne racuna kao 0)."""
    vals: List[float] = [v for v in values if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else float("nan")
