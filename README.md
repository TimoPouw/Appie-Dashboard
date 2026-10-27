# Appie-Dashboard: Albert Heijn in Home Assistant

[![Release](https://img.shields.io/github/v/release/TimoPouw/Appie-Dashboard)](https://github.com/TimoPouw/Appie-Dashboard/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![License](https://img.shields.io/github/license/TimoPouw/Appie-Dashboard)](LICENSE)

Een 100% ge-vibe-code Home Assistant-integratie voor je Albert Heijn-account (de Appie-app). Dit is een fork van [eejeha/Appie-Dashboard](https://github.com/eejeha/Appie-Dashboard) met extra's; het domein blijft `appie`, dus hij vervangt het origineel zonder opnieuw in te loggen.

- **Boodschappenlijst**: de lijst uit de AH-app als to-do-lijst, twee kanten op gesynchroniseerd (elke minuut). Toevoegen, afvinken, hernoemen en verwijderen werkt vanuit HA én vanuit de app. Typ een productnummer (bijv. `441199`) om een echt AH-product toe te voegen in plaats van vrije tekst.
- **Wat kost je lijst**: de prijs van de producten op je lijst, na bonuskorting.
- **Vergeet niet**: de suggesties die de app onder je lijst laat zien.
- **Bonus voor ons**: alleen de bonus die ertoe doet: je persoonlijke bonus, bonus op producten die je eerder kocht, en bonus op wat op je lijst staat (die staat bovenaan, en volgt je lijst meteen).
- **Kassabonnen**: je laatste kassabon met artikelen en korting, wat je deze maand bij AH hebt uitgegeven, en elke recente bon openen (ook als PDF).
- **Vaak gekocht**: knoppen met wat je het vaakst koopt (standaard 10, geteld over de kassabonnen van de afgelopen 4 maanden; beide in te stellen). Eén tik zet het product op je lijst; staat het er al, dan komt er één bij.
- **Je winkel**: open of dicht, openingstijden, en de koopjes van vandaag. Staat er iets uit Vaak gekocht tussen, dan krijg je een event.
- **Bonus Box, spotlight en bonus per categorie**: je persoonlijke Bonus Box, de uitgelichte bonus van de week, en alle bonus in een categorie.
- **Favoriete lijsten**: je lijstjes uit de app bekijken, er iets op zetten, of een heel lijstje op je boodschappenlijst zetten.
- **Producten opzoeken**: details en voedingswaarden van een product.
- **Zoeken en toevoegen op naam**: `appie.add_product` voor Assist, bijvoorbeeld "zet halfvolle melk op de lijst".

> **Met dank aan [Willem de Groot](https://github.com/gwillem) en [appie-go](https://github.com/gwillem/appie-go).** Zonder zijn uitzoekwerk aan de AH-app had deze integratie niet bestaan. Zie [Dankjewel](#dankjewel) onderaan.

> Dit gebruikt de onofficiële, reverse-engineered API van de AH-app. Niet gelieerd aan Albert Heijn. AH kan de API of de inlogstap op elk moment veranderen.
>
> Het AH-logo is een merk van Albert Heijn en staat er alleen in zodat je de integratie herkent in Home Assistant.

## Entiteiten

| Entiteit | Inhoud |
|---|---|
| `todo.albert_heijn_boodschappenlijst` | De boodschappenlijst. Aantal en bonus staan in de omschrijving van een item. |
| `sensor.albert_heijn_lijst_kosten` | Wat de producten op je lijst kosten na korting (€). Attributen `zonder_korting`, `korting`, `aantal_producten`, `aantal_vrije_tekst` (vrije tekst heeft geen prijs). Afgevinkte items tellen niet mee. |
| `sensor.albert_heijn_vergeet_niet` | Aantal "vergeet niet"-suggesties. Attribuut `suggesties`: lijst met `product_id`, `title`, `image`, `size`, `is_bonus`, `bonus_mechanism`, `price`, `price_before`. |
| `sensor.albert_heijn_bonus_voor_ons` | Aantal relevante aanbiedingen. Attribuut `offers`: lijst met `key`, `title`, `mechanism` ("1 + 1 GRATIS"), `price`, `price_was`, `image`, `source` (`op_lijst` / `persoonlijk` / `eerder_gekocht`), `on_list`, `activated`, `end_date`. Ook `period_start`, `period_end`, `on_list`, `personal`. `on_list` volgt je lijst direct. |
| `sensor.albert_heijn_laatste_kassabon` | Totaal van de laatste kassabon (€). Attributen `datetime`, `items`, `discounts`, `discount_total`, `payments`, `recent` (laatste 10 bonnen, elk met `datetime`, `total`, `id` en `pdf_url`). |
| `sensor.albert_heijn_uitgaven_deze_maand` | Som van de kassabonnen deze maand (€, reset op de 1e; met langetermijnstatistiek). Attributen `receipts` en `per_maand` (de afgelopen 12 maanden: `maand`, `naam`, `totaal`, `bonnen`). |
| `select.albert_heijn_kassabon` | Kies een van je recente kassabonnen ("zo 4 okt 2026 15:00 · € 36,16"). |
| `sensor.albert_heijn_gekozen_kassabon` | De gekozen bon (€). Attributen `receipt_id`, `datetime`, `items`, `discounts`, `discount_total`, `payments`, `pdf_url`. |
| `sensor.albert_heijn_vaak_gekocht` | Aantal producten in Vaak gekocht. Attribuut `producten`: de hele ranglijst met `rank`, `title`, `times_bought`, `product_id`, `bonus`, `on_list`, `quantity_on_list`, `entity_picture`. |
| `button.albert_heijn_vaak_gekocht_1` … `_N` | Je vaakst gekochte producten, op volgorde. Naam en plaatje volgen het product; attributen `rank`, `title`, `times_bought`, `product_id`, `bonus`, `on_list`, `quantity_on_list`. Indrukken = op de lijst zetten. Producten die AH niet online verkoopt (losse bananen) gaan er als vrije tekst op. |
| `sensor.albert_heijn_bonus_spotlight` | Aantal uitgelichte bonusaanbiedingen van de week. Attribuut `offers`: dezelfde velden als bij Bonus voor ons (`source` is `spotlight`), `on_list` volgt je lijst. |
| `sensor.albert_heijn_bonus_box` | Aantal aanbiedingen in je persoonlijke Bonus Box. Attributen `max_activaties`, `geactiveerd`, `aanbiedingen` (`id`, `title`, `category`, `mechanism`, `price`, `price_was`, `image`, `activated`, `start_date`, `end_date`). |
| `sensor.albert_heijn_favoriete_lijsten` | Aantal favoriete lijsten. Attribuut `lijsten`: `id`, `naam`, `aantal`, `image`. |
| `binary_sensor.albert_heijn_winkel_open` | Is je vaste winkel nu open? |
| `sensor.albert_heijn_winkel` | Sluitingstijd van vandaag ("22:00") of `gesloten`. Attributen `store_id`, `adres`, `openingstijden` (de komende dagen: `datum`, `dag`, `open`, `dicht`), `services`. |
| `sensor.albert_heijn_koopjes` | Aantal koopjes (laatste-kans-afprijzingen) in je winkel. Attribuut `items`: `product_id`, `title`, `size`, `category`, `markdown_type`, `expires`, `is_favoriet`, `price`, `price_was`, `percentage`. |

Grote attributen (`offers`, `items`, `recent`, `producten`, `suggesties` en alles van de gekozen kassabon) worden niet in de database opgeslagen.

Kassabonnen zijn alleen de bonnen uit de winkel waarbij je je Bonuskaart (app) hebt gescand, net als in de app.

### Kassabonnen bekijken

Kies een bon in `select.albert_heijn_kassabon`; de integratie haalt hem op en zet hem in `sensor.albert_heijn_gekozen_kassabon`. Er wordt niets opgeslagen: alleen de gekozen bon staat in het geheugen. Elke bon in `recent` en de gekozen bon hebben een `pdf_url`: open die link en AH levert de echte bon als PDF. De link bevat een willekeurige sleutel die bij elke herstart verandert, en werkt alleen voor je eigen recente bonnen.

## Hoe vaak er gevraagd wordt

| Wat | Hoe vaak |
|---|---|
| Boodschappenlijst | elke minuut |
| Lijst kosten | als de producten of aantallen op je lijst veranderen (één keer per reeks wijzigingen, een minuut na de eerste), en elke 6 uur |
| Vergeet niet | als de producten op je lijst veranderen, maximaal eens per 15 minuten, en elke 6 uur |
| Bonus | elke 6 uur en bij een nieuwe bonusweek; `on_list` rekent zonder extra vraag mee met je lijst |
| Bonus spotlight, Bonus Box | elke 6 uur |
| Favoriete lijsten | elke 30 minuten |
| Kassabonnen | elk uur |
| Vaak gekocht | elke 12 uur (elke bon maar één keer) |
| Winkel | elke 12 uur; open of dicht wordt elke minuut lokaal uitgerekend |
| Koopjes | elke 30 minuten, alleen als je winkel open is |

## Opties

Instellingen → Apparaten & diensten → Albert Heijn → **Configureren**:

- **Aantal producten** (10 tot 50, standaard 10): hoeveel Vaak gekocht-knoppen. Zet je het lager, dan verdwijnen de overbodige knoppen.
- **Dagen aan kassabonnen** (30 tot 365, standaard 120): over welke periode Vaak gekocht telt.

Opslaan herlaadt de integratie; een herstart is niet nodig.

## Services

Alle services geven een antwoord terug (`response_variable` in een script).

**`appie.search`**: producten zoeken.

```yaml
action: appie.search
data:
  zoekterm: halfvolle melk
  aantal: 5
response_variable: resultaat
```

```yaml
producten:
  - product_id: 900
    title: AH Halfvolle melk 2L
    size: 2 l
    price: 2.19
    image: https://static.ah.nl/...
    is_bonus: false
    bonus_mechanism: null
```

**`appie.add_product`**: zoekt een product en zet de beste match als echt product op je lijst. Wat in Vaak gekocht staat gaat voor, dan wat je eerder kocht, dan het beste zoekresultaat. `aantal` is optioneel (standaard 1).

```yaml
action: appie.add_product
data:
  zoekterm: halfvolle melk
```

```yaml
product_id: 901
title: Campina Halfvolle melk
size: 1 l
price: 1.59
image: null
is_bonus: false
bonus_mechanism: null
match: eerder_gekocht      # of vaak_gekocht / beste_zoekresultaat
quantity_on_list: 2
```

Voor Assist, in `custom_sentences/nl/appie.yaml`:

```yaml
language: nl
intents:
  AppieAddProduct:
    data:
      - sentences:
          - "zet {product} op [de] [boodschappen]lijst"
lists:
  product:
    wildcard: true
```

met in `configuration.yaml`:

```yaml
intent_script:
  AppieAddProduct:
    action:
      - action: appie.add_product
        data:
          zoekterm: "{{ product }}"
        response_variable: gekozen
    speech:
      text: "{{ gekozen.title }} staat op de lijst."
```

**`appie.get_product`**: één product met details en voedingswaarden.

```yaml
action: appie.get_product
data:
  product_id: 436752
response_variable: product
```

```yaml
product_id: 436752
title: AH Biologisch Rundergehakt
size: 300 g
price: 5.66
image: https://static.ah.nl/...
is_bonus: true
bonus_mechanism: 10% KORTING
brand: AH Biologisch
category: Vlees
subcategory: Rundergehakt
nutriscore: D
orderable: true
previously_bought: true
properties: [biologisch]
description: Biologisch rundergehakt
nutrition:
  - name: Energie
    value: 1011 kJ (243 kcal)
```

**`appie.get_products`**: meerdere producten tegelijk (`product_ids: [441199, 111]`). Antwoord: `producten` met dezelfde velden als `appie.search`, in de volgorde die je vroeg.

**`appie.get_subcategories`**: de subcategorieën van een productcategorie (`categorie_id: 6401`). Hoe AH dat antwoord vormgeeft staat niet in appie-go, dus je krijgt het letterlijk terug onder `antwoord`.

**`appie.bonus`**: zonder `categorie` de bonuscategorieën van deze week, met een categorie alle aanbiedingen daarin.

```yaml
action: appie.bonus
data:
  categorie: Zuivel, eieren
response_variable: bonus
```

```yaml
categorie: Zuivel, eieren
aanbiedingen:
  - key: product:111
    title: AH Roomboter
    mechanism: 2e halve prijs
    source: categorie
    price: 2.47
    price_was: 3.29
    image: null
    end_date: "2026-10-11"
    activated: null
    on_list: false
```

**`appie.get_favorite_list`**: de producten op een favoriete lijst (`lijst`: naam of id).

```yaml
lijst: Weekboodschappen
id: 305e6a50-...
producten:
  - product_id: 111
    title: AH Roomboter
    size: 250 g
    price: 3.29
    image: null
    is_bonus: false
    bonus_mechanism: null
    quantity: 1
```

**`appie.add_to_favorite_list`**: zet een product op een favoriete lijst, met `zoekterm` (wat je vaak koopt gaat voor) of `product_id`, en optioneel `aantal`.

```yaml
action: appie.add_to_favorite_list
data:
  lijst: Feestje
  zoekterm: chips
```

Antwoord: het gekozen product (zoals bij `appie.add_product`), plus `lijst` en `quantity`.

**`appie.favorite_list_to_list`**: zet een hele favoriete lijst op je boodschappenlijst. Wat er al op staat wordt alleen aangevuld, nooit verlaagd.

```yaml
action: appie.favorite_list_to_list
data:
  lijst: Weekboodschappen
```

```yaml
lijst: Weekboodschappen
toegevoegd:
  - product_id: 222
    title: AH Courgette
    quantity: 3
al_op_lijst:
  - product_id: 111
    title: AH Roomboter
```

**`appie.get_receipt`**: een recente kassabon ophalen. Zonder `receipt_id` krijg je de laatste.

```yaml
action: appie.get_receipt
data:
  receipt_id: "{{ state_attr('sensor.albert_heijn_laatste_kassabon', 'recent')[1].id }}"
response_variable: bon
```

```yaml
receipt_id: AH-...
datetime: "2026-10-03T09:00:00+02:00"
total: 6.92
items:
  - name: AH kaas
    quantity: 1
    amount: 6.92
discounts: []
discount_total: 0
payments: [PINNEN]
pdf_url: /api/appie/kassabon/AH-...?token=...
```

## Event

`appie_koopje_favoriet` komt één keer per koopje van een product uit Vaak gekocht (ook niet opnieuw na een herstart). Data: `product_id`, `title`, `size`, `category`, `markdown_type`, `expires`, `price`, `price_was`, `store_id`.

```yaml
triggers:
  - trigger: event
    event_type: appie_koopje_favoriet
actions:
  - action: notify.mobile_app_telefoon
    data:
      message: "Koopje: {{ trigger.event.data.title }} voor € {{ trigger.event.data.price }}"
```

## Installeren

Met één klik in je eigen Home Assistant:

[![Open je Home Assistant en open deze repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TimoPouw&repository=Appie-Dashboard&category=integration)

Installeer **Albert Heijn**, herstart Home Assistant en voeg daarna de integratie toe:

[![Open je Home Assistant en voeg de integratie Albert Heijn toe.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=appie)

Of met de hand:

1. HACS → ⋮ → **Custom repositories** → `https://github.com/TimoPouw/Appie-Dashboard`, type **Integration**.
2. Installeer **Albert Heijn** en herstart Home Assistant.
3. Instellingen → Apparaten & diensten → **Integratie toevoegen** → *Albert Heijn*.

### Beta-versies

Versies met `-beta` in de naam (zoals `v0.3.0-beta.1`) zijn pre-releases. HACS laat ze alleen zien als je bij de integratie in HACS ⋮ → **Opnieuw downloaden** kiest en **Bètaversies tonen** aanzet. Werkt Home Assistant 2025.8 of nieuwer; het logo in de integratielijst verschijnt vanaf Home Assistant 2026.3.

## Dashboard

In [`dashboards/appie.yaml`](dashboards/appie.yaml) staat een kant-en-klaar dashboard met vier tabbladen: **Boodschappen** (lijst, kosten, Vaak gekocht-knoppen, Vergeet niet, favoriete lijsten), **Bonus** (bonus voor jou, Bonus Box, spotlight), **Kassabonnen** (uitgaven per maand, recente bonnen met PDF, bon bekijken) en **Winkel** (openingstijden en koopjes). Het gebruikt alleen standaardkaarten van Home Assistant, dus je hoeft niets extra te installeren.

1. Instellingen → Dashboards → **Dashboard toevoegen** → **Nieuw dashboard vanaf nul**, noem het bijvoorbeeld *Albert Heijn*.
2. Open het, ⋮ → **Bewerken** → ⋮ → **Ruwe configuratie-editor**.
3. Vervang alles door de inhoud van `dashboards/appie.yaml` en sla op.

Heb je het aantal Vaak gekocht-knoppen verhoogd, kopieer dan een van de knoppen in het dashboard en verander het nummer.

## Blueprint: melding bij een koopje

Krijg een melding als je winkel een koopje heeft van iets wat je vaak koopt:

[![Importeer de blueprint in je Home Assistant.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTimoPouw%2FAppie-Dashboard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fappie%2Fkoopje_favoriet.yaml)

Standaard komt er een melding in Home Assistant zelf; kies bij het instellen een andere actie (bijvoorbeeld een melding naar je telefoon) als je dat liever hebt.

## Inloggen

AH stuurt na het inloggen door naar `appie://login-exit?code=...`, een adres dat alleen de app kan openen. Die link vang je op met de ontwikkelaarstools van je browser:

1. Open de inlogpagina uit het configuratiescherm in Chrome, maar **log nog niet in**.
2. Open de ontwikkelaarstools (Cmd+Option+I of F12), tabblad **Network**, vink **Preserve log** aan en typ `login-exit` in het filterveld.
3. Log in (inclusief de sms-code).
4. Rechtsklik op de regel `login-exit` → **Copy** → **Copy URL** en plak die in Home Assistant. De code is maar een paar minuten geldig.

Daarna ververst de integratie zelf de toegang (een token is 7 dagen geldig en wordt een dag van tevoren vernieuwd). Lukt dat niet meer, dan vraagt Home Assistant om opnieuw in te loggen.

## Ontwikkelen

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

Bij elke push en pull request draaien hassfest, de HACS-controle en de tests (GitHub Actions). Een release maak je via Actions → **Release** → **Run workflow** op `main`: die tagt de commit met `v` plus de versie uit `manifest.json` (bijvoorbeeld `v0.3.0-beta.1`). Een tag met die naam pushen werkt ook. De release-notes komen uit `CHANGELOG.md`, en een versie met `-` wordt een pre-release.

Logo en icoon: de bron is [`assets/Albert_Heijn_Logo.svg`](assets/Albert_Heijn_Logo.svg). Exporteer een SVG eerst naar een PNG van minstens 512 px, en zet die dan in de goede maten met

```bash
.venv/bin/pip install pillow
.venv/bin/python scripts/make_brand.py --icon icoon.png --logo logo.png --dark-logo logo-wit.png
```

## Dankjewel

Deze integratie staat op de schouders van **[appie-go](https://github.com/gwillem/appie-go)** van **[Willem de Groot](https://github.com/gwillem)** ([@gwillem](https://github.com/gwillem)). Hij heeft de API van de Appie-app uitgeplozen en alles netjes gedocumenteerd in [`doc/albertheijn_api.md`](https://github.com/gwillem/appie-go/blob/main/doc/albertheijn_api.md). Vrijwel alles wat deze integratie doet, komt daar vandaan:

| Onderdeel hier | Gebaseerd op appie-go |
|---|---|
| Inloggen via `appie://login-exit`, tokens verversen | `auth.go`, `login.go` |
| Headers en client-id van de app | `client.go` |
| Boodschappenlijst (v2) | `shoppinglist.go` + de API-documentatie |
| Persoonlijke bonus en bonusweken | `bonus.go` ([bijdrage van @ddeboer](https://github.com/gwillem/appie-go/pull/28)) |
| Kassabonnen (GraphQL) | `receipts.go` |
| Kassacodes omzetten naar producten (*Vaak gekocht*) | `productConvertId` ([bijdrage van @aaearon](https://github.com/gwillem/appie-go/pull/17)) |
| Kassabon als PDF | `receipts.go` |
| Lijst kosten, Vergeet niet, favoriete winkel | de API-documentatie (`FetchTotalPrice`, `dontforgetlane`, `GetFavoriteStore`) |
| Koopjes | `koopjes.go` |
| Producten zoeken en opzoeken, voedingswaarden | `products.go` en `doc/search-api.md` |
| Bonus spotlight en per categorie | `bonus.go` |
| Bonus Box | de API-documentatie (`FetchBonusBoxOffers`) |
| Favoriete lijsten | `shoppinglist.go` |

Ook dank aan [@beninhos](https://github.com/gwillem/appie-go/issues/26) voor het uitzoeken van de inlogbeveiliging van AH, en aan [KixAss/home-assistant-appie](https://github.com/KixAss/home-assistant-appie), dat liet zien hoe de v2-boodschappenlijst zich gedraagt.

Vind je dit handig? Geef [appie-go een ster](https://github.com/gwillem/appie-go). Deze repo is een eigen Python-implementatie en gebruikt dezelfde licentie als appie-go: [AGPL-3.0](LICENSE).
