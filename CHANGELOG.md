# Changelog

## 0.3.1

### Nieuw

- `sensor.albert_heijn_uitgaven_deze_maand` heeft een attribuut `per_maand`: wat je de afgelopen 12 maanden per maand bij AH uitgaf (`maand`, `naam`, `totaal`, `bonnen`). Eerdere maanden worden één keer per dag opgehaald, deze maand elk uur.
- Dashboard: tabel met uitgaven per maand op het tabblad Kassabonnen.

## 0.3.0

Eerste gewone release van deze fork: alles uit 0.3.0-beta.1 (zie hieronder), plus:

### Opgelost

- **Winkel en Winkel open waren niet beschikbaar**: AH stuurt de openingstijden per week gegroepeerd, niet als één lijst. Nu worden ze goed gelezen.
- **Favoriete lijsten was niet beschikbaar**: het REST-endpoint `lists/v3` geeft bij AH een 404. Nu wordt de GraphQL-query `FetchFavoriteLists` gebruikt.
- Het icoon van Vaak gekocht bestond niet.

### Nieuw

- Dashboard: een eerste tabblad **Overzicht** met wat er in je Bonus Box zit en je hele Vaak gekocht-ranglijst.

## 0.3.0-beta.1

Fork van [eejeha/Appie-Dashboard](https://github.com/eejeha/Appie-Dashboard). Alle bestaande entiteiten en attributen blijven gelijk; er komen alleen dingen bij.

### Nieuw

- `sensor.albert_heijn_lijst_kosten`: wat de producten op je lijst kosten na bonuskorting (GraphQL `FetchTotalPrice`).
- `sensor.albert_heijn_vergeet_niet`: de "vergeet niet"-suggesties van de app.
- `binary_sensor.albert_heijn_winkel_open` en `sensor.albert_heijn_winkel`: je vaste winkel met openingstijden.
- `sensor.albert_heijn_koopjes` en het event `appie_koopje_favoriet`.
- `select.albert_heijn_kassabon` en `sensor.albert_heijn_gekozen_kassabon`: elke recente kassabon bekijken, plus een PDF-link per bon. De service `appie.get_receipt`.
- `sensor.albert_heijn_vaak_gekocht` met de hele ranglijst.
- `sensor.albert_heijn_bonus_spotlight`, `sensor.albert_heijn_bonus_box` en de service `appie.bonus` (bonus per categorie).
- `sensor.albert_heijn_favoriete_lijsten` en de services `appie.get_favorite_list`, `appie.add_to_favorite_list` en `appie.favorite_list_to_list`.
- Services `appie.get_product` (met voedingswaarden), `appie.get_products` en `appie.get_subcategories`.
- Services `appie.search` en `appie.add_product` (handig met Assist).
- Opties: aantal Vaak gekocht-knoppen (10 tot 50) en de periode waarover geteld wordt (30 tot 365 dagen). Werkt zonder herstart.
- `recent` op de laatste kassabon heeft per bon ook `id` en `pdf_url`.
- Koopjes en de winkel komen in diagnostics, met het adres weggelaten.
- Kant-en-klaar dashboard (`dashboards/appie.yaml`) met alleen standaardkaarten, en een blueprint voor een melding bij een koopje.
- Het AH-logo in de integratielijst en bij de apparaten (Home Assistant 2026.3 of nieuwer).
- Iconen voor alle acties (services).
- GitHub Actions: hassfest, HACS-controle en tests bij elke push, en automatische releases vanaf een tag.

### Verbeterd

- De bonus werd na de start niet meer ververst op het 6-uursinterval, omdat elke lijstpoll (elke minuut) de timer opnieuw startte. Nu ververst hij weer op tijd, en `on_list` volgt nog steeds direct de lijst.
- Debug-logging toont nu de API-antwoorden, met tokens, inlogcodes en persoonlijke gegevens weggelaten.

### Let op

- Vereist Home Assistant 2025.8 of nieuwer (voor het herladen na het wijzigen van de opties).
