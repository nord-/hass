# Fronius exportreglering vid negativt försäljningspris

Detta dokument beskriver hur Home Assistant reglerar solcellsanläggningens
exporteffekt när NordPool-priset blir negativt, så att vi slipper betala för
att exportera solel till nätet.

## Sammanfattning

När försäljningspriset för solel går under 0 kr/kWh triggas en automation
som via Modbus skickar SunSpec-kommandon till Fronius-växelriktaren och
sänker dess effektgräns iterativt. Målet är att producera **exakt så mycket
huset självt konsumerar** — alltså netto = 0 mot elnätet. När priset blir
positivt igen släpps gränsen och full produktion återställs.

## Komponenter

### Modbus-registren (Fronius SunSpec inverter control)

Definierade i `modbus.yaml` (hub-namn `froniussymo`, slave/unit `1`).

| Adress | SunSpec-namn        | Funktion                                                                                              |
|--------|---------------------|-------------------------------------------------------------------------------------------------------|
| 40242  | `WMaxLimPct`        | Effektgräns i hundradels procent. Värde `6000` = 60.00 %. Skrivs som `procent * 100`.                 |
| 40244  | `WMaxLimPct_RvrtTms`| Reverteringstid i sekunder. Om inget nytt värde skrivs inom denna tid återgår omvandlaren till 100 %. |
| 40246  | `WMaxLim_Ena`       | Aktiveringsflagga. `1` = effektgränsen är aktiv, `0` = full produktion (oreglerat läge).              |

Reverteringstiden är vårt **säkerhetsnät**: om automationen kraschar mitt
i en loop återgår omvandlaren automatiskt till 100 % efter 60 s. Den ska
alltså aldrig fastna i ett begränsat tillstånd även om HA går ned.

### Sensorer och entiteter

| Entity                                  | Definition                          | Roll                                                                  |
|-----------------------------------------|-------------------------------------|-----------------------------------------------------------------------|
| `sensor.template_elpris_solar_kr`       | `templates/prices.yaml`             | Försäljningspris för solel (NordPool spot minus avdrag). Trigger.     |
| `sensor.template_grid_power_kw`         | `templates/sensors.yaml:13`         | Netto på elmätaren. Positiv = import, negativ = export.               |
| `sensor.template_house_net_power_kw`    | `templates/sensors.yaml:20`         | Inverterad version. **Positiv = export**, negativ = import.           |
| `input_number.fronius_power_limit_pct`  | HA-helper (persistent)              | Sparat tillstånd: vilken gräns vi senast satte. 0–100.                |
| `sensor.fronius_effektmal`              | `templates/sun.yaml:50`             | Beräknat **mål** för gränsen i procent. Reglerlogiken bor här.        |

> **Entity-ID:t på målet:** Sensorn deklareras med `unique_id: fronius_target_pct`
> och `name: "Fronius effektmål [%]"`. I äldre HA-versioner blev entity-id:t
> `sensor.template_fronius_target_pct` (från unique_id). I HA 2026+ namnges
> template-entiteter från det slugifierade `name`-fältet → `sensor.fronius_effektmal`.
> Sista commiten (`57e2154`) handlar om just denna ändring.

## Reglerlogiken (`templates/sun.yaml:50`)

`sensor.fronius_effektmal` beräknar nästa målgräns utifrån tre inputs:
försäljningspriset, nettoeffekten på elmätaren, och den aktuellt satta
gränsen. Logiken är en enkel proportionell reglering mot netto = 0.

```jinja
sell_price = states('sensor.template_elpris_solar_kr') | float(0)
net_kw     = states('sensor.template_house_net_power_kw') | float(0)
current    = states('input_number.fronius_power_limit_pct') | float(100)
pv_max_kw  = 8.2     # Max kapacitet på anläggningen
deadband   = 0.1     # ±0.1 kW kring noll → ingen ändring

if sell_price >= 0:
    target = 100                                             # ingen reglering behövs
elif net_kw > +deadband:        # vi exporterar → sänk
    target = clamp(current - (net_kw / pv_max_kw) * 100, 0, 100)
elif net_kw < -deadband:        # vi importerar → höj (men aldrig över 100)
    target = clamp(current + (-net_kw / pv_max_kw) * 100, 0, 100)
else:                           # innanför deadband → ligg still
    target = current
```

Tanken är att differensen mellan vad huset drar och vad omvandlaren
producerar konverteras till en procentuell förändring av effektgränsen,
skalad mot anläggningens maxeffekt. Konvergensen styrs av loopens
iterationstakt (10 s) i kombination med rate-limit i automationen.

## Själva automationen (`automations.yaml`, id `1767969815543`)

Aliaset är `Fronius exportreglering – negativt försäljningspris`. Mode är
`restart` så att en redan körande instans kasseras om triggern faller på
nytt (t.ex. pris oscillerar runt noll).

### Trigger

```yaml
trigger: numeric_state
entity_id: sensor.template_elpris_solar_kr
below: 0
```

Fires varje gång priset går från ≥ 0 till < 0.

### Steg 1 — Sätt reverteringstiden

```yaml
modbus.write_register
  hub: froniussymo, unit: 1, address: 40244, value: 60
```

Säkerhetsnätet aktiveras: om vi slutar skriva till `WMaxLimPct` i 60 s
återgår omvandlaren till 100 %.

### Steg 2 — Reglerloop medan priset är negativt

```yaml
repeat:
  while:
    - condition: numeric_state
      entity_id: sensor.template_elpris_solar_kr
      below: 0
  sequence:
    - variables:
        target:  '{{ states("sensor.fronius_effektmal") | int(0) }}'
        current: '{{ states("input_number.fronius_power_limit_pct") | int(0) }}'
        delta:   '{{ target - current }}'
        limited: |
          {% if delta > 10 %}
            {{ current + 10 }}
          {% elif delta < -10 %}
            {{ current - 10 }}
          {% else %}
            {{ target }}
          {% endif %}
    - modbus.write_register     # WMaxLimPct = limited * 100
        address: 40242, value: '{{ limited * 100 }}'
    - modbus.write_register     # WMaxLim_Ena = 1
        address: 40246, value: 1
    - input_number.set_value    # Spara nytt aktuellt värde
        entity_id: input_number.fronius_power_limit_pct
        value: '{{ limited }}'
    - delay: 10s
```

**Rate-limit:** Ändringen per iteration är begränsad till ±10 procentenheter.
Det tar alltså i värsta fall ~100 s att gå från 100 % till 0 %, eller
tvärtom. Detta dämpar oscillationer mot regulatorns mätfönster.

**Iterationstakt:** 10 sekunder. Värdet är en kompromiss mellan responstid
och att inte överbelasta Modbus-bussen / undvika "chatter".

### Steg 3 — Avslut när priset blir positivt igen

```yaml
modbus.write_register     # WMaxLim_Ena = 0  (släpp gränsen)
  address: 40246, value: 0

modbus.write_register     # WMaxLimPct = 10000 (= 100 %)
  address: 40242, value: 10000

input_number.set_value    # Återställ tillståndet i HA
  entity_id: input_number.fronius_power_limit_pct
  value: 100
```

Omvandlaren går tillbaka till oreglerad full produktion. Helpern
nollställs så att nästa reglering börjar från ett känt utgångsläge.

## Säkra fallbacks (`| int(0)` på både `target` och `current`)

Båda Jinja-uttrycken i loopen har `| int(0)` som fallback. Anledningarna:

- **Utan default kastas hård ValueError.** `| int` på `unknown` /
  `unavailable` ger inte 0 — det ger ett undantag, automationen avbryts
  helt, ingen reglering sker, och vi exporterar fortfarande mot negativt
  pris i värsta fall.
- **`0` är säkrast som default för båda inputs.** Hela automationen är
  ett *skydd mot förlust*. Semantiken "när jag inte vet, stäng av" är
  konsistent med syftet. Om regulatorsensorn är trasig får vi sämre
  självkonsumtion under några minuter, men vi betalar aldrig för export.
- **Återhämtning är gratis.** Loopen pollar var 10:e sekund och rampar
  10 procentenheter åt rätt håll så snart sensorn svarar igen.

### Varför inte `| int(100)` eller `| int(current)`?

- `int(100)` rampar **upp** vid sensorfel → exporterar maximalt vid
  negativt pris. Detta är dyrast möjligt utfall.
- `int(current)` håller bara positionen. Om regulator-sensorn är trasig
  länge fastnar vi på vad-än-vi-var-vid-trigger (typiskt 100 % från
  återställningen). I praktiken samma negativa utfall som `int(100)`.

## Vanliga fel och felsökning

### "Template error: int got invalid input 'unknown'"

Tidigare symptom innan `| int(0)`-fallbackerna lades till. Indikerar att
någon av sensorerna `sensor.fronius_effektmal` eller
`input_number.fronius_power_limit_pct` rapporterade `unknown` /
`unavailable` vid loopens iteration. Numera silentes med `0` som värde.

### "Entity not found" på `sensor.template_fronius_target_pct`

HA döpte tidigare template-entiteter efter `unique_id`. Modernare
versioner använder slugifierat `name`. Sensorn ovan heter numera
`sensor.fronius_effektmal`. Eventuella kvarvarande referenser i lovelace,
automations eller scripts måste uppdateras.

### Omvandlaren går till 0 % och stannar där

Möjliga orsaker:

1. **`sensor.fronius_effektmal` rapporterar 0.** Kontrollera i template-
   sensorn att `sell_price` faktiskt är ≥ 0 — annars går målet i `0` när
   `net_kw` är stort.
2. **Reverteringstiden 40244 har av någon anledning satts till 0.** Med
   värdet 0 har Fronius ingen revert — gränsen blir "sticky". Skriv om
   `value: 60`.
3. **`WMaxLim_Ena` (40246) är fortfarande `1`** efter att priset blivit
   positivt. Då gäller den senast skrivna gränsen. Avbrott i avslutssteget?
   Trigga automationen igen, eller skriv manuellt `0` på adress 40246.

### Loopen håller på "för länge" trots stabilt pris

Loopens villkor är `numeric_state below: 0` på prissensor. Om sensorn
oscillerar mellan -0.001 och +0.001 (numeriskt brus) kommer triggers att
falla repetitivt — och `mode: restart` startar om hela automationen.
Lös genom att antingen filtrera prissensorn, eller introducera hysteres
i triggervillkoret.

## Lovelace

Statistikvyn på `/lovelace/8` visar:

- `sensor.fronius_inverter_total_power` — faktisk effekt
- `input_number.fronius_power_limit_pct` — aktuell gräns
- `sensor.template_elpris_solar_kr` — försäljningspris (negativa
  perioder syns som dippar under noll)

Detta är primärverktyget för att i efterhand verifiera att en regler-
session faktiskt höll netto nära noll.

## Relaterade filer

- `automations.yaml` — själva automationen (id `1767969815543`)
- `templates/sun.yaml` — `sensor.fronius_effektmal` (target-beräkning)
- `templates/sensors.yaml` — `house_net_power_kw` och `grid_power_kw`
- `templates/prices.yaml` — `template_elpris_solar_kr`
- `modbus.yaml` — definitionen av Modbus-hubben `froniussymo`
