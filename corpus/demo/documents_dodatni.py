"""
Prosirenje demo korpusa (2026-10-01): jedanaest novih dokumenata.

Razlozi, iz prvog punog merenja (`eval-2026-10-01`):
  - samo 20 pitanja "samo na slici" dalo je 5 neslaganja izmedju A i B, a sa
    5 neslaganja tacan McNemar-ov test ne moze ispod p = 0,0625;
  - pretraga je bila prelaka (Hit@5 = 0,98) jer se dokumenti nisu preklapali.

Zato:
  - nove VRSTE slika: dijagram sekvence, mrezna topologija sa zonama i
    podmrezama, linijski grafikon sa vise serija bez ispisanih vrednosti,
    grupisani stubici, torta i Gantt plan;
  - OMETACI: stara verzija arhitekture (2.2) i stari SLA (2025), sa
    drugacijim vrednostima — pretraga mora da nadje VAZECI dokument;
  - opsti dokumenti bez mnogo slika, kao realniji sum za pretragu.

Pravilo iz `documents.py` vazi i ovde: svaka slika ima bar jednu cinjenicu
koje nema ni u jednom tekstu korpusa. `generate.py` to proverava.
"""

from documents import _header

TOK_PLACANJA = [
    ("h1", "Tok plaćanja depozita karticom"),
    _header("Payments team", "revizija 2"),
    ("h2", "1. Pregled"),
    ("p", "Plaćanje depozita pri rezervaciji obavlja payment-service, uz eksternog "
          "payment provajdera. Podaci kartice se nikada ne čuvaju u sistemu Nexa "
          "Booking: provajder vraća token, a payment-service čuva samo njega. Kod "
          "kartica za koje banka izdavalac to traži, kupac dodatno potvrđuje "
          "plaćanje u aplikaciji svoje banke (3D Secure)."),
    ("p", "Svaki zahtev ka provajderu nosi ključ idempotentnosti, koji važi 24 "
          "sata, pa zahtev ponovljen zbog prekida veze ne može dvaput da naplati "
          "karticu. Ako provajder ne odgovori u roku od 8 sekundi, payment-service "
          "prekida pokušaj i klijentu vraća grešku 504."),
    ("table", {
        "caption": "Tabela 1. Statusi plaćanja",
        "widths": [80, 150, 253],
        "rows": [
            ["Status", "Značenje", "Šta sledi"],
            ["pending", "čeka potvrdu kupca", "autorizacija, ili istek posle 15 minuta"],
            ["authorized", "sredstva rezervisana na kartici",
             "naplata najkasnije 7 dana posle autorizacije"],
            ["captured", "sredstva naplaćena", "povraćaj samo na zahtev klijenta"],
            ["failed", "plaćanje odbijeno", "novi pokušaj sa drugom karticom"],
            ["refunded", "sredstva vraćena kupcu", "nema daljih koraka"],
        ],
    }),
    ("h2", "2. Redosled poruka"),
    ("p", "Slika 1 prikazuje redosled poruka između učesnika pri plaćanju "
          "depozita, od zahteva web klijenta do naplate."),
    ("figure", {
        "caption": "Slika 1. Sekvenca plaćanja depozita",
        "spec": {
            "participants": ["Web klijent", "api-gateway", "payment-service",
                             "Payment provider", "booking-service"],
            "messages": [
                (0, 1, "POST /payments"),
                (1, 2, "create_intent"),
                (2, 3, "authorize_request"),
                (3, 0, "3DS challenge"),
                (0, 3, "potvrda kupca"),
                (3, 2, "webhook: authorized"),
                (2, 4, "confirm_booking"),
                (4, 2, "", "povratna"),
                (2, 3, "capture_funds"),
                (2, 1, "200 OK", "povratna"),
                (1, 0, "", "povratna"),
            ],
        },
    }),
]

MREZA = [
    ("h1", "Mrežna topologija produkcije"),
    _header("Platform team", "revizija 4"),
    ("h2", "1. Pregled"),
    ("p", "Produkcija Nexa Booking radi u jednoj virtuelnoj privatnoj mreži sa "
          "adresnim opsegom 10.20.0.0/16, raspoređenoj u dve zone dostupnosti. U "
          "svakoj zoni postoje tri podmreže: javna, aplikaciona i podmreža za "
          "podatke. Iz interneta je dostupan samo load balancer; aplikacioni "
          "serveri i baze nemaju javne adrese."),
    ("p", "Administratorski pristup ide isključivo preko VPN-a, uz obaveznu "
          "dvofaktorsku autentikaciju, i to samo do bastion servera. Pravila "
          "pristupa između slojeva navedena su u tabeli 1; sve što nije navedeno "
          "je zabranjeno."),
    ("table", {
        "caption": "Tabela 1. Pravila pristupa",
        "widths": [110, 120, 70, 183],
        "rows": [
            ["Izvor", "Odredište", "Port", "Namena"],
            ["internet", "load balancer", "443", "HTTPS saobraćaj klijenata"],
            ["load balancer", "aplikacioni serveri", "8080", "prosleđivanje zahteva"],
            ["aplikacioni serveri", "baza i keš", "5432, 6379", "pristup podacima"],
            ["VPN", "bastion server", "22", "administracija"],
        ],
    }),
    ("h2", "2. Raspored komponenti"),
    ("p", "Slika 1 prikazuje raspored komponenti po zonama i podmrežama."),
    ("figure", {
        "caption": "Slika 1. Raspored komponenti produkcije",
        "spec": {
            "size": (180, 128), "box": (30, 9),
            "groups": [
                (2, 2, 178, 126, "VPC produkcija"),
                (6, 6, 88, 120, "zona eu-a"),
                (92, 6, 174, 120, "zona eu-b"),
                (10, 82, 84, 110, "subnet public-a"),
                (96, 82, 170, 110, "subnet public-b"),
                (10, 46, 84, 74, "subnet app-a"),
                (96, 46, 170, 74, "subnet app-b"),
                (10, 10, 84, 38, "subnet data-a", "dole"),
                (96, 10, 170, 38, "subnet data-b", "dole"),
            ],
            "nodes": {
                "lb": (47, 94, "Load balancer"),
                "nat": (133, 94, "NAT gateway"),
                "app1": (47, 60, "vm-app-1"),
                "app2": (133, 60, "vm-app-2"),
                # Redis nize od baza: strelica replikacije ide vodoravno od
                # primarne baze ka replici i ne sme proci kroz njega.
                "pgp": (30, 30, "PostgreSQL\nprimary"),
                "redis": (66, 17, "Redis"),
                "pgr": (133, 30, "PostgreSQL\nreplica"),
            },
            "edges": [
                ("lb", "app1", ""),
                ("lb", "app2", ""),
                ("app1", "pgp", ""),
                ("app2", "pgp", ""),
                ("app1", "redis", ""),
                ("pgp", "pgr", "replikacija"),
                ("app2", "nat", "izlaz ka internetu"),
            ],
        },
    }),
]

MONITORING = [
    ("h1", "Monitoring i alarmi"),
    _header("Platform team", "važi od 1. jula 2026."),
    ("h2", "1. Metrike i dežurstvo"),
    ("p", "Svaki servis izlaže metrike o broju zahteva, udelu grešaka (error "
          "rate) i latenciji. Metrike se prikupljaju svakih 15 sekundi i čuvaju "
          "13 meseci. Alarm se šalje dežurnom inženjeru; ako ga on ne potvrdi u "
          "roku od 15 minuta, alarm se eskalira na drugog dežurnog, a posle još "
          "15 minuta na engineering managera."),
    ("p", "Dežurstvo traje nedelju dana, počinje ponedeljkom u 10 časova i "
          "rotira se između članova Platform i Payments tima."),
    ("table", {
        "caption": "Tabela 1. Alarmi",
        "widths": [130, 95, 85, 173],
        "rows": [
            ["Metrika", "Prag", "Trajanje", "Obaveštenje"],
            ["error rate", "veći od 2%", "5 minuta", "poziv dežurnom"],
            ["p95 latencija", "veća od 800 ms", "10 minuta", "poruka u kanal #alerts"],
            ["health check", "3 uzastopna neuspeha", "odmah", "poziv dežurnom"],
            ["popunjenost diska", "veća od 85%", "30 minuta", "poruka u kanal #alerts"],
        ],
    }),
    ("h2", "2. Error rate po servisu"),
    ("p", "Slika 1 prikazuje nedeljni error rate po servisima tokom juna i "
          "početka jula 2026."),
    ("figure", {
        "caption": "Slika 1. Error rate po servisima",
        "scale": 0.9,
        "spec": {
            "kind": "multiline", "title": "Error rate po servisu, nedelje 22–27",
            "x_label": "Nedelja", "y_label": "Error rate (%)",
            "categories": ["n22", "n23", "n24", "n25", "n26", "n27"],
            "series": {
                "api-gateway": [0.4, 0.5, 0.4, 0.6, 0.5, 0.4],
                "booking-service": [0.8, 0.9, 1.4, 1.1, 0.9, 0.8],
                "payment-service": [1.2, 1.6, 1.3, 2.3, 1.5, 1.1],
                "notification-service": [0.6, 0.7, 1.9, 0.9, 0.7, 0.6],
            },
            "y_max": 2.6,
        },
    }),
    ("h2", "3. Broj alarma"),
    ("p", "Slika 2 prikazuje ukupan broj alarma po mesecima u drugom kvartalu "
          "2026."),
    ("figure", {
        "caption": "Slika 2. Broj alarma po mesecima",
        "scale": 0.8,
        "spec": {
            "kind": "bar", "title": "Broj alarma, Q2 2026.",
            "x_label": "Mesec", "y_label": "Broj alarma",
            "categories": ["april", "maj", "jun"],
            "values": [14, 37, 12], "y_max": 45, "fmt": "{:.0f}",
        },
    }),
]

KAPACITET = [
    ("h1", "Kapacitet baze podataka — 2026."),
    _header("Platform team", "revizija 2"),
    ("h2", "1. Konfiguracija"),
    ("p", "Produkcijska baza je PostgreSQL 16, sa primarnim serverom i jednom "
          "replikom za čitanje. Rezervna kopija pravi se svake noći u 02:00 i čuva "
          "se 30 dana. Uz nju se čuvaju i transakcioni logovi, pa je moguć "
          "povraćaj na bilo koji trenutak u poslednjih 7 dana."),
    ("p", "Kada prosečno opterećenje procesora na nekom serveru tri kvartala "
          "zaredom pređe 70%, pokreće se nabavka većeg servera."),
    ("table", {
        "caption": "Tabela 1. Serveri baze",
        "widths": [110, 70, 90, 213],
        "rows": [
            ["Server", "vCPU", "RAM", "Disk"],
            ["primarni", "8", "64 GB", "1 TB SSD"],
            ["replika", "4", "32 GB", "1 TB SSD"],
        ],
    }),
    ("h2", "2. Opterećenje i zauzeće prostora"),
    ("p", "Slika 1 prikazuje prosečno opterećenje procesora po kvartalima, a "
          "slika 2 udeo pojedinih tabela u zauzetom prostoru na kraju trećeg "
          "kvartala."),
    ("figure", {
        "caption": "Slika 1. Opterećenje procesora po kvartalima",
        "scale": 0.85,
        "spec": {
            "kind": "grouped", "title": "Prosečno opterećenje CPU-a, 2026.",
            "x_label": "Kvartal", "y_label": "CPU (%)",
            "categories": ["Q1", "Q2", "Q3"],
            "series": {"primary": [52, 63, 58], "replica": [38, 57, 66]},
            "y_max": 80, "fmt": "{:.0f}",
        },
    }),
    ("figure", {
        "caption": "Slika 2. Zauzeće prostora po tabelama",
        "scale": 0.75,
        "spec": {
            "kind": "pie", "title": "Zauzeće prostora, kraj Q3 2026.",
            "labels": ["bookings", "payments", "audit_log", "services", "ostalo"],
            "values": [41, 23, 19, 9, 8], "fmt": "{:.0f}",
        },
    }),
]

ROADMAP = [
    ("h1", "Roadmap za 2027. godinu"),
    _header("Product", "verzija 1"),
    ("h2", "1. Principi"),
    ("p", "Roadmap obuhvata najvažnije projekte za 2027. godinu. Projekti koji "
          "menjaju infrastrukturu planiraju se tako da se ne preklapaju sa "
          "sezonom najvećeg saobraćaja, od novembra do decembra. Za svaki projekat "
          "odgovoran je jedan tim, a periodi su okvirni i preispituju se "
          "kvartalno."),
    ("table", {
        "caption": "Tabela 1. Projekti",
        "widths": [150, 110, 223],
        "rows": [
            ["Projekat", "Odgovoran tim", "Cilj"],
            ["Kubernetes migracija", "Platform team", "autoscaling i brži deploy"],
            ["Redizajn kalendara", "Frontend team", "brže zakazivanje na mobilnom"],
            ["Novi payment provider", "Payments team", "provizija niža za 0,4 procentna poena"],
            ["Nexa Booking 3.0 beta", "Booking team", "grupni termini i liste čekanja"],
            ["Mobilna aplikacija", "Frontend team", "iOS i Android za krajnje korisnike"],
            ["SOC 2 sertifikacija", "Platform team", "uslov za enterprise klijente"],
        ],
    }),
    ("h2", "2. Vremenski plan"),
    ("p", "Slika 1 prikazuje okvirni period izvođenja svakog projekta."),
    ("figure", {
        "caption": "Slika 1. Vremenski plan projekata, 2027.",
        "scale": 0.95,
        "spec": {
            "kind": "gantt", "title": "Roadmap 2027.", "x_label": "Mesec 2027.",
            "months": ["jan", "feb", "mar", "apr", "maj", "jun",
                       "jul", "avg", "sep", "okt", "nov", "dec"],
            "tasks": [
                ("Kubernetes migracija", 0, 4),
                ("Redizajn kalendara", 0, 2),
                ("Novi payment provider", 1, 3),
                ("Nexa Booking 3.0 beta", 2, 5),
                ("Mobilna aplikacija", 4, 9),
                ("SOC 2 sertifikacija", 5, 10),
            ],
        },
    }),
]

# --- ometaci: stare verzije postojecih dokumenata -------------------------

ARHITEKTURA_22 = [
    ("h1", "Nexa Booking 2.2 — Arhitektura sistema (zastarelo)"),
    _header("Platform team", "revizija 3, zamenjena revizijom 6 (verzija 2.4)"),
    ("p", "Napomena: dokument opisuje verziju 2.2 iz 2025. godine i zadržan je "
          "radi istorije izmena. Važeća arhitektura opisana je u dokumentu za "
          "verziju 2.4."),
    ("h2", "1. Servisi"),
    ("p", "U verziji 2.2 backend su činila tri servisa iza api-gateway-a: "
          "booking-service, payment-service i notification-service. Katalog "
          "usluga bio je deo booking-service-a, a baza je imala samo primarni "
          "server, bez replike."),
    ("table", {
        "caption": "Tabela 1. Servisi u verziji 2.2",
        "widths": [135, 70, 50, 60, 168],
        "rows": [
            ["Servis", "Jezik", "Port", "Timeout", "Vlasnik"],
            ["api-gateway", "Go", "8080", "10 s", "Platform team"],
            ["booking-service", "Go", "8001", "5 s", "Booking team"],
            ["payment-service", "Go", "8002", "12 s", "Payments team"],
            ["notification-service", "Node.js", "8003", "5 s", "Notifications team"],
        ],
    }),
    ("h2", "2. Komponente"),
    ("p", "Slika 1 prikazuje komponente sistema u verziji 2.2."),
    ("figure", {
        "caption": "Slika 1. Komponente sistema, verzija 2.2",
        "spec": {
            "size": (170, 80), "box": (28, 9),
            "nodes": {
                "web": (16, 60, "Web klijent"),
                "gw": (58, 60, "api-gateway"),
                "book": (100, 70, "booking-service"),
                "pay": (100, 44, "payment-service"),
                # Dijagonalno dole desno: uspravna strelica bi prosla kroz
                # payment-service, a ta veza je upravo predmet pitanja AZ2.
                "notif": (148, 14, "notification-service"),
                "pg": (148, 70, "PostgreSQL"),
                "prov": (148, 44, "Payment provider"),
            },
            "edges": [
                ("web", "gw", "HTTPS"),
                ("gw", "book", ""),
                ("gw", "pay", ""),
                ("book", "pg", ""),
                ("pay", "prov", ""),
                # Natpis levo od strelice, ispod payment-service-a: na
                # podrazumevanom mestu prekrio bi kutiju Payment provider.
                ("book", "notif", "direktan HTTP poziv", (110, 28)),
            ],
        },
    }),
    ("h2", "3. Latencija"),
    ("p", "Slika 2 prikazuje p95 latenciju najvažnijih endpoint-a u verziji 2.2."),
    ("figure", {
        "caption": "Slika 2. p95 latencija po endpoint-u, verzija 2.2",
        "scale": 0.85,
        "spec": {
            "kind": "bar", "title": "p95 latencija po endpoint-u, avgust 2025.",
            "x_label": "Endpoint", "y_label": "Latencija (ms)",
            "categories": ["GET /slots", "POST /bookings", "POST /payments", "GET /services"],
            "values": [131, 305, 642, 88], "y_max": 720, "fmt": "{:.0f}",
        },
    }),
]

SLA_2025 = [
    ("h1", "SLA i nivoi podrške — 2025. (prestao da važi)"),
    _header("Customer Support", "važio do 31. decembra 2025."),
    ("p", "Napomena: ovaj SLA je zamenjen SLA-om koji važi od 1. januara 2026."),
    ("h2", "1. Obaveze"),
    ("p", "Uptime se merio mesečno. Planirano održavanje najavljivalo se najmanje "
          "48 sati unapred. Za nedostupnost preko obaveze iz plana klijent je "
          "dobijao kredit od 3% mesečne pretplate po započetom satu."),
    ("table", {
        "caption": "Tabela 1. Planovi podrške u 2025.",
        "widths": [75, 75, 110, 145, 78],
        "rows": [
            ["Plan", "Uptime", "Prvi odgovor (kritično)", "Kanali podrške",
             "Cena (EUR mesečno)"],
            ["Starter", "99,0%", "1 radni dan", "e-mail", "25"],
            ["Business", "99,5%", "4 sata", "e-mail i chat", "79"],
            ["Enterprise", "99,8%", "1 sat", "telefon radnim danima", "299"],
        ],
    }),
    ("h2", "2. Ostvareni uptime"),
    ("p", "Slika 1 prikazuje izmereni uptime u poslednjem kvartalu važenja."),
    ("figure", {
        "caption": "Slika 1. Izmereni uptime, Q4 2025.",
        "scale": 0.8,
        "spec": {
            "kind": "bar", "title": "Izmereni uptime, Q4 2025.",
            "x_label": "Mesec", "y_label": "Uptime (%)",
            "categories": ["oktobar", "novembar", "decembar"],
            "values": [99.91, 99.64, 99.95], "y_min": 99.4, "y_max": 100.05,
            "fmt": "{:.2f}",
        },
    }),
]

# --- opsti dokumenti ------------------------------------------------------

ONBOARDING = [
    ("h1", "Procedura onboardinga novih zaposlenih"),
    _header("People Ops", "važi od 1. marta 2026."),
    ("h2", "1. Prvi meseci"),
    ("p", "Prvi radni dan novog zaposlenog je uvek ponedeljak. Novi zaposleni "
          "dobija mentora iz svog tima, koji mu je na raspolaganju prva tri "
          "meseca. Probni rad traje tri meseca, a na kraju probnog rada "
          "engineering manager vodi razgovor o napretku i odluci o nastavku "
          "saradnje."),
    ("table", {
        "caption": "Tabela 1. Prva nedelja",
        "widths": [85, 250, 148],
        "rows": [
            ["Dan", "Aktivnost", "Ko vodi"],
            ["ponedeljak", "uvodni sastanak i pravila rada", "People Ops"],
            ["utorak", "upoznavanje sa arhitekturom sistema", "Platform team"],
            ["sreda", "bezbednosna obuka", "Security tim"],
            ["četvrtak", "prvi zadatak u kodu", "mentor"],
            ["petak", "razgovor o prvoj nedelji", "engineering manager"],
        ],
    }),
    ("h2", "2. Priprema pre dolaska"),
    ("p", "Slika 1 prikazuje šta se dešava od potpisivanja ugovora do prvog "
          "radnog dana."),
    ("figure", {
        "caption": "Slika 1. Priprema pre prvog radnog dana",
        "spec": {
            "size": (170, 66), "box": (30, 9),
            "nodes": {
                "ugovor": (18, 52, "Potpisan ugovor"),
                "ops": (62, 52, "People Ops"),
                "it": (106, 52, "IT podrška"),
                "em": (62, 14, "Engineering\nmanager"),
                "mentor": (106, 14, "Mentor"),
                "dan": (152, 33, "Prvi radni dan"),
            },
            "edges": [
                ("ugovor", "ops", ""),
                ("ops", "it", "nalog za opremu"),
                ("ops", "em", "obaveštenje"),
                ("em", "mentor", "izbor mentora"),
                ("it", "dan", "laptop i nalozi"),
                ("mentor", "dan", ""),
            ],
        },
    }),
]

DPA = [
    ("h1", "Ugovor o obradi podataka — standardni aneks"),
    _header("Legal team", "verzija 2026-1"),
    ("h2", "1. Predmet"),
    ("p", "Ovaj aneks uređuje obradu podataka o ličnosti krajnjih korisnika koju "
          "Nexa Tech obavlja u ime klijenta, kao obrađivač. Klijent je rukovalac "
          "podacima i odgovara za zakonitost njihovog prikupljanja."),
    ("p", "Po raskidu ugovora podaci klijenta čuvaju se još 30 dana, radi "
          "eventualnog izvoza, a zatim se trajno brišu, uključujući i rezervne "
          "kopije. O povredi bezbednosti podataka Nexa Tech obaveštava klijenta "
          "bez odlaganja, a najkasnije u roku od 48 sati od saznanja."),
    ("h2", "2. Podobrađivači"),
    ("table", {
        "caption": "Tabela 1. Podobrađivači",
        "widths": [120, 210, 153],
        "rows": [
            ["Podobrađivač", "Namena", "Zemlja obrade"],
            ["cloud provajder", "hosting aplikacije i baze", "Nemačka"],
            ["SMS provajder", "slanje SMS obaveštenja", "Holandija"],
            ["e-mail servis", "slanje e-mail obaveštenja", "Irska"],
            ["payment provajder", "obrada plaćanja", "Litvanija"],
        ],
    }),
    ("p", "O dodavanju novog podobrađivača klijent se obaveštava najmanje 30 "
          "dana unapred i ima pravo da se usprotivi."),
]

PUTOVANJA = [
    ("h1", "Pravilnik o službenim putovanjima"),
    _header("People Ops", "važi od 1. februara 2026."),
    ("h2", "1. Planiranje"),
    ("p", "Službeno putovanje prijavljuje se najmanje 10 dana unapred, preko HR "
          "portala. Avio karte i smeštaj rezerviše travel desk, a ne sam "
          "zaposleni. Za letove kraće od šest sati koristi se ekonomska klasa."),
    ("p", "Troškovi se pravdaju u roku od pet radnih dana od povratka, uz "
          "originalne račune."),
    ("table", {
        "caption": "Tabela 1. Dnevnice",
        "widths": [200, 283],
        "rows": [
            ["Zemlja", "Dnevnica (EUR)"],
            ["Srbija", "25"],
            ["Nemačka", "60"],
            ["Holandija", "65"],
            ["ostale zemlje EU", "55"],
        ],
    }),
    ("h2", "2. Odobravanje"),
    ("p", "Slika 1 prikazuje ko odobrava zahtev za službeno putovanje, u "
          "zavisnosti od procenjenog troška."),
    ("figure", {
        "caption": "Slika 1. Odobravanje službenog putovanja",
        "spec": {
            "size": (170, 64), "box": (30, 9),
            "nodes": {
                "emp": (18, 48, "Zaposleni"),
                "lead": (62, 48, "Team lead"),
                "head": (106, 48, "Department head"),
                "cfo": (150, 48, "CFO"),
                "desk": (106, 12, "Travel desk"),
            },
            "edges": [
                ("emp", "lead", "zahtev"),
                ("lead", "head", "preko 500 EUR"),
                ("head", "cfo", "preko 2.000 EUR"),
                ("lead", "desk", ""),
                ("head", "desk", ""),
                ("cfo", "desk", ""),
            ],
        },
    }),
]

KODEKS = [
    ("h1", "Kodeks poslovnog ponašanja"),
    _header("People Ops", "važi od 1. januara 2026."),
    ("h2", "1. Pokloni"),
    ("p", "Zaposleni sme da primi poklon od klijenta ili dobavljača samo ako mu "
          "vrednost ne prelazi 50 EUR. Poklon veće vrednosti se vraća, a ako to "
          "nije moguće, predaje se People Ops-u."),
    ("h2", "2. Sukob interesa"),
    ("p", "Svaki mogući sukob interesa, na primer rad za konkurentsku firmu ili "
          "vlasnički udeo kod dobavljača, prijavljuje se People Ops-u u roku od "
          "pet radnih dana od saznanja."),
    ("h2", "3. Prijava nepravilnosti"),
    ("p", "Nepravilnosti se mogu prijaviti i anonimno, preko posebnog obrasca na "
          "internom portalu. Prijavu razmatra komisija od tri člana, koja "
          "odgovara u roku od 15 dana."),
]

DOCUMENTS_DODATNI = [
    ("tok-placanja", "pdf", "Tok plaćanja depozita karticom", TOK_PLACANJA),
    ("mrezna-topologija", "pdf", "Mrežna topologija produkcije", MREZA),
    ("monitoring-i-alarmi", "docx", "Monitoring i alarmi", MONITORING),
    ("kapacitet-baze-2026", "pdf", "Kapacitet baze podataka — 2026.", KAPACITET),
    ("roadmap-2027", "pdf", "Roadmap za 2027. godinu", ROADMAP),
    # Ometaci: stare verzije postojecih dokumenata.
    ("booking-arhitektura-2-2", "pdf", "Nexa Booking 2.2 — Arhitektura sistema (zastarelo)",
     ARHITEKTURA_22),
    ("sla-i-podrska-2025", "pdf", "SLA i nivoi podrške — 2025.", SLA_2025),
    # Opsti dokumenti.
    ("procedura-onboardinga", "docx", "Procedura onboardinga", ONBOARDING),
    ("ugovor-o-obradi-podataka", "pdf", "Ugovor o obradi podataka", DPA),
    ("pravilnik-o-putovanjima", "docx", "Pravilnik o službenim putovanjima", PUTOVANJA),
    ("kodeks-ponasanja", "pdf", "Kodeks poslovnog ponašanja", KODEKS),
]
