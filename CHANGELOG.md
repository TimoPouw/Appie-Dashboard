# Changelog

## 0.5.1

### Opgelost

- **Premium stond op "niet actief" terwijl je Premium hebt.** AH vult de abonnementsgegevens (`subscriptionCurrent`) bij een Premium-lid niet. Of je Premium hebt, komt nu uit `subscriptionPremiumSavingsV2`, met een startdatum en wat je bespaarde.

### Nieuw

- `sensor.albert_heijn_premium_bespaard`: wat Premium je heeft bespaard sinds je het hebt (€), met de Bonus Box, bio, extra koopzegels en Air Miles als attributen.
- `sensor.albert_heijn_premium` heeft er attributen bij: `lid_sinds`, `totaal_bespaard`, `extra_koopzegels`, `extra_air_miles` en meer.

## 0.5.0

### Nieuw

- **Sparen**: `sensor.albert_heijn_koopzegels` (zegels, boekjes, rente) en `sensor.albert_heijn_koopzegels_waarde` (wat ze waard zijn bij inleveren).
- `sensor.albert_heijn_air_miles`: je Air Miles-saldo.
- `sensor.albert_heijn_spaaracties`: lopende spaaracties met je punten per actie.
- `sensor.albert_heijn_uitdagingen`: uitdagingen ("3 weken €50 besteden") met de voortgang per stap.
- `sensor.albert_heijn_premium` en `sensor.albert_heijn_premium_besparing`: of je Premium hebt en wat het je (zou) besparen per jaar, volgens AH.
- `sensor.albert_heijn_cadeaukaarten` en `sensor.albert_heijn_openstaand_tegoed`: saldo van je cadeaukaarten (alleen de laatste 4 cijfers van een kaartnummer) en geld dat AH je nog terug moet geven.
- `sensor.albert_heijn_gemiste_bonus`: producten die je vaak koopt, die nu in de bonus zijn en nog niet op je lijst staan.
- Dashboard: tabblad **Sparen**.

Alles is alleen-lezen. De aanroepen staan niet in appie-go zelf; wat AH nodig heeft is live gecontroleerd (zie README, Sparen).

## 0.4.0

### Nieuw

- Service `appie.activate_bonus`: een aanbieding uit je Bonus Box activeren, net als in de app (proefversie: AH documenteert deze aanroep niet, zie README).
- Bonus Box-aanbiedingen hebben ook `hq_id`.

### Verbeterd

- Lijst kosten: de eerste wijziging aan je lijst wordt direct doorgerekend, niet pas na een minuut. Een snelle reeks wijzigingen daarna kost nog steeds maar één extra vraag aan AH.

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
