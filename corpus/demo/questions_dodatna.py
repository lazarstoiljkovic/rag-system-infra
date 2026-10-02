"""
Pitanja za prosireni korpus (2026-10-01), i izmene postojecih pitanja.

Cilj prosirenja je statisticki: oko 60 pitanja "samo na slici" (bilo ih je
20), od toga 15–20 teskih za opis, da bi poredjenje A i B moglo da ima dovoljno
neslaganja za McNemar-ov test. Polja su ista kao u `questions.py`, plus:

  naziv_i_u_tekstu  odgovor je naziv (servisa, projekta) koji postoji i u
                    tekstu korpusa, ali cinjenica — KOJI od njih — postoji
                    samo na slici (npr. koji servis je imao najveci error rate
                    u datoj nedelji). Provera curenja se tada preskace, a
                    `napomena` mora da objasni zasto je pitanje ipak "samo na
                    slici".

`dokaz` za pitanja "samo na slici" ne mora biti sam odgovor: dovoljno je da
bude natpis sa slike koji dokazuje cinjenicu (npr. natpis strelice), a koji ne
postoji ni u jednom tekstu.
"""

QUESTIONS_DODATNA = [
    # --- Tok placanja (dijagram sekvence) ----------------------------------
    {"id": "TP1", "dokumenti": ["tok-placanja"], "tip": "tekst",
     "pitanje": "Koliko dugo važi ključ idempotentnosti pri zahtevu ka payment provajderu?",
     "odgovor": "24 sata.", "dokaz": ["24 sata"]},
    {"id": "TP2", "dokumenti": ["tok-placanja"], "tip": "tabela",
     "pitanje": "Koliko dugo plaćanje može da ostane u statusu pending?",
     "odgovor": "Najviše 15 minuta, posle toga ističe.", "dokaz": ["15 minuta"]},
    {"id": "TP3", "dokumenti": ["tok-placanja"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Koju poruku payment provider šalje direktno web klijentu tokom plaćanja depozita?",
     "odgovor": "3DS challenge.", "dokaz": ["3DS challenge"]},
    {"id": "TP4", "dokumenti": ["tok-placanja"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Kako payment-service saznaje da je kupac potvrdio plaćanje?",
     "odgovor": "Preko webhook-a od payment provajdera (webhook: authorized).",
     "dokaz": ["webhook: authorized"]},
    {"id": "TP5", "dokumenti": ["tok-placanja"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Koju poruku payment-service šalje booking-service-u tokom plaćanja depozita?",
     "odgovor": "confirm_booking, posle webhook-a da je plaćanje autorizovano.",
     "dokaz": ["confirm_booking"]},
    {"id": "TP6", "dokumenti": ["tok-placanja"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Koju poruku payment-service šalje payment provajderu nakon što booking-service potvrdi rezervaciju?",
     "odgovor": "capture_funds (naplata).", "dokaz": ["capture_funds"]},

    # --- Mrezna topologija -------------------------------------------------
    {"id": "MR1", "dokumenti": ["mrezna-topologija"], "tip": "tabela",
     "pitanje": "Preko kog porta load balancer prosleđuje zahteve aplikacionim serverima?",
     "odgovor": "8080.", "dokaz": ["8080"]},
    {"id": "MR2", "dokumenti": ["mrezna-topologija"], "tip": "tekst",
     "pitanje": "Koji je adresni opseg produkcijske virtuelne privatne mreže?",
     "odgovor": "10.20.0.0/16.", "dokaz": ["10.20.0.0/16"]},
    {"id": "MR3", "dokumenti": ["mrezna-topologija"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "U kojoj zoni dostupnosti se nalazi replika PostgreSQL baze?",
     "odgovor": "U zoni eu-b.", "dokaz": ["zona eu-b"]},
    {"id": "MR4", "dokumenti": ["mrezna-topologija"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "U kojoj podmreži radi Redis?",
     "odgovor": "U podmreži data-a (zona eu-a).", "dokaz": ["data-a"]},
    {"id": "MR5", "dokumenti": ["mrezna-topologija"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "Koja komponenta se, pored load balancer-a, nalazi u nekoj javnoj podmreži?",
     "odgovor": "NAT gateway (u podmreži public-b).", "dokaz": ["NAT gateway"]},
    {"id": "MR6", "dokumenti": ["mrezna-topologija"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Preko koje komponente aplikacioni server vm-app-2 izlazi na internet?",
     "odgovor": "Preko NAT gateway-a.", "dokaz": ["izlaz ka internetu"]},

    # --- Monitoring (linijski grafikon sa vise serija) ----------------------
    {"id": "MO1", "dokumenti": ["monitoring-i-alarmi"], "tip": "tekst",
     "pitanje": "Posle koliko vremena se nepotvrđen alarm eskalira na drugog dežurnog?",
     "odgovor": "Posle 15 minuta.", "dokaz": ["15 minuta"]},
    {"id": "MO2", "dokumenti": ["monitoring-i-alarmi"], "tip": "tabela",
     "pitanje": "Pri kojoj p95 latenciji i posle koliko vremena se šalje alarm?",
     "odgovor": "Kada je p95 veća od 800 ms tokom 10 minuta; poruka ide u kanal #alerts.",
     "dokaz": ["800 ms"]},
    {"id": "MO3", "dokumenti": ["monitoring-i-alarmi"], "tip": "grafikon",
     "samo_na_slici": True, "tesko_za_opis": True, "naziv_i_u_tekstu": True,
     "pitanje": "Koji servis je imao najveći error rate u 24. nedelji?",
     "odgovor": "notification-service (oko 1,9%).",
     "napomena": "Nazivi servisa su u tekstu, ali vrednosti po nedeljama postoje samo na "
                 "grafikonu, i to bez ispisanih brojeva.",
     "dokaz": ["notification-service"]},
    {"id": "MO4", "dokumenti": ["monitoring-i-alarmi"], "tip": "grafikon",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "U kojoj nedelji je error rate payment-service-a prešao prag od 2% za alarm?",
     "odgovor": "U 25. nedelji (oko 2,3%).", "dokaz": ["n25"]},
    {"id": "MO5", "dokumenti": ["monitoring-i-alarmi"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "Koliko alarma je bilo u maju 2026?",
     "odgovor": "37.", "dokaz": ["37"]},

    # --- Kapacitet baze (grupisani stubici i torta) ------------------------
    {"id": "KB1", "dokumenti": ["kapacitet-baze-2026"], "tip": "tekst",
     "pitanje": "U koliko sati se pravi noćna rezervna kopija baze i koliko dugo se čuva?",
     "odgovor": "U 02:00, čuva se 30 dana.", "dokaz": ["02:00", "30 dana"]},
    {"id": "KB2", "dokumenti": ["kapacitet-baze-2026"], "tip": "tekst",
     "pitanje": "Na koliko dana unazad je moguć povraćaj baze na proizvoljan trenutak?",
     "odgovor": "7 dana.", "dokaz": ["7 dana"]},
    {"id": "KB3", "dokumenti": ["kapacitet-baze-2026"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "U kom kvartalu 2026. je replika bila opterećenija od primarnog servera i koliko?",
     "odgovor": "U Q3: replika 66%, primarni server 58%.", "dokaz": ["66"]},
    {"id": "KB4", "dokumenti": ["kapacitet-baze-2026"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "Koja tabela zauzima najviše prostora u bazi i koliki je njen udeo?",
     "odgovor": "bookings, 41%.", "dokaz": ["41%"]},
    {"id": "KB5", "dokumenti": ["kapacitet-baze-2026"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "Koliki udeo prostora u bazi zauzima tabela audit_log?",
     "odgovor": "19%.", "dokaz": ["audit_log", "19%"]},

    # --- Roadmap (Gantt) ---------------------------------------------------
    {"id": "RM1", "dokumenti": ["roadmap-2027"], "tip": "tekst",
     "pitanje": "Kada je sezona najvećeg saobraćaja, sa kojom se infrastrukturni projekti ne smeju preklapati?",
     "odgovor": "Od novembra do decembra.", "dokaz": ["od novembra do decembra"]},
    {"id": "RM2", "dokumenti": ["roadmap-2027"], "tip": "tabela",
     "pitanje": "Koji tim je odgovoran za SOC 2 sertifikaciju?",
     "odgovor": "Platform team.", "dokaz": ["SOC 2 sertifikacija", "Platform team"]},
    {"id": "RM3", "dokumenti": ["roadmap-2027"], "tip": "grafikon",
     "samo_na_slici": True, "tesko_za_opis": True, "naziv_i_u_tekstu": True,
     "pitanje": "Koji projekat iz roadmap-a za 2027. se završava poslednji i kada?",
     "odgovor": "SOC 2 sertifikacija, u novembru 2027.",
     "napomena": "Nazivi projekata su u tabeli, ali periodi postoje samo na Gantt planu, "
                 "bez ispisanih datuma.",
     "dokaz": ["SOC 2 sertifikacija"]},
    {"id": "RM4", "dokumenti": ["roadmap-2027"], "tip": "grafikon",
     "samo_na_slici": True, "tesko_za_opis": True, "naziv_i_u_tekstu": True,
     "pitanje": "Koji projekti se izvode istovremeno sa uvođenjem novog payment provajdera?",
     "odgovor": "Kubernetes migracija, Redizajn kalendara i Nexa Booking 3.0 beta.",
     "napomena": "Nazivi projekata su u tabeli, ali preklapanje se vidi samo na Gantt planu.",
     "dokaz": ["Redizajn kalendara", "Nexa Booking 3.0 beta"]},
    {"id": "RM5", "dokumenti": ["roadmap-2027"], "tip": "grafikon",
     "samo_na_slici": True, "tesko_za_opis": True, "naziv_i_u_tekstu": True,
     "pitanje": "U kom mesecu 2027. počinje rad na mobilnoj aplikaciji i koliko traje?",
     "odgovor": "U maju; traje do oktobra, šest meseci.",
     "napomena": "Naziv projekta je u tabeli, ali period postoji samo na Gantt planu.",
     "dokaz": ["Mobilna aplikacija"]},

    # --- Ometac: arhitektura 2.2 -------------------------------------------
    {"id": "AZ1", "dokumenti": ["booking-arhitektura-2-2"], "tip": "tekst",
     "pitanje": "Koliko servisa je činilo backend u verziji 2.2 i gde je bio katalog usluga?",
     "odgovor": "Tri servisa; katalog je bio deo booking-service-a.",
     "dokaz": ["tri servisa", "deo booking-service-a"]},
    {"id": "AZ2", "dokumenti": ["booking-arhitektura-2-2"], "tip": "dijagram",
     "samo_na_slici": True,
     "pitanje": "Kako je booking-service u verziji 2.2 obaveštavao notification-service?",
     "odgovor": "Direktnim HTTP pozivom (sinhrono, bez message queue-a).",
     "dokaz": ["direktan HTTP poziv"]},
    {"id": "AZ3", "dokumenti": ["booking-arhitektura-2-2"], "tip": "grafikon",
     "samo_na_slici": True,
     "pitanje": "Kolika je bila p95 latencija za POST /payments u avgustu 2025?",
     "odgovor": "642 ms.", "dokaz": ["642"]},

    # --- Ometac: SLA 2025 --------------------------------------------------
    {"id": "SZ1", "dokumenti": ["sla-i-podrska-2025"], "tip": "tabela",
     "pitanje": "Koliko je mesečno koštao plan Enterprise po SLA iz 2025. godine?",
     "odgovor": "299 EUR.", "dokaz": ["299"]},
    {"id": "SZ2", "dokumenti": ["sla-i-podrska-2025"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "U kom mesecu četvrtog kvartala 2025. je uptime bio najniži i koliki je bio?",
     "odgovor": "U novembru, 99,64%.", "dokaz": ["99.64"]},

    # --- Onboarding --------------------------------------------------------
    {"id": "ON1", "dokumenti": ["procedura-onboardinga"], "tip": "tekst",
     "pitanje": "Koliko traje probni rad i ko vodi razgovor na njegovom kraju?",
     "odgovor": "Tri meseca; razgovor vodi engineering manager.",
     "dokaz": ["Probni rad traje tri meseca"]},
    {"id": "ON2", "dokumenti": ["procedura-onboardinga"], "tip": "tabela",
     "pitanje": "Ko vodi bezbednosnu obuku u prvoj nedelji novog zaposlenog?",
     "odgovor": "Security tim, u sredu.", "dokaz": ["Security tim"]},
    {"id": "ON3", "dokumenti": ["procedura-onboardinga"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Ko priprema laptop i naloge za novog zaposlenog?",
     "odgovor": "IT podrška, na osnovu naloga za opremu od People Ops-a.",
     "dokaz": ["laptop i nalozi"]},
    {"id": "ON4", "dokumenti": ["procedura-onboardinga"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Ko bira mentora novom zaposlenom?",
     "odgovor": "Engineering manager.", "dokaz": ["izbor mentora"]},

    # --- Ugovor o obradi podataka -------------------------------------------
    {"id": "DP1", "dokumenti": ["ugovor-o-obradi-podataka"], "tip": "tabela",
     "pitanje": "U kojoj zemlji SMS provajder obrađuje podatke krajnjih korisnika?",
     "odgovor": "U Holandiji.", "dokaz": ["SMS provajder", "Holandija"]},
    {"id": "DP2", "dokumenti": ["ugovor-o-obradi-podataka"], "tip": "tekst",
     "pitanje": "Koliko dugo se podaci klijenta čuvaju posle raskida ugovora?",
     "odgovor": "30 dana, radi izvoza, a zatim se trajno brišu.", "dokaz": ["30 dana"]},

    # --- Sluzbena putovanja -------------------------------------------------
    {"id": "PT1", "dokumenti": ["pravilnik-o-putovanjima"], "tip": "tabela",
     "pitanje": "Kolika je dnevnica za službeni put u Nemačku?",
     "odgovor": "60 EUR.", "dokaz": ["Nemačka", "60"]},
    {"id": "PT2", "dokumenti": ["pravilnik-o-putovanjima"], "tip": "tekst",
     "pitanje": "Koliko unapred se prijavljuje službeno putovanje?",
     "odgovor": "Najmanje 10 dana unapred, preko HR portala.", "dokaz": ["10 dana unapred"]},
    {"id": "PT3", "dokumenti": ["pravilnik-o-putovanjima"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Ko sve odobrava službeno putovanje procenjeno na 1.200 EUR?",
     "odgovor": "Team lead, a zatim Department head (trošak je preko 500 EUR).",
     "dokaz": ["preko 500 EUR"]},
    {"id": "PT4", "dokumenti": ["pravilnik-o-putovanjima"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Od kog iznosa službeno putovanje mora da odobri i CFO?",
     "odgovor": "Preko 2.000 EUR.", "dokaz": ["preko 2.000 EUR"]},

    # --- Kodeks ponasanja ---------------------------------------------------
    {"id": "KD1", "dokumenti": ["kodeks-ponasanja"], "tip": "tekst",
     "pitanje": "Do koje vrednosti zaposleni sme da primi poklon od klijenta?",
     "odgovor": "Do 50 EUR.", "dokaz": ["50 EUR"]},
    {"id": "KD2", "dokumenti": ["kodeks-ponasanja"], "tip": "tekst",
     "pitanje": "Kome se i u kom roku prijavljuje mogući sukob interesa?",
     "odgovor": "People Ops-u, u roku od pet radnih dana od saznanja.",
     "dokaz": ["pet radnih dana od saznanja"]},

    # --- nova pitanja nad postojecim slikama --------------------------------
    {"id": "E1", "dokumenti": ["booking-arhitektura"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Šta payment-service šalje eksternom payment provajderu umesto podataka kartice?",
     "odgovor": "Tokenizovanu karticu.", "dokaz": ["tokenizovana kartica"]},
    {"id": "E2", "dokumenti": ["booking-arhitektura"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Odakle web klijent učitava statičke fajlove?",
     "odgovor": "Sa CDN-a.", "dokaz": ["statički fajlovi"]},
    {"id": "E3", "dokumenti": ["sla-i-podrska"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Kome L2 support prosleđuje kritične tikete?",
     "odgovor": "On-call engineer-u.", "dokaz": ["On-call engineer"]},
    {"id": "E4", "dokumenti": ["plan-migracije-kubernetes"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "U kom namespace-u će raditi api-gateway posle migracije na Kubernetes?",
     "odgovor": "U namespace-u edge.", "dokaz": ["namespace: edge"]},
    {"id": "E5", "dokumenti": ["plan-migracije-kubernetes"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "U kom namespace-u će raditi notification-service?",
     "odgovor": "U namespace-u async, zajedno sa message queue-om.", "dokaz": ["namespace: async"]},
    {"id": "E6", "dokumenti": ["organizacija-i-pozicije"], "tip": "dijagram",
     "samo_na_slici": True, "tesko_za_opis": True,
     "pitanje": "Koji timovi rade iz kancelarije u Novom Sadu?",
     "odgovor": "Platform team, Booking team i Frontend team.", "dokaz": ["Kancelarija Novi Sad"]},
    {"id": "E7", "dokumenti": ["politika-bezbednosti"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Kome security on-call prosleđuje ozbiljan bezbednosni incident?",
     "odgovor": "CTO-u.", "dokaz": ["ozbiljan incident"]},
    {"id": "E8", "dokumenti": ["pravilnik-o-radu"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Kome team lead šalje odobren zahtev za odsustvo radi evidencije?",
     "odgovor": "People Ops-u.", "dokaz": ["evidencija"]},
    {"id": "E9", "dokumenti": ["izvestaj-performanse-q2-2026"], "tip": "grafikon",
     "samo_na_slici": True,
     "pitanje": "Koja stranica ima najbrži LCP na mobilnim uređajima i koliki je on?",
     "odgovor": "Profile, 1,6 s.", "dokaz": ["1.6"]},
    {"id": "E10", "dokumenti": ["ci-cd-proces"], "tip": "grafikon", "samo_na_slici": True,
     "pitanje": "U kom mesecu 2026. je pipeline u proseku trajao najkraće i koliko?",
     "odgovor": "U maju, 13,6 minuta.", "dokaz": ["13.6"]},
    {"id": "E11", "dokumenti": ["plan-migracije-kubernetes"], "tip": "grafikon",
     "samo_na_slici": True,
     "pitanje": "Koliki je očekivani trošak infrastrukture u junu 2027?",
     "odgovor": "5,2 hiljade EUR.", "dokaz": ["5.2"]},
    {"id": "E12", "dokumenti": ["frontend-standardi"], "tip": "dijagram", "samo_na_slici": True,
     "pitanje": "Šta pokreće Action u frontend aplikaciji Nexa Booking?",
     "odgovor": "User event iz React komponente.", "dokaz": ["user event"]},

    # --- vise dokumenata ----------------------------------------------------
    {"id": "X5", "dokumenti": ["roadmap-2027", "plan-migracije-kubernetes"],
     "tip": "vise-dokumenata",
     "pitanje": "Koji tim uvodi novog payment provajdera i u kom mesecu 2027. se payment-service migrira na Kubernetes?",
     "odgovor": "Payments team; payment-service se migrira u aprilu 2027.",
     "dokaz": ["Novi payment provider", "april 2027"]},
    {"id": "X6", "dokumenti": ["ugovor-o-obradi-podataka", "politika-bezbednosti"],
     "tip": "vise-dokumenata",
     "pitanje": "U kom roku Nexa Tech mora da obavesti klijenta o povredi bezbednosti podataka i ko kod nas obaveštava Poverenika?",
     "odgovor": "Klijenta najkasnije u roku od 48 sati; Poverenika obaveštava Pravna služba.",
     "dokaz": ["48 sati"]},
    {"id": "X7", "dokumenti": ["monitoring-i-alarmi", "izvestaj-performanse-q2-2026"],
     "tip": "vise-dokumenata",
     "pitanje": "Koji tim, pored Platform tima, učestvuje u dežurstvu, i koji servis tog tima je bio bottleneck na load testu?",
     "odgovor": "Payments team; payment-service.", "dokaz": ["Payments tima", "Bottleneck"]},
]

# Postojeca pitanja koja ometaci cine dvosmislenim: bez preciziranja bi i
# stara verzija dokumenta dala "tacan" odgovor.
_IZMENE = {
    "A1": "U trenutnoj verziji 2.4, na kom portu radi payment-service i koliki mu je timeout?",
    "A4": "Koji endpoint je u avgustu 2026. imao najveću p95 latenciju i kolika je ona?",
    "S1": "Koliki uptime garantuje plan Business po SLA koji važi od 2026. godine?",
    "S2": "Koliko unapred se, po SLA koji važi od 2026. godine, najavljuje planirano održavanje?",
}


def izmene_postojecih(questions):
    out = []
    for q in questions:
        q = dict(q)
        if q["id"] in _IZMENE:
            q["pitanje"] = _IZMENE[q["id"]]
        out.append(q)
    return out
