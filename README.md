# Kimai custom component för Home Assistant

Byggd mot Kimai 2.x REST API (Bearer-token). Kräver HA 2026.3+ (för lokala
brand-bilder; övrigt fungerar på äldre versioner om du tar bort `brand/`).

## Installation via HACS (rekommenderat)

1. Lägg upp den här mappen som ett eget GitHub-repo, t.ex. `ha-kimai`.
   `hacs.json` ligger redan i roten och `custom_components/kimai/` under den –
   det är strukturen HACS förväntar sig.
2. Justera `documentation` och `issue_tracker` i `manifest.json` till ditt
   faktiska repo (står placeholder just nu).
3. Skapa en release/tag i repot (HACS läser versionstaggar).
4. I HA: HACS → tre prickar → **Custom repositories** → klistra in repo-URL,
   kategori **Integration** → Lägg till → installera → starta om HA.

## Manuell installation (SSH mot HAOS, port 22222)

Kopiera mappen `custom_components/kimai` till `/config/custom_components/kimai`
på din HA-instans, t.ex:

```
scp -P 22222 -r custom_components/kimai root@orvar:/mnt/data/supervisor/homeassistant/custom_components/kimai
```

(Justa sökvägen om `/config` är mountat annorlunda – kontrollera med
`ha core info` eller via Samba/`docker exec` in i homeassistant-containern.)

Starta om Home Assistant, gå sedan till
**Inställningar → Enheter & tjänster → Lägg till integration → Kimai**.

## Innan du testar i HA

Verifiera token och host manuellt först:

```
curl -sS -H "Authorization: Bearer DIN_TOKEN" https://kimai.example.se/api/version
curl -sS -H "Authorization: Bearer DIN_TOKEN" https://kimai.example.se/api/timesheets/active
curl -sS -H "Authorization: Bearer DIN_TOKEN" https://kimai.example.se/api/projects?visible=1
```

Om dessa fungerar (JSON tillbaka, inte 401/403) kommer config flow att fungera.
Token skapas under Kimai → din profil → API-åtkomst.

## Entiteter som skapas

**Binary sensor**
- `binary_sensor.kimai_aktivt` – device_class `running`, med ikonlogik
  (mdi:clock-check / mdi:clock-off). Ersätter template-varianten. Attribut:
  `project`, `activity` (råa ID:n) samt namnen

**Sensorer**
- `sensor.kimai_status` – aktivt projektnamn eller "Ledig". Attribut: `pagaende`,
  `timesheet_id`, `project`, `activity` (råa ID:n), `aktivitet` (namn),
  `begin`/`starttid`, `description`/`beskrivning`
- `sensor.kimai_pagaende_tid` – minuter i pågående tidrapport (device_class
  duration). Uppdateras var 30:e sekund med coordinatorn
- `sensor.kimai_startad` – starttidpunkt som timestamp. Använd denna för en
  sekund-för-sekund-räknare i Lovelace (relative time renderas klientsidan,
  helt utan polling)
- `sensor.kimai_senaste` – vad "Starta senaste" skulle återuppta

**Knappar**
- `button.kimai_starta` – startar valt projekt i select-listan
- `button.kimai_starta_senaste` – återupptar senast stoppade tidrapport (samma
  kund/projekt/aktivitet) via Kimais restart-endpoint. Blir `unavailable` om
  ingen tidigare rapport finns
- `button.kimai_stoppa` – stoppar aktiv tidrapport

**Select**
- `select.kimai_valj_projekt` – vad `button.kimai_starta` ska starta

## Services

- `kimai.start_by_name` (project, activity, description) – **enklaste vägen in.**
  Ta namn eller ID; namn matchas exakt men skiftlägesokänsligt mot Kimai
- `kimai.start_timesheet` (project_id, activity_id, description)
- `kimai.stop_timesheet`
- `kimai.restart_last` – samma som knappen, för dina scripts

## Styra från script / input_text / röstassistent

`kimai.start_by_name` gör att man slipper hårdkoda numeriska ID:n:

```yaml
script:
  starta_kimai:
    fields:
      uppdrag:
        selector:
          text:
    sequence:
      - action: kimai.start_by_name
        data:
          project: "{{ uppdrag }}"
          description: "{{ uppdrag }}"
```

Vill man styra via en `input_text` eller `input_select` räcker det att skicka
dess state som `project`. Anges ingen `activity` används projektets första.
Anges den kan det vara namn eller ID.

Om namnet inte finns i Kimai kastas ett tydligt fel istället för att fel projekt
startas – uppslagningen är exakt matchning, ingen fuzzy-sökning.

### Varför inte Kimais egen sökning?

Kimai har en `term`-parameter för fritextsökning på projekt och aktiviteter, men
den ger delträffar och kan returnera flera resultat. Att starta fel projekt är
värre än att få ett felmeddelande, så integrationen matchar istället exakt mot
projekt- och aktivitetslistorna som coordinatorn ändå redan har hämtat. Det
kostar heller inga extra API-anrop.

Aktivitetsnamn är inte unika i Kimai – flera projekt har ofta en aktivitet som
heter t.ex. "Möte". Uppslagningen viktar därför aktiviteter som hör till det
valda projektet högre, och faller tillbaka på globala aktiviteter.

## Röststyrning (Assist)

Integrationen registrerar tre intents. Det ger **både** den inbyggda
Assist-matchningen och LLM-agenter tillgång till samma funktioner, eftersom
HA:s LLM-API (Assist) byggs upp från registrerade intents.

| Intent | Vad den gör |
| --- | --- |
| `KimaiStartTimesheet` | Startar projekt (slots: `project`, `activity`, `description`) |
| `KimaiStopTimesheet` | Stoppar pågående tidtagning |
| `KimaiCurrentTimesheet` | Svarar på vad som pågår och hur länge |

### Med LLM-agent (Ollama, OpenAI, m.fl.)

Fungerar direkt efter installation. Välj bara **Assist** som API i agentens
inställningar. Modellen ser intent-beskrivningarna och kan anropa dem:

> "Nu ska jag jobba med Forskningsprojektet"
> → *Startade tidtagning för Forskningsprojekt.*

Projektnamnet skickas som fritext och slås upp mot Kimai i integrationen, så
inget behöver konfigureras i förväg. Föreslår modellen ett namn som inte finns
får den ett tydligt fel tillbaka och kan fråga om.

### Med inbyggda Assist (utan LLM)

Meningar kan **inte** ligga i en custom integration - HA laddar dem bara från
`config/custom_sentences/<språk>/`. Kopiera därför:

```
custom_sentences_exempel/sv/kimai.yaml  ->  config/custom_sentences/sv/kimai.yaml
```

och fyll i dina egna projektnamn under `lists: project:`. Den inbyggda
matchningen kan inte hämta listan dynamiskt från Kimai - den behöver veta
giltiga ord i förväg. Starta om HA (eller ladda om `conversation`) efteråt.

## Tips: live-räknare i Lovelace

`sensor.kimai_pagaende_tid` uppdateras var 30:e sekund. Vill du ha en räknare
som tickar varje sekund, använd `sensor.kimai_startad` istället – t.ex. med
mushroom-template-card och `relative_time()`, eller ett vanligt entity-kort
(HA renderar timestamp-sensorer som "för X minuter sedan" automatiskt).

## Kugghjulet (Options Flow)

Inställningar → Enheter & tjänster → Kimai → **Konfigurera**:

- **Lägg till koppling** – välj projekt → välj aktivitet → sätt eget namn
- **Ändra koppling** – redigera aktivitet och/eller namn på befintlig koppling
  (formuläret förifylls med nuvarande värden)
- **Ta bort koppling**
- **Importera flera** – klistra in hela mappningen som JSON
- **Ladda om projekt och aktiviteter** – hämtar listorna på nytt från Kimai
- **Klar** – sparar och laddar om integrationen automatiskt

Menyn visar hur många projekt och aktiviteter som är inlästa och när, så du
ser direkt om listorna är gamla.

### Om när projektlistan uppdateras

Projekt och aktiviteter hämtas **vid inladdning** av integrationen - alltså
vid HA-omstart, vid reload av integrationen, och när du ändrar något i
kugghjulet (vilket triggar en reload). Däremellan pollas de inte alls.

Lägger du till ett nytt projekt i Kimai dyker det därför inte upp automatiskt.
Välj **Ladda om projekt och aktiviteter** i kugghjulet, så hämtas listorna
direkt utan omstart.

Formulären i kugghjulet hämtar alltid färsk data direkt från API:et, så de
visar rätt projekt även om coordinatorns cache är gammal.

Utan kopplingar visar `select.kimai_valj_projekt` Kimais råa projektnamn och
start-knappen tar första aktiviteten för projektet. Med kopplingar visas dina
egna namn och exakt rätt projekt+aktivitet startas.

Projekt och aktiviteter hämtas live från Kimais API varje gång du öppnar
kugghjulet – inget är hårdkodat eller cachat mellan omstarter.

## Var lagras datan?

- **Host, token, verify_ssl** → `.storage/core.config_entries` (fältet `data`)
- **Kopplingarna** → samma fil, fältet `options`

Det är en vanlig JSON-fil, inte recorder-databasen. Den ingår i HA-backupen och
påverkas inte av `recorder`-purge. Token ligger i klartext där, precis som för
alla andra HA-integrationer.

## Ersätter dessa template-sensorer

Integrationen täcker det som tidigare byggdes med REST-sensorer + templates:

| Tidigare template | Ersätts av |
| --- | --- |
| `binary_sensor.kimai_aktivt` | `binary_sensor.kimai_aktivt` |
| `sensor.kimai_aktuellt_projekt` | `sensor.kimai_status` (attribut `begin`, `project`, `activity`, `description`) |
| `sensor.kimai_projekt_id` | attributet `project` på ovanstående |
| `sensor.kimai_raw_*` | behövs inte – coordinatorn hämtar allt |

Vill du behålla dina gamla entitets-ID:n kan du peka om dina templates mot de
nya attributen istället för `sensor.kimai_raw_*`, så slipper du röra
automationer och dashboards.

## Om dataformatet

Kimai returnerar `project` och `activity` antingen som nästlade objekt eller
som råa ID:n beroende på version och endpoint. Koden hanterar båda: namn slås
upp mot projekt-/aktivitetslistorna när bara ID:n kommer tillbaka.

## Påverkan på resten av Home Assistant

Integrationen är byggd för att inte kunna störa andra integrationer:

- **Ingen synkron I/O.** Alla API-anrop går via `aiohttp` i event-loopen.
  Inget blockerar MainThread, så en långsam eller nedlagd Kimai kan inte
  frysa andra integrationer.
- **Inga externa pip-paket.** `requirements: []` - inget installeras i din
  HA-instans, inga versionskonflikter med andra integrationer.
- **Låg pollingbelastning.** Cykeln är 2 parallella API-anrop var 30:e
  sekund. Projekt- och aktivitetslistorna hämtas bara vid inladdning av
  integrationen - de ändras sällan nog att återkommande anrop är onödiga.
- **Går Kimai ner** markeras entiteterna `unavailable` och coordinatorn
  backar av. Inga upprepade fel i loggen, inget som påverkar övriga entiteter.
- **Städar efter sig.** Vid unload tas services, `hass.data`-nycklar och
  entitetsreferenser bort. Upprepade omladdningar läcker inte minne.
- **13 entiteter totalt** (4 sensorer, 1 binary sensor, 3 knappar,
  1 select) - försumbart i en stor instans.

Vill du sänka belastningen ytterligare kan `DEFAULT_SCAN_INTERVAL` i
`const.py` höjas. 30 sekunder är valt för att `sensor.kimai_pagaende_tid` ska
kännas levande; behöver du inte det räcker 60-120 sekunder gott.

## Kända begränsningar / nästa steg

- `select.kimai_valj_projekt`s val är lokalt i HA och nollställs vid omstart
  (den återgår till första alternativet i listan). Kan lösas med
  `RestoreEntity` om det stör.
- Ingen felhantering för Kimai-versioner < 2.x (annan auth-metod,
  X-AUTH-USER/X-AUTH-TOKEN). Säg till om du kör en äldre version.
- Ingen `unique_id`-migrering behövs ännu eftersom detta är v0.1.

## Utveckling

Enklast: kör HA i en devcontainer/venv på din dev-maskin med denna mapp
symlinkad in i `config/custom_components/`, så slipper du starta om din
produktions-HA för varje ändring. Home Assistants officiella dev-mall:
https://github.com/home-assistant/integration_blueprint
