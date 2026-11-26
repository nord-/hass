# Värmepumpens prisplan: lärdomar

Senast uppdaterad 2026-11-26.

Det här dokumentet samlar det vi har lärt oss om huset, värmepumpen och planeraren sedan prisplanen infördes 2026-11-20. Det är skrivet för att kunna läsas utan att ha följt arbetet.

- Hur planeraren är byggd och varför varje regel finns: `docs/superpowers/specs/2026-11-20-heat-pump-price-plan-design.md`.
- Den oberoende granskningen av modellen, med alla siffror och metoder: `docs/varmepump-prisplan-granskning-2026-11-26.md`.
- Koden: `python_scripts/heating_plan.py`, `packages/heating.yaml` och testerna i `tests/`.

## 1. Målet

Rickard, 2026-11-26:

> Vårt primära mål är inte att huset ska förbruka mindre energi utan att flytta effekt från dyra timmar till billiga timmar utan att tappa i komfort (alltför mycket).

Följden är att energi som aldrig köps tillbaka inte är en vinst att räkna hem. Den är komfort som går förlorad. Planen ska bedömas på hur mycket pris den flyttar per förlorad grad.

## 2. Vad som går att styra

| Del | Vad den gör |
|---|---|
| `switch.varmepumpen_a` (Shelly 1 på pumpens externingång) | På = värme och varmvatten spärrade. Pumpen är inställd så att elpatronen spärras samtidigt. |
| `switch.varmepumpen_b` | På = elpatronen spärrad. Styrs av två äldre automationer (pris över p75 eller hög last). Planeraren rör den inte. |
| Värmepumpen | IVT AirX 407 med AirModule E9, reglercentral HMC300 på EMS-buss. |

- **Pumpen går bara att stoppa, inte gasa.** De externa ingångarna I1–I4 kan enbart spärra (kompressor, värme, varmvatten, kyla, tillskott). Menyn har ingen Smart Grid-funktion.
- **Pumpen har ingen rumsgivare.** Den styr på utegivaren och värmekurvan och ser inte inomhustemperaturen. Den bromsar därför inte när solen värmer huset.
- **Vägar till riktig gas och broms**, ingen av dem gjord:
  1. EMS-ESP, ett ESP32-kort på EMS-bussen (BBQKees). Tillverkaren anger att anläggningar med HMC300 är kompatibla, men AirX 407 med AirModule står inte uttryckligen i någon lista. Rapporter om samma plattform säger att Tx mode ska stå på EMS+.
  2. Emulera utegivaren, till exempel med Ohmigo.

## 3. Hur huset och pumpen beter sig

Siffrorna kommer från timstatistiken i Home Assistant (sedan 2025-10-30), femminutersstatistik och brytarhistorik. Där inget annat sägs kommer de från granskningen 2026-11-26.

### Kompressorn

- Kompressorn ligger ensam på fas 3 (`sensor.shelly_3em_c45bbe55c55e_power_2`). Fas 1 och 2 bär cirka 45 W styrning plus elpatronen.
- Blockerad drar pumpen cirka 60 W. I drift drar kompressorn 0,7–2,1 kW beroende på utetemperatur.
- Vid −10 till −5 °C går den på 1,79 kW i median mot 2,17 kW som mest. Den har alltså bara 0,3–0,4 kW i reserv när det är kallt.
- Den följer ungefär de senaste sex timmarnas utetemperatur, inte den aktuella.

### Efter ett block

- **Ingen rusning.** Kompressorn tar inte igen underskottet med full effekt. Den går på ungefär normal nivå.
- **Starten dröjer ofta.** För de sju släppen 21–25/11 tog det 43, 1, 28, 27, 1, 34 och 1 minut innan effekten gick över 400 W.
- **Två lägen.** Antingen startar den inom fem minuter och når 2,4–2,8 kW första timmen, vilket är effektnivån för varmvatten (stämmer i tre fall av tre, inte bevisat). Eller så startar den efter cirka 25 minuter och klättrar stegvis i ungefär två timmar.
- **Varje block kostar 0,4–0,8 timmar extra stillestånd** utöver själva blocket.

### Vart den uteblivna energin tar vägen

- **Ungefär hälften köps aldrig tillbaka** (spann 40–75 % tillbaka inom tre dygn). Per blockerad timme kommer cirka +0,24 kWh tillbaka inom 12 h, +0,47 inom 24 h och +0,75 inom 72 h, mot 1,0–1,2 kWh utebliven.
- **Resten syns som ett svalare hus:** cirka 0,15–0,2 °C lägre dygnsmedel per blockerad timme och dygn, när det pågår dag efter dag. Lika i tvättstuga, kök, vardagsrum och kontor.
- Säkerheten är måttlig för att andelen ligger klart under ett, och låg för det exakta värdet. Återbetalning efter mer än 72 h, eller att braskaminen eldas mer när huset är svalt, går inte att utesluta.

### När huset blir som kallast

- **Svackan kommer efter blocket, inte under det.** Efter de långa blocken 22–24/11 nådde tvättstugan sitt minimum cirka 03:40, köket cirka 05:40 och vardagsrummet 06:30–07:25.
- **Ett dygns block slår hårdast nästa dygn**, tre till fyra gånger mer än samma dygn.
- Ett förmiddagsblock lägger svackan på eftermiddagen och kvällen. Ett eftermiddagsblock lägger den på natten.
- Huset tål långa block. Den 19/11 vid −2,1 °C blockerades cirka 11 timmar i sträck och rummen sjönk ungefär en grad.

### Förmiddag mot eftermiddag

- **Ingen påvisad termisk fördel för förmiddagsblock.** Rummen tappar lika mycket per blockerad timme (tvättstugan −3,4 mot −3,8 °C·h inom 24 h, och intervallen överlappar).
- En blockerad morgontimme förskjuter cirka 25 % mer energi än en eftermiddagstimme, eftersom pumpen går hårdare då.
- Om två block slår ett lika långt eftermiddagsblock i rumstemperatur går inte att avgöra ur befintlig data.

### Elpatronen

- Den syns som steg på 4,5, 8,8 och 13,2 A på `sensor.shelly_3em_c45bbe55c55e_current_1`.
- Förra vintern gick den nästan bara under −10 °C, mest kl. 03–08: 78 % av timmarna vid −20 till −15 °C, 42 % vid −15 till −10 °C, 5,5 % vid −10 till −5 °C och i stort sett aldrig över −5 °C.
- Den har inte gått alls 14–25/11, inte heller efter de långa blocken.
- Rickard har aldrig sett den slå på på grund av ett block, bara när kompressorn inte räcker i kyla. Granskarens misstanke om ett samband vid −9 till −5 °C går inte att skilja från kylan själv och är struken.

### Sol, varmvatten och rum

- **Sol:** den 21 och 22/11 nådde tvättstugan 24 °C mitt på dagen medan pumpen fortfarande drog 0,8–2,1 kW.
- **Varmvatten:** cirka 0,7 kWh per dygn, 4 % av kompressorns energi. Tre vuxna, och det har aldrig tagit slut.
- **Tvättstugan** (`sensor.felix_rum_temperature`, entiteten är felnamngiven) är ett av husets varmaste rum.
- **Köket** (`sensor.xiaomi_lys3_temperatur`) är en bra värdemätare och ingår i komfortvakten.
- **Felix rum** (`sensor.xiaomi_lys2_temperatur`) ligger cirka 1,5 °C lägre än tvättstugan. Det ska inte vara referens, eftersom övriga rum då blir för varma.
- **Badrummet** (`sensor.xiaomi_lys4_temperatur`) reagerar inte alls på block.
- **Störkällor:** matlagning lyfter köket 0,5 °C eller mer, tvättstugan har tvättmaskin, brödrost och kaffebryggare, och braskaminen kan ta vardagsrummet till närmare 30 °C.

### Priserna

- Den typiska kurvan har en topp på morgonen, en på sen eftermiddag eller kväll och sedan en billig natt. Mönstret går igen även när nivån är extrem.
- Prisnivån varierar lika mycket från dag till dag som inom dygnet. Snittet för de två följande dygnen ligger på 0,48–2,16 gånger den planerade dagens snitt (10:e till 90:e percentilen).
- Eftersom återbetalningen tar ett till tre dygn förlorar planen pengar ungefär en dag av fem i granskarens modell. Det går inte att lösa med morgondagens priser.

## 4. Hur modellen har ändrats

### Värderingen av ett block

| Datum | Blocket jämförs med | Varför det ersattes |
|---|---|---|
| 2026-11-20 | Dygnets snittpris | Tog ingen hänsyn till vad det kostar efteråt. Första planen blockerade 16–17 vid 1,30 kr och tog igen värmen 17–18 vid 1,28 kr. |
| 2026-11-20 | Priset i pausen efter blocket (1–1,5 h) | Byggde på antagandet att pumpen tar igen allt med full effekt direkt. Gav för 22/11 block 01–04 och 20:45–23:45 och lät pumpen gå genom hela kvällsplatån. |
| 2026-11-21 | Snittet för de kommande 12 timmarna | Efter ett morgonblock är de kommande 12 timmarna den dyra dagen, och den billiga natten hamnar utanför. Planen för 27/11 blev 12:15–18:30 och släppte igenom dygnets dyraste timme, 08–09 (616 öre med allt). |
| 2026-11-26 | Snittet för de kommande 24 timmarna | Gäller nu. Gav 07:45–11:30 och 16:00–18:15 för 27/11. |

Kvartar efter midnatt, där priserna är okända, räknas med dygnets snitt. Granskaren provade ett annat antagande och det blev något sämre.

### Reglerna

| Datum | Ändring | Varför |
|---|---|---|
| 2026-11-20 | Max block per temperatur, budget = 2 × max block, paus max(1 h, halva blocket) | Första versionen. |
| 2026-11-21 | En gräns per dygn (ankarna), ett block får använda allt, paus som hjälpare på 2 h | De gamla reglerna tvingade in en timmes paus mitt i pristoppen, och en så kort paus ger nästan ingen värme. |
| 2026-11-26 | Minsta prisskillnad som hjälpare, 0,20 kr/kWh (var fast 0,10) | Ett block ska flytta tillräckligt mycket pris för att vara värt graderna. |
| 2026-11-26 | Minsta block 2 h (var 1 h) | 24-timmarsfönstret ger annars ensamma entimmesblock. |

## 5. Nuvarande inställning

Läget 2026-11-26. Hjälparna ändras i kortet "Värmeplan, inställningar".

| Inställning | Värde |
|---|---|
| Värdering | Blockets pris minus snittet för de kommande 24 timmarna minus minsta prisskillnad |
| Minsta prisskillnad (`input_number.heating_min_excess`) | 0,20 kr/kWh spot |
| Max blockering per dygn (`input_number.heating_block_cold`, `_chilly`, `_mild`, `_warm`) | 4 / 8 / 10 / 12 h vid −7,5 / −2,5 / +2,5 / +7,5 °C, interpolerat på snittet av prognosens sex kallaste timmar |
| Minsta paus mellan block (`input_number.heating_min_pause`) | 2 h, gäller även över midnatt |
| Minsta block | 2 h (konstant i koden) |
| Komfortvakt, tvättstugan | Kvantil 10 över ett dygn: full gräns vid 22,0 °C, minus 10 % per 0,1 °C under |
| Komfortvakt, köket | Kvantil 10 över ett dygn under 21,0 °C ger gräns 0 |

Planeraren körs när morgondagens priser finns, i praktiken cirka 13:12, och skriver planen till `input_text.heating_plan_a` eller `_b`. `binary_sensor.varmepump_blockerad_enligt_plan` följer planen för dagens datum.

## 6. Beslut och fasta ramar

- **Inga korta block, och minst 2 h paus mellan block.** Rickard, 2026-11-26: båda är säkra förbättringar och ska inte ändras tillbaka. Mätningen stöder dem.
- **Felix rum är ingen komfortreferens.** Köket är det.
- **Elpatronen är ingen fråga för planeraren.** Inga blockgränser för dess skull.
- **Ingen broms än.** Frågan tas upp till våren om det blir för varmt. En broms ska bygga på ett medelvärde över flera rum, aldrig ett enskilt rum, så att matlagning, tvättmaskin eller braskamin inte utlöser den.
- **Ingen regel som tvingar fram två block eller gynnar förmiddagar.** Planeraren delar upp när priserna säger det.
- **Den energi som inte köps tillbaka räknas inte som vinst i värderingen.** Det är ett temperaturbeslut och hör hemma i dygnsgränsen.
- **Inga notiser** i funktionen.

## 7. Misstag och vad de lärde oss

1. **Antaganden om pumpens dynamik utan mätning.** Påståendet att pumpen tar igen allt med full effekt direkt styrde värderingen i ett dygn och var fel. Kontrollera sådana påståenden mot timstatistiken innan en modell byggs på dem.
2. **Råa jämförelser före och efter.** Både "huset är en grad varmare med nya planen" och motsatsen byggde på dagar med olika utetemperatur och sol. Ingen av dem höll.
3. **Fel framgångsmått.** Kvoten mellan betalt pris och dygnets snitt blir cirka 0,90 bara av att blockerade timmar tas bort. Den säger inget om vad som köps tillbaka senare.
4. **Mätfel av block som följde på varandra.** Siffran 30–90 minuters startfördröjning kom från korta block som låg tätt, där nästa block hann börja före kompressorn.
5. **Korta block drunknar i brus.** Ett tretimmarsblock missar 2–4 kWh, och lika mycket svänger förbrukningen ändå. Den gamla automationen blockerade nästan varje dag, så det finns få rena jämförelsedagar.
6. **En inställning utan verkan.** Hjälparen för minsta prisskillnad ändrade ingenting vid veckans prisnivå, eftersom dygnsgränsen var det som begränsade. Räkna om verkliga dagar innan en ny ratt införs.
7. **Tyst omplanering.** Planeraren avbryter om ett fält redan har morgondagens datum. För att planera om måste fältet tömmas först.
8. **En död givare stoppar planen.** När köksgivarens batteri tog slut 2026-11-21 skrevs ingen plan. Batterinivån hade inte varnat, så larmet går nu även när en temperaturgivare blir otillgänglig.
9. **En oberoende granskare gav mest.** Den fick fakta, mätningar och tre påståenden att försöka motbevisa, och hittade det viktigaste utanför de påståendena.

## 8. Öppna frågor

- **Dygnsgränsen nollställs vid midnatt.** Planerna har blockerat 11,25 h inom samma 24 timmar med gränser på 6,5 och 8 h. Huset summerar över dygn, inte kalenderdagar.
- **Komfortvakten reagerar ett till två dygn för sent,** eftersom svackan kommer dygnet efter och kvantilen läses kl. 13. En enkel modell antyder att gränsen kan svänga mellan 3 och 7 h per dygn när kvantilen ligger mellan 21 och 22 °C. Det är inte observerat.
- **Hur många timmar per dygn är värda graderna?** Granskarens modell på förra vinterns priser (snitt spot 0,91 kr), där bara prisflytten räknas:

  | Tak för dygnsgränsen | Blockerat per dygn | Prisflytt, kr per dygn |
  |---|---|---|
  | 2 h | 1,9 h | 1,19 |
  | 4 h | 3,8 h | 2,07 |
  | 6 h | 5,2 h | 2,50 |
  | 8 h | 6,1 h | 2,72 |
  | Ankarna som de var | 6,3 h | 2,77 |

  Timmar utöver fyra flyttar under 0,3 kr vardera men kostar samma 0,15–0,2 °C. Kronorna är osäkra, formen på kurvan höll för fyra olika antaganden. Åtta timmar per dygn motsvarar ett hus som är cirka 1,2–1,6 °C svalare när det har ställt in sig.
- **Två block mot ett långt.** Den 27/11 är första dagen med ett förmiddagsblock i den nya planen.
- **Frysskydd för utedelen under block.** Servicemanualen (2014/06) beskriver det inte. Pumpen drar cirka 60 W under block, vilket tyder på att cirkulationen går, och ingenting gick sönder förra vintern. Frågan till IVT eller installatören är inte ställd.
- **Broms vid solöverskott**, till våren.
- **EMS-ESP** för att kunna gasa.

Experiment som skulle ge säkra svar:

| Fråga | Experiment |
|---|---|
| Hur stor andel köps tillbaka, och hur fort | Två oblockerade dagar i veckan, valda efter kalender och inte efter pris, i sex till åtta kalla veckor |
| Verkningsgrad och varför hälften inte köps tillbaka | Temperaturgivare på golvvärmens fram- och returledning |
| Två block mot ett | Varannan dag av varje form med lika många timmar, cirka 25 dagar per form |

## 9. Data och verktyg

### Entiteter

| Entitet | Innehåll |
|---|---|
| `sensor.template_heatpump_ivt_power` | Pumpens effekt, summan av tre faser |
| `sensor.shelly_3em_c45bbe55c55e_power_2` | Kompressorns fas |
| `sensor.shelly_3em_c45bbe55c55e_current_1` | Rör sig bara när elpatronen går |
| `sensor.framsidan_temperature` | Utetemperatur |
| `sensor.felix_rum_temperature` | Tvättstugan |
| `sensor.xiaomi_lys3_temperatur` | Köket |
| `sensor.template_elpris_kr` | Pris med avgifter och moms |
| `sensor.nordpool_kwh_se3_sek_3_095_0` | Spotpris, kvartspriser i `raw_today` och `raw_tomorrow` |

### Hämta data

- **Timstatistik** finns sedan 2025-10-30 via websocket-anropet `recorder/statistics_during_period` med `period: hour`. Femminutersstatistik fanns från 2026-11-10 vid granskningen.
- **Rå historik** via REST (`/api/history/period/...`) räcker ett par veckor bakåt. `switch.varmepumpen_a` ger exakta blocktider, och fanns från 2026-11-10 vid granskningen.

### Fällor i datan

- En timme med låg effekt kan vara naturlig tomgång. Den förekommer bara över cirka +4 °C ute. Säkrast är att räkna en timme som blockerad när kompressorfasens timmaximum är under 30 W.
- Sol mitt på dagen stör allt som mäts på förmiddagsblock. Solcellsproduktionen fungerar som mått på solen.
- Före 2026-11-20 blockerade den gamla automationen på pris, så blockens tidpunkt hänger ihop med priskurva och tid på dygnet.
- Utetemperaturens variation från dag till dag är större än de effekter som söks.

### Tester och driftsättning

- `tests/` kör planeraren i en kopia av Home Assistants `python_script`-sandlåda (`tests/ha_sandbox.py`). De förväntade planerna räknas fram med en separat referensimplementation, inte med planeraren själv.
- Varje gång modellen har ändrats har den dag som avslöjade felet sparats som prisfixtur i `tests/fixtures/` och låsts med ett test.
- Sandlådan har egenheter: `isinstance(x, list)` fungerar inte, `d[k] += x` är inte tillåtet, och tider jämförs säkrast via `dt_util.as_timestamp`.
- Driftsättning: slå ihop till master, pusha, `git pull --ff-only` på Pi:n, kontrollera konfigurationen, ladda om `python_script` (och `input_number` om hjälpare har ändrats). Dashboarden sparas via websocket efter att live-versionen har jämförts med filen.
