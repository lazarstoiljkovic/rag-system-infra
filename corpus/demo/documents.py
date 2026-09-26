"""
Sadrzaj demo korpusa — interna tehnicka dokumentacija fiktivne softverske
firme koja razvija web aplikacije.

  Firma     Nexa Tech Solutions d.o.o. (izmisljena), Novi Sad
  Proizvod  Nexa Booking — SaaS web aplikacija za online zakazivanje termina
            (saloni, ordinacije, servisi)

Sedam tehnickih dokumenata pokriva ono sto tipican tim za web razvoj pise:
arhitekturu, CI/CD, standarde koda, API specifikaciju, SLA, izvestaj o
performansama i plan migracije. Cetiri opsta dokumenta firme (pravilnik o
radu, organizacija i pozicije, finansijski izvestaj, politika bezbednosti)
cine korpus realnijim i sluze kao "ometaci" pretrage. Povezani su (isti servisi, isti incident), pa
postoje i pitanja koja traze vise dokumenata.

Nazivi servisa, timova i komponenti su onakvi kakve IT firme stvarno koriste
(`booking-service`, "Payments team", "Message queue"), a tekst je na srpskom
SA dijakriticima — kao u domacoj IT dokumentaciji. To je sadrzaj, ne kod.

Sve je izmisljeno — firma, proizvod, brojevi, incidenti — namerno: model ne
sme moci da pogodi odgovor bez retrievala (CLAUDE.md, "Korpus je
sinteticki"). Tehnologije (React, PostgreSQL, Redis, Kubernetes) su stvarne;
cinjenice o njihovoj upotrebi nisu.

Za svaku sliku vazi: bar jedna cinjenica postoji SAMO na slici. Neke su
namerno teske za opis recima (pripadnost grupi, strelica bez natpisa) — na
njima se ocekuje prednost varijante B. `generate.py` proverava sve automatski.
"""

COMPANY = "Nexa Tech Solutions d.o.o."
PRODUCT = "Nexa Booking"
AUTHOR = COMPANY + " (fiktivno)"


def _header(team, revision):
    return ("p", "Interni dokument · {} · {} · {}".format(COMPANY, team, revision))


ARHITEKTURA = [
    ("h1", "Nexa Booking 2.4 — Arhitektura sistema"),
    _header("Platform team", "revizija 6"),
    ("h2", "1. Namena"),
    ("p", "Nexa Booking je web aplikacija za online zakazivanje termina koju "
          "Nexa Tech razvija i održava kao SaaS. Koristi je oko 1.800 poslovnih "
          "klijenata — saloni, ordinacije i servisi — čiji krajnji korisnici "
          "zakazuju termine preko web klijenta ili partnerskih aplikacija. "
          "Frontend je single-page aplikacija u React-u, a backend čine četiri "
          "mikroservisa iza zajedničkog api-gateway servisa."),
    ("h2", "2. Servisi i podaci"),
    ("p", "Svi zahtevi klijenata prolaze kroz api-gateway, koji validira JWT "
          "token, primenjuje rate limiting i prosleđuje zahtev odgovarajućem "
          "servisu. Servisi međusobno komuniciraju sinhrono preko REST-a, osim "
          "notifikacija, koje idu asinhrono preko message queue-a, da spor SMS "
          "provajder ne bi usporio zakazivanje. Podaci se čuvaju u PostgreSQL "
          "bazi, a lista slobodnih termina se kešira u Redis-u 300 sekundi, jer "
          "je to najčešći upit u sistemu."),
    ("p", "Korisnička sesija ističe posle 30 minuta neaktivnosti. Plaćanja su "
          "najsporija operacija u sistemu, jer zavise od eksternog payment "
          "provajdera."),
    ("table", {
        "caption": "Tabela 1. Servisi",
        "widths": [135, 70, 50, 60, 168],
        "rows": [
            ["Servis", "Jezik", "Port", "Timeout", "Vlasnik"],
            ["api-gateway", "Go", "8080", "10 s", "Platform team"],
            ["booking-service", "Go", "8101", "3 s", "Booking team"],
            ["payment-service", "Go", "8102", "8 s", "Payments team"],
            ["notification-service", "Node.js", "8103", "5 s", "Notifications team"],
            ["catalog-service", "Node.js", "8104", "3 s", "Booking team"],
        ],
    }),
    ("h2", "3. Komponente"),
    ("p", "Slika 1 prikazuje komponente sistema i tok zahteva od web klijenta "
          "do baze podataka."),
    ("figure", {
        "caption": "Slika 1. Komponente sistema Nexa Booking",
        "spec": {
            "size": (170, 110), "box": (28, 9),
            "nodes": {
                "web": (16, 72, "Web klijent\n(React)"),
                "cdn": (16, 40, "CDN"),
                "gw": (58, 72, "api-gateway"),
                "book": (100, 88, "booking-service"),
                "cat": (100, 64, "catalog-service"),
                "pay": (100, 40, "payment-service"),
                "pgp": (146, 88, "PostgreSQL\nprimary"),
                "pgr": (146, 64, "PostgreSQL\nread replica"),
                "prov": (146, 40, "Payment provider\n(eksterni)"),
                "mq": (58, 100, "Message queue"),
                "notif": (16, 100, "notification-service"),
            },
            "edges": [
                ("web", "cdn", "statički fajlovi"),
                ("web", "gw", "HTTPS / JSON"),
                ("gw", "book", ""),
                ("gw", "cat", ""),
                ("gw", "pay", ""),
                ("book", "pgp", "write"),
                ("cat", "pgr", "read"),
                ("pay", "prov", "tokenizovana kartica"),
                ("book", "mq", "booking.created"),
                ("mq", "notif", ""),
            ],
        },
    }),
    ("h2", "4. Latencija"),
    ("p", "Slika 2 prikazuje p95 latenciju najvažnijih endpoint-a u produkciji, "
          "izmerenu tokom avgusta 2026."),
    ("figure", {
        "caption": "Slika 2. p95 latencija po endpoint-u (avgust 2026)",
        "scale": 0.85,
        "spec": {
            "kind": "bar", "title": "p95 latencija po endpoint-u, avgust 2026.",
            "x_label": "Endpoint", "y_label": "Latencija (ms)",
            "categories": ["GET /slots", "POST /bookings", "POST /payments", "GET /services"],
            "values": [84, 212, 468, 57], "y_max": 550, "fmt": "{:.0f}",
        },
    }),
]

CI_CD = [
    ("h1", "CI/CD proces — od commit-a do produkcije"),
    _header("Platform team", "revizija 3"),
    ("h2", "1. Pravila"),
    ("p", "Svaka izmena ide kroz merge request, koji moraju da odobre najmanje dva "
          "člana tima. Grana main je zaštićena: direktan push nije dozvoljen, a "
          "merge je moguć tek kad pipeline prođe bez greške. Pipeline se "
          "pokreće automatski na svaki push."),
    ("p", "Deploy u produkciju dozvoljen je samo utorkom i četvrtkom od 10 do 14 "
          "časova, kada je ceo tim na poslu. Produkcija se ažurira postepeno: "
          "nova verzija prvo dobija 10% saobraćaja tokom 30 minuta (canary "
          "release). Ako error rate u tom periodu pređe 1%, rollback na "
          "prethodnu verziju je automatski. Deploy u produkciju uvek traži "
          "ručno odobrenje."),
    ("table", {
        "caption": "Tabela 1. Okruženja",
        "widths": [85, 90, 160, 148],
        "rows": [
            ["Okruženje", "Namena", "Kako se ažurira", "Podaci"],
            ["dev", "razvoj", "automatski, na svaki push", "sintetički"],
            ["staging", "testiranje", "automatski, posle merge-a u main",
             "anonimizovana kopija produkcije"],
            ["production", "klijenti", "ručno odobrenje, pa canary", "stvarni"],
        ],
    }),
    ("h2", "2. Faze pipeline-a"),
    ("p", "Slika 1 prikazuje sve faze pipeline-a, od commit-a do produkcije."),
    ("figure", {
        "caption": "Slika 1. Faze pipeline-a",
        "spec": {
            "size": (170, 70), "box": (27, 9),
            "nodes": {
                "commit": (14, 58, "Commit"),
                "build": (48, 58, "Build + lint"),
                "unit": (82, 58, "Unit testovi"),
                "docker": (116, 58, "Docker image"),
                "registry": (152, 58, "Container\nregistry"),
                "staging": (152, 32, "Deploy na staging"),
                "e2e": (116, 32, "E2E testovi"),
                "approve": (82, 32, "Approval\n(release manager)"),
                "canary": (48, 32, "Canary 10%"),
                "prod": (14, 32, "Production 100%"),
                "rollback": (48, 7, "Auto rollback"),
            },
            "edges": [
                ("commit", "build", ""),
                ("build", "unit", ""),
                ("unit", "docker", ""),
                ("docker", "registry", ""),
                ("registry", "staging", ""),
                ("staging", "e2e", ""),
                ("e2e", "approve", "passed"),
                ("approve", "canary", ""),
                ("canary", "prod", "30 min"),
                ("canary", "rollback", "errors > 1%"),
            ],
        },
    }),
    ("h2", "3. Trajanje pipeline-a"),
    ("p", "Slika 2 prikazuje prosečno trajanje celog pipeline-a po mesecima. "
          "Najveće skraćenje doneo je keš zavisnosti, uveden u proleće 2026."),
    ("figure", {
        "caption": "Slika 2. Prosečno trajanje pipeline-a (2026)",
        "scale": 0.85,
        "spec": {
            "kind": "line", "title": "Prosečno trajanje pipeline-a, 2026.",
            "x_label": "Mesec", "y_label": "Minuta",
            "categories": ["jan", "feb", "mar", "apr", "maj", "jun"],
            "values": [24.5, 22.1, 19.8, 14.2, 13.6, 15.9], "y_max": 30,
        },
    }),
]

FRONTEND = [
    ("h1", "Frontend standardi"),
    _header("Frontend team", "važi od 1. aprila 2026."),
    ("h2", "1. Osnovna pravila"),
    ("p", "Frontend aplikacije Nexa Booking piše se u React-u i TypeScript-u, sa "
          "uključenim strict režimom. Komponente se imenuju u PascalCase obliku, "
          "jedna komponenta po fajlu. Svaki pull request koji menja UI mora da "
          "sadrži screenshot pre i posle izmene."),
    ("p", "Accessibility je obavezan, a ne poželjan: svaki novi ekran mora da "
          "prođe automatski audit pre merge-a i ručnu proveru tastaturom pre "
          "deploy-a u produkciju."),
    ("table", {
        "caption": "Tabela 1. Pravila i provere",
        "widths": [110, 200, 140],
        "rows": [
            ["Oblast", "Pravilo", "Kako se proverava"],
            ["Bundle size", "najviše 250 KB (gzip) po ruti", "automatski u CI"],
            ["Testovi", "coverage najmanje 80% deljenih komponenti", "CI izveštaj"],
            ["Accessibility", "WCAG 2.1, nivo AA", "automatski audit"],
            ["Code style", "ESLint i Prettier, bez upozorenja", "pre-commit hook"],
        ],
    }),
    ("h2", "2. Tok podataka"),
    ("p", "Slika 1 prikazuje propisani tok podataka u frontendu. Odstupanje od "
          "ovog toka je razlog za odbijanje pull request-a."),
    ("figure", {
        "caption": "Slika 1. Tok podataka u frontendu",
        "spec": {
            "size": (170, 60), "box": (26, 9),
            "nodes": {
                "comp": (20, 44, "React komponenta"),
                "action": (64, 44, "Action"),
                "client": (108, 44, "API client"),
                "gw": (152, 44, "api-gateway"),
                "store": (64, 10, "Store"),
            },
            "edges": [
                ("comp", "action", "user event"),
                ("action", "client", "request"),
                ("client", "gw", "HTTPS"),
                ("client", "store", "response"),
                ("store", "comp", ""),
            ],
        },
    }),
]

API = [
    ("h1", "Nexa Booking API v3 — rezervacije"),
    _header("Booking team", "revizija 12"),
    ("h2", "1. Osnovno"),
    ("p", "API je namenjen partnerskim aplikacijama. Base path je /api/v3, a svaki "
          "zahtev mora imati Bearer token koji partner dobija preko OAuth 2.0 "
          "client credentials toka. Liste se vraćaju paginirano, najviše 100 "
          "stavki po strani."),
    ("p", "Zahtev za novu rezervaciju mora imati header Idempotency-Key. Ključ se "
          "pamti 24 sata: ponovljen zahtev sa istim ključem vraća isti odgovor "
          "umesto da napravi drugu rezervaciju. Kada je termin u međuvremenu "
          "zauzet, API vraća status 409, a za neispravne podatke status 422."),
    ("table", {
        "caption": "Tabela 1. Endpoint-i",
        "widths": [60, 130, 195, 98],
        "rows": [
            ["Metoda", "Putanja", "Opis", "Rate limit (req/min)"],
            ["GET", "/slots", "slobodni termini za uslugu", "600"],
            ["POST", "/bookings", "nova rezervacija", "120"],
            ["GET", "/bookings/{id}", "detalji rezervacije", "600"],
            ["DELETE", "/bookings/{id}", "otkazivanje, najkasnije 2 sata pre termina", "60"],
        ],
    }),
    ("h2", "2. Tok nove rezervacije"),
    ("p", "Slika 1 prikazuje šta se dešava posle uspešnog poziva POST /bookings, "
          "sve do obaveštenja krajnjem korisniku."),
    ("figure", {
        "caption": "Slika 1. Tok nove rezervacije",
        "spec": {
            "size": (170, 64), "box": (29, 9),
            "nodes": {
                "partner": (16, 50, "Partner app"),
                "gw": (58, 50, "api-gateway"),
                "book": (101, 50, "booking-service"),
                "pay": (149, 50, "payment-service"),
                "mq": (101, 12, "Message queue"),
                "notif": (58, 12, "notification-service"),
                "user": (16, 12, "Krajnji korisnik"),
            },
            "edges": [
                ("partner", "gw", "POST /bookings"),
                ("gw", "book", "provera termina"),
                ("book", "pay", "depozit 20%"),
                ("book", "mq", "booking.created"),
                ("mq", "notif", ""),
                ("notif", "user", "SMS + e-mail"),
            ],
        },
    }),
]

SLA = [
    ("h1", "SLA i nivoi podrške — Nexa Booking"),
    _header("Customer Support", "važi od 1. januara 2026."),
    ("h2", "1. Obaveze"),
    ("p", "Uptime se meri mesečno, kao udeo minuta u kojima je aplikacija "
          "odgovarala na zahteve. Planirano održavanje najavljuje se najmanje 72 "
          "sata unapred i ne računa se kao nedostupnost. Za svaki započeti sat "
          "nedostupnosti preko obaveze iz plana klijent dobija kredit od 5% "
          "mesečne pretplate, a najviše 50%."),
    ("table", {
        "caption": "Tabela 1. Planovi podrške",
        "widths": [75, 75, 110, 145, 78],
        "rows": [
            ["Plan", "Uptime", "Prvi odgovor (kritično)", "Kanali podrške",
             "Cena (EUR mesečno)"],
            ["Starter", "99,5%", "8 radnih sati", "e-mail, radnim danima", "29"],
            ["Business", "99,9%", "2 sata", "e-mail i chat, svakog dana", "99"],
            ["Enterprise", "99,95%", "30 minuta", "telefon 24/7, dedicated inženjer", "349"],
        ],
    }),
    ("h2", "2. Obrada tiketa"),
    ("p", "Slika 1 prikazuje put tiketa od klijenta do onoga ko ga rešava. "
          "Kritični tiketi van radnog vremena stižu direktno do dežurnog "
          "inženjera."),
    ("figure", {
        "caption": "Slika 1. Put tiketa",
        "spec": {
            "size": (170, 64), "box": (28, 9),
            "nodes": {
                "client": (16, 50, "Klijent"),
                "portal": (58, 50, "Helpdesk portal"),
                "l1": (100, 50, "L1 support"),
                "l2": (148, 50, "L2 support"),
                "oncall": (148, 12, "On-call engineer"),
                "billing": (100, 12, "Billing"),
            },
            "edges": [
                ("client", "portal", "tiket"),
                ("portal", "l1", "trijaža"),
                ("l1", "l2", "tehnički problem"),
                ("l2", "oncall", "kritično"),
                ("l1", "billing", "pitanja o računu"),
            ],
        },
    }),
    ("h2", "3. Ostvareni uptime"),
    ("p", "Slika 2 prikazuje izmereni uptime u drugom kvartalu 2026. Uzroci "
          "odstupanja opisani su u kvartalnom izveštaju o performansama."),
    ("figure", {
        "caption": "Slika 2. Izmereni uptime, Q2 2026.",
        "scale": 0.8,
        "spec": {
            "kind": "bar", "title": "Izmereni uptime, Q2 2026.",
            "x_label": "Mesec", "y_label": "Uptime (%)",
            "categories": ["april", "maj", "jun"],
            "values": [99.97, 99.82, 99.99], "y_min": 99.5, "y_max": 100.05,
            "fmt": "{:.2f}",
        },
    }),
]

PERFORMANSE = [
    ("h1", "Izveštaj o performansama — Q2 2026."),
    _header("Platform team", "Q2 2026."),
    ("h2", "1. Load test"),
    ("p", "Pre letnje sezone, kada broj rezervacija raste, sproveden je load test "
          "sa ciljem od 1.500 zahteva u sekundi. Sistem je izdržao 1.850 "
          "zahteva u sekundi pre nego što je p95 latencija prešla 500 "
          "milisekundi. Bottleneck je bio payment-service, zbog ograničenja "
          "eksternog payment provajdera na broj istovremenih konekcija."),
    ("table", {
        "caption": "Tabela 1. Rezultati load testa",
        "widths": [150, 90, 90, 90],
        "rows": [
            ["Scenario", "Zahteva u sekundi", "p95 (ms)", "Error rate (%)"],
            ["pretraga termina", "1.200", "96", "0,01"],
            ["nova rezervacija", "400", "238", "0,05"],
            ["plaćanje", "150", "512", "0,40"],
            ["mešovito (realno)", "1.850", "497", "0,12"],
        ],
    }),
    ("h2", "2. Incident u maju"),
    ("p", "Najveći incident u kvartalu desio se 17. maja: istekao je TLS "
          "sertifikat api-gateway-a, pa aplikacija nije bila dostupna 80 "
          "minuta. Automatsko obnavljanje sertifikata nije radilo od prelaska "
          "na novi DNS nalog u martu, a upozorenje o isteku slalo se na ugašenu "
          "e-mail adresu. Posle incidenta obnavljanje je ispravljeno, a "
          "upozorenje prebačeno u on-call sistem."),
    ("h2", "3. Brzina učitavanja stranica (LCP)"),
    ("p", "Slika 1 prikazuje Largest Contentful Paint (LCP) po stranici, merenu "
          "kod stvarnih korisnika na mobilnim uređajima. Preporučena granica je "
          "2,5 sekunde."),
    ("figure", {
        "caption": "Slika 1. LCP po stranici, mobilni uređaji",
        "scale": 0.8,
        "spec": {
            "kind": "bar", "title": "LCP po stranici (mobilni), Q2 2026.",
            "x_label": "Stranica", "y_label": "LCP (s)",
            "categories": ["Home", "Search", "Booking", "Profile"],
            "values": [1.8, 2.4, 2.9, 1.6], "y_max": 3.5,
        },
    }),
]

KUBERNETES = [
    ("h1", "Plan migracije na Kubernetes (2027)"),
    _header("Platform team", "draft 2"),
    ("h2", "1. Ciljevi"),
    ("p", "Nexa Booking danas radi na virtuelnim mašinama koje se ručno "
          "održavaju. Migracija na managed Kubernetes klaster u dve "
          "availability zone treba da omogući autoscaling pred sezonu i brže "
          "deploy-e. Baza podataka ostaje van klastera, kao managed PostgreSQL "
          "servis, jer njen životni ciklus ne treba vezivati za klaster."),
    ("p", "Servisi se u klasteru grupišu u zasebne namespace-ove prema domenu i "
          "bezbednosnim zahtevima, sa network policy pravilima koja dozvoljavaju "
          "samo propisane tokove između njih. Prvi se migrira servis sa "
          "najmanjim rizikom."),
    ("table", {
        "caption": "Tabela 1. Faze migracije",
        "widths": [40, 95, 160, 188],
        "rows": [
            ["Faza", "Period", "Šta se migrira", "Uslov za sledeću fazu"],
            ["F1", "januar 2027.", "notification-service", "nijedna izgubljena poruka dve nedelje"],
            ["F2", "februar–mart 2027.", "catalog-service, booking-service", "p95 bez pogoršanja"],
            ["F3", "april 2027.", "payment-service", "security audit prošao"],
            ["F4", "maj 2027.", "api-gateway; gašenje VM-ova", "svi servisi na klasteru"],
        ],
    }),
    ("h2", "2. Ciljna arhitektura"),
    ("p", "Slika 1 prikazuje raspored servisa u klasteru posle poslednje faze."),
    ("figure", {
        "caption": "Slika 1. Ciljna arhitektura na Kubernetes-u",
        "spec": {
            "size": (170, 96), "box": (30, 9),
            "groups": [
                (2, 16, 134, 94, "Kubernetes klaster (2 AZ)"),
                (6, 54, 44, 86, "namespace: edge"),
                (50, 54, 130, 86, "namespace: core"),
                (6, 20, 44, 50, "namespace: pci", "dole"),
                (50, 20, 130, 50, "namespace: async", "dole"),
            ],
            "nodes": {
                "gw": (25, 68, "api-gateway"),
                "book": (70, 68, "booking-service"),
                "cat": (110, 68, "catalog-service"),
                "pay": (25, 33, "payment-service"),
                "mq": (70, 33, "Message queue"),
                "notif": (110, 33, "notification-service"),
                "pg": (154, 68, "PostgreSQL\n(managed)"),
            },
            "edges": [
                ("gw", "book", ""),
                ("gw", "pay", ""),
                ("book", "mq", "event"),
                ("mq", "notif", ""),
                ("cat", "pg", ""),
            ],
        },
    }),
    ("h2", "3. Troškovi"),
    ("p", "Slika 2 prikazuje očekivani mesečni trošak infrastrukture tokom "
          "migracije, dok virtuelne mašine i klaster rade paralelno."),
    ("figure", {
        "caption": "Slika 2. Očekivani mesečni trošak infrastrukture, 2027.",
        "scale": 0.85,
        "spec": {
            "kind": "line", "title": "Očekivani trošak infrastrukture, 2027.",
            "x_label": "Mesec", "y_label": "Hiljade EUR",
            "categories": ["jan", "feb", "mar", "apr", "maj", "jun"],
            "values": [6.4, 7.9, 8.3, 7.1, 5.8, 5.2], "y_max": 10,
        },
    }),
]

PRAVILNIK = [
    ("h1", "Pravilnik o radu"),
    _header("People Ops", "važi od 1. januara 2026."),
    ("h2", "1. Radno vreme i hibridni rad"),
    ("p", "Radno vreme je osam sati dnevno, uz fleksibilan početak između 8 i 10 "
          "časova. Nexa Tech radi po hibridnom modelu: dolazak u kancelariju "
          "obavezan je ponedeljkom i sredom, a ostalim danima zaposleni biraju "
          "gde rade. Timovi mogu dogovoriti dodatne zajedničke dane, ali ne "
          "mogu ukinuti obavezne."),
    ("p", "Svaki zaposleni dobija laptop, koji se menja na svake tri godine, i "
          "jednokratni budžet od 400 EUR za opremanje radnog mesta kod kuće."),
    ("h2", "2. Godišnji odmor i odsustva"),
    ("p", "Godišnji odmor iznosi 22 radna dana, uz jedan dodatni dan za svakih "
          "navršenih pet godina staža u firmi, a najviše 30 dana. Zahtev se "
          "podnosi preko HR portala najmanje 15 dana unapred. Neiskorišćeni "
          "dani prenose se u narednu godinu i moraju se iskoristiti do 30. juna."),
    ("table", {
        "caption": "Tabela 1. Plaćena odsustva",
        "widths": [220, 100, 140],
        "rows": [
            ["Razlog", "Trajanje", "Potrebna dokumentacija"],
            ["sklapanje braka", "5 radnih dana", "venčani list"],
            ["rođenje deteta", "5 radnih dana", "izvod iz matične knjige"],
            ["selidba", "2 radna dana", "nije potrebna"],
            ["smrt člana uže porodice", "5 radnih dana", "umrlica"],
            ["stručno usavršavanje", "3 radna dana godišnje", "potvrda o prisustvu"],
        ],
    }),
    ("h2", "3. Odobravanje odsustva"),
    ("p", "Slika 1 prikazuje put zahteva za odsustvo, od podnošenja do "
          "evidencije."),
    ("figure", {
        "caption": "Slika 1. Odobravanje zahteva za odsustvo",
        "spec": {
            "size": (170, 60), "box": (28, 9),
            "nodes": {
                "emp": (16, 46, "Zaposleni"),
                "portal": (58, 46, "HR portal"),
                "lead": (100, 46, "Team lead"),
                "ops": (148, 46, "People Ops"),
                "head": (100, 12, "Department head"),
            },
            "edges": [
                ("emp", "portal", "zahtev"),
                ("portal", "lead", "odobrenje"),
                ("lead", "ops", "evidencija"),
                ("lead", "head", "više od 10 radnih dana"),
                ("head", "ops", ""),
            ],
        },
    }),
]

ORGANIZACIJA = [
    ("h1", "Organizacija i pozicije"),
    _header("People Ops", "stanje na dan 1. jula 2026."),
    ("h2", "1. Firma"),
    ("p", "Nexa Tech Solutions je softverska firma osnovana 2017. godine, sa "
          "sedištem u Novom Sadu i kancelarijom u Nišu. Ima 86 zaposlenih, od "
          "čega 61 u inženjerskim timovima. Pored razvoja sopstvenog proizvoda "
          "Nexa Booking, firma razvija web aplikacije po narudžbini za klijente "
          "iz Evrope."),
    ("p", "Karijerni put u inženjeringu ima pet nivoa. Prelazak na viši nivo "
          "razmatra se dva puta godišnje, u martu i septembru, na osnovu ocene "
          "team lead-a i razgovora sa kandidatom."),
    ("table", {
        "caption": "Tabela 1. Pozicije u inženjeringu",
        "widths": [150, 50, 110, 173],
        "rows": [
            ["Pozicija", "Nivo", "Iskustvo", "Bruto zarada (EUR mesečno)"],
            ["Junior developer", "L1", "0–2 godine", "1.100–1.600"],
            ["Medior developer", "L2", "2–4 godine", "1.700–2.500"],
            ["Senior developer", "L3", "4+ godina", "2.600–3.800"],
            ["Tech lead", "L4", "6+ godina", "3.600–4.600"],
            ["Engineering manager", "L5", "8+ godina", "4.200–5.500"],
        ],
    }),
    ("h2", "2. Organizaciona šema"),
    ("p", "Slika 1 prikazuje upravu firme i raspored inženjerskih timova po "
          "kancelarijama."),
    ("figure", {
        "caption": "Slika 1. Organizaciona šema",
        "spec": {
            "size": (170, 100), "box": (26, 9),
            "groups": [
                (2, 26, 112, 56, "Kancelarija Novi Sad", "dole"),
                (118, 2, 168, 56, "Kancelarija Niš", "dole"),
            ],
            "nodes": {
                "ceo": (85, 92, "CEO"),
                "cto": (40, 74, "CTO"),
                "cfo": (85, 74, "CFO"),
                "people": (130, 74, "Head of People"),
                "platform": (20, 38, "Platform team"),
                "booking": (56, 38, "Booking team"),
                "frontend": (92, 38, "Frontend team"),
                "payments": (143, 38, "Payments team"),
                "notif": (143, 14, "Notifications team"),
            },
            "edges": [
                ("ceo", "cto", ""),
                ("ceo", "cfo", ""),
                ("ceo", "people", ""),
                ("cto", "platform", ""),
                ("cto", "booking", ""),
                ("cto", "frontend", ""),
                ("cto", "payments", ""),
            ],
        },
    }),
]

FINANSIJE = [
    ("h1", "Finansijski izveštaj — prva polovina 2026."),
    _header("Finance", "za upravu i zaposlene"),
    ("h2", "1. Sažetak"),
    ("p", "U prvoj polovini 2026. Nexa Tech je ostvario prihod od 2,84 miliona "
          "EUR, što je 18% više nego u istom periodu prošle godine. Oko 70% "
          "prihoda dolazi od pretplata na Nexa Booking, a ostatak od razvoja po "
          "narudžbini i ugovora o održavanju. EBITDA marža iznosi 21%, a broj "
          "poslovnih klijenata Nexa Booking-a porastao je sa 1.520 na 1.800."),
    ("p", "Najveći pojedinačni rast zabeležen je kod razvoja po narudžbini, "
          "zahvaljujući dva nova klijenta iz Nemačke. Firma nema kreditnih "
          "obaveza, a gotovinske rezerve pokrivaju više od šest meseci troškova."),
    ("table", {
        "caption": "Tabela 1. Prihod po izvoru (EUR)",
        "widths": [200, 95, 95, 95],
        "rows": [
            ["Izvor prihoda", "Q1 2026.", "Q2 2026.", "Ukupno"],
            ["Pretplate na Nexa Booking", "951.000", "1.052.000", "2.003.000"],
            ["Razvoj po narudžbini", "268.000", "311.000", "579.000"],
            ["Održavanje i podrška", "120.000", "138.000", "258.000"],
            ["Ukupno", "1.339.000", "1.501.000", "2.840.000"],
        ],
    }),
    ("h2", "2. Prihod po mesecima"),
    ("p", "Slika 1 prikazuje ukupan prihod po mesecima. Pad u aprilu posledica je "
          "završetka jednog velikog projekta po narudžbini."),
    ("figure", {
        "caption": "Slika 1. Prihod po mesecima, H1 2026.",
        "scale": 0.85,
        "spec": {
            "kind": "line", "title": "Prihod po mesecima, H1 2026.",
            "x_label": "Mesec", "y_label": "Hiljade EUR",
            "categories": ["jan", "feb", "mar", "apr", "maj", "jun"],
            "values": [418, 432, 489, 470, 502, 529], "y_max": 600, "fmt": "{:.0f}",
        },
    }),
    ("h2", "3. Struktura troškova"),
    ("p", "Slika 2 prikazuje strukturu operativnih troškova u prvoj polovini "
          "godine. Zarade su, očekivano, najveća stavka."),
    ("figure", {
        "caption": "Slika 2. Struktura troškova, H1 2026.",
        "scale": 0.8,
        "spec": {
            "kind": "bar", "title": "Struktura troškova, H1 2026.",
            "x_label": "Stavka", "y_label": "Udeo u troškovima (%)",
            "categories": ["Zarade", "Cloud", "Kancelarije", "Marketing", "Ostalo"],
            "values": [63, 11, 8, 6, 12], "y_max": 75, "fmt": "{:.0f}%",
        },
    }),
]

BEZBEDNOST = [
    ("h1", "Politika bezbednosti informacija"),
    _header("Security", "revizija 4"),
    ("h2", "1. Pristup i lozinke"),
    ("p", "Lozinka mora imati najmanje 14 znakova i ne sme se koristiti ni za "
          "jedan drugi servis. Periodična promena lozinke se ne traži, ali je "
          "obavezna odmah posle sumnje na kompromitaciju. Dvofaktorska "
          "autentikacija je obavezna za sve naloge firme, a za pristup "
          "produkciji koristi se isključivo hardverski ključ."),
    ("p", "Diskovi svih laptopova moraju biti šifrovani, a ekran se automatski "
          "zaključava posle pet minuta neaktivnosti. Gubitak ili krađa uređaja "
          "prijavljuje se odmah, kao bezbednosni incident."),
    ("table", {
        "caption": "Tabela 1. Klasifikacija podataka",
        "widths": [110, 200, 173],
        "rows": [
            ["Klasa", "Primeri", "Pravila"],
            ["Javno", "sajt, blog, javna dokumentacija API-ja", "bez ograničenja"],
            ["Interno", "interna dokumentacija, planovi", "samo zaposleni"],
            ["Poverljivo", "ugovori, podaci o zaradama", "samo ovlašćeni, šifrovano"],
            ["Strogo poverljivo", "podaci o platnim karticama, lozinke",
             "samo namenski sistemi, nikad u e-mailu"],
        ],
    }),
    ("h2", "2. Prijava incidenta"),
    ("p", "Svaki zaposleni koji primeti sumnjivu aktivnost prijavljuje je odmah, "
          "u kanalu #security-incident. Slika 1 prikazuje dalji tok prijave."),
    ("figure", {
        "caption": "Slika 1. Tok prijave bezbednosnog incidenta",
        "spec": {
            "size": (170, 64), "box": (28, 9),
            "nodes": {
                "emp": (16, 50, "Zaposleni"),
                "sec": (64, 50, "Security on-call"),
                "cto": (112, 50, "CTO"),
                "legal": (64, 12, "Pravna služba"),
                "reg": (112, 12, "Poverenik\n(regulator)"),
            },
            "edges": [
                ("emp", "sec", "#security-incident"),
                ("sec", "cto", "ozbiljan incident"),
                ("sec", "legal", "curenje ličnih podataka"),
                ("legal", "reg", "prijava u roku od 72 h"),
            ],
        },
    }),
]

# (ime fajla, format, naslov, blokovi)
DOCUMENTS = [
    ("booking-arhitektura", "pdf", "Nexa Booking 2.4 — Arhitektura sistema", ARHITEKTURA),
    ("ci-cd-proces", "pdf", "CI/CD proces", CI_CD),
    ("frontend-standardi", "docx", "Frontend standardi", FRONTEND),
    ("booking-api-v3", "pdf", "Nexa Booking API v3 — rezervacije", API),
    ("sla-i-podrska", "pdf", "SLA i nivoi podrške", SLA),
    ("izvestaj-performanse-q2-2026", "docx", "Izveštaj o performansama — Q2 2026.", PERFORMANSE),
    ("plan-migracije-kubernetes", "pdf", "Plan migracije na Kubernetes", KUBERNETES),
    # Opsti dokumenti firme — realniji korpus i "ometaci" za pretragu.
    ("pravilnik-o-radu", "docx", "Pravilnik o radu", PRAVILNIK),
    ("organizacija-i-pozicije", "pdf", "Organizacija i pozicije", ORGANIZACIJA),
    ("finansijski-izvestaj-h1-2026", "pdf", "Finansijski izveštaj — H1 2026.", FINANSIJE),
    ("politika-bezbednosti", "pdf", "Politika bezbednosti informacija", BEZBEDNOST),
]
