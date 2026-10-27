# Changelog

## 0.3.0

Fork van [eejeha/Appie-Dashboard](https://github.com/eejeha/Appie-Dashboard). Alle bestaande entiteiten en attributen blijven gelijk; er komen alleen dingen bij.

### Nieuw

- `sensor.albert_heijn_lijst_kosten`: wat de producten op je lijst kosten na bonuskorting (GraphQL `FetchTotalPrice`).
- `sensor.albert_heijn_vergeet_niet`: de "vergeet niet"-suggesties van de app.
- `binary_sensor.albert_heijn_winkel_open` en `sensor.albert_heijn_winkel`: je vaste winkel met openingstijden.
- `sensor.albert_heijn_koopjes` en het event `appie_koopje_favoriet`.
- `select.albert_heijn_kassabon` en `sensor.albert_heijn_gekozen_kassabon`: elke recente kassabon bekijken, plus een PDF-link per bon. De service `appie.get_receipt`.
- `sensor.albert_heijn_vaak_gekocht` met de hele ranglijst.
- Services `appie.search` en `appie.add_product` (handig met Assist).
- Opties: aantal Vaak gekocht-knoppen (10 tot 50) en de periode waarover geteld wordt (30 tot 365 dagen). Werkt zonder herstart.
- `recent` op de laatste kassabon heeft per bon ook `id` en `pdf_url`.
- Koopjes en de winkel komen in diagnostics, met het adres weggelaten.

### Verbeterd

- De bonus werd na de start niet meer ververst op het 6-uursinterval, omdat elke lijstpoll (elke minuut) de timer opnieuw startte. Nu ververst hij weer op tijd, en `on_list` volgt nog steeds direct de lijst.
- Debug-logging toont nu de API-antwoorden, met tokens, inlogcodes en persoonlijke gegevens weggelaten.

### Let op

- Vereist Home Assistant 2025.8 of nieuwer (voor het herladen na het wijzigen van de opties).
