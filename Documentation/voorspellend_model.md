# Voorspellend model bodemvocht

De dagelijkse uitvoering rapporteert iedere actieve probe en voorspelt voor bruikbare, getrainde probes de relatieve permittiviteit voor de volgende zeven dagen. Het doel is om per locatie tijdig zichtbaar te maken hoe groot het risico is dat een probe binnen die periode een voorlopige kritieke vochtgrens bereikt.

De actieve bestanden zijn:

- `data_analyse/permittivity_prediction_model.py`: dagelijkse voorspelling en Excel-uitvoer;
- `data_analyse/train_permittivity_prediction_model.py`: parametertraining en evaluatie;
- `data_analyse/visualise_permittivity_training.py`: maximaal vier evaluatiegrafieken per getrainde probe;
- `data_analyse/permittivity_data_exploration.py`: historische probe- en weervisualisaties;
- `data_analyse/benchmark_archived_model.py`: referentiebenchmark van de bewaarde handmatige parameters;
- `data_analyse/archived_model_training_config.json`: zoekbereiken en trainingsinstellingen.

## Herkomst van het model

De voorspellingsvergelijking komt uit `legacy_data/model_experiments/permittivity_prediction_model_before_dynamic.py`. Deze versie presteerde in de uitgevoerde controles beter dan het later ontwikkelde gezamenlijke dieptemodel.

Het oorspronkelijke bestand gebruikte alleen `probe_number = 1` en handmatig ingevulde parameters per `device_id`. De actieve versie behoudt de vergelijking, maar gebruikt een apart model voor iedere combinatie van:

```text
device_id + probe_number + depth_cm
```

Sensoren, probes en dieptes delen geen parameters of trainingsdata. Ook probes die toevallig dezelfde diepte hebben worden zelfstandig getraind. Relatieve permittiviteit wordt uitsluitend binnen de historische reeks van dezelfde sensor en probe beoordeeld en niet tussen sensoren of dieptes vergeleken.

De later ontwikkelde dynamische diepteversie maakt geen deel meer uit van de bewaarde projectbestanden. De actieve implementatie deelt geen parameters of trainingsdata tussen dieptes.

## Referentiebenchmark van het archiefmodel

`benchmark_archived_model.py` leest uitsluitend de vier parameter-dictionaries uit `permittivity_prediction_model_before_dynamic.py`; het voert het gearchiveerde script zelf niet uit en verandert het operationele model niet. De benchmark vergelijkt de handmatige parameters met persistence op dezelfde laatste acht testweken, zowel met de volledige historische afleidingen als met een variant zonder informatie uit de testperiode.

Voer de benchmark voor een of meer probenummers uit met:

```bash
python data_analyse/benchmark_archived_model.py --probes 1 2 3 --output data_analyse/model_artifacts/archived_model_benchmark_probes_1_2_3.csv
```

De opgegeven CSV bevat de samenvatting per probe en diepte; daarnaast ontstaat automatisch een bestand met `_cases` achter dezelfde basisnaam voor de afzonderlijke testsituaties. Zonder `--output` worden `archived_model_benchmark.csv` en `archived_model_benchmark_cases.csv` overschreven. Gebruik voor nieuwe controles daarom een eigen bestandsnaam. Bestaande bestanden voor eerdere probe-selecties zijn bewaarde referentieresultaten. De benchmark traint niets en schrijft `archived_sensor_model.json` niet opnieuw.

## Sensorselectie

Alle sensor-ID's uit alle categorieen van `data_collection/sensor_data/usable_sensors.json` worden getraind. Van deze sensoren worden alle actieve probes afzonderlijk verwerkt.

Een actieve sensor die niet in het JSON-bestand staat krijgt in de operatoruitvoer per probe:

```text
status = insufficient_history
```

Daardoor verdwijnen ongeschikte sensoren niet stilzwijgend uit het rapport.

## Voorspellingsvergelijking

Voor iedere sensor-probe-dieptecombinatie worden vier parameters gezocht:

- `rain_threshold_mm`: vanaf welke dagelijkse neerslag een regengebeurtenis meetelt;
- `rain_response_strength`: hoe sterk effectieve neerslag doorwerkt;
- `max_rain_response_multiplier`: de bovengrens van de regenrespons;
- `rain_memory_decay`: hoe snel regeninvloed over vijf dagen afneemt.

Daarnaast leidt de training twee waarden rechtstreeks af uit de historische meetreeks van dezelfde probe:

- gemiddelde dagelijkse stijging na een regengebeurtenis;
- gemiddelde dagelijkse uitdrogingsslope tussen regengebeurtenissen.

Voor iedere toekomstige dag telt het model regen boven de drempel op met exponentieel afnemend gewicht. Bij voldoende effectieve regen wordt de verwachte stijging toegepast. Zonder voldoende regen wordt de historische uitdrogingsslope toegepast. De positie van de actuele permittiviteit binnen de laatste dertig dagen dempt de stijging wanneer de grond al relatief nat is en versterkt de daling wanneer de waarde relatief hoog ligt.

Temperatuur, wind en zonneschijn zitten niet in deze vergelijking. Dat is bewust: de actieve implementatie herstelt eerst het aantoonbaar beter presterende oorspronkelijke model. Temperatuur en zonneschijn worden alleen gebruikt voor de energieproxy in de visualisaties en veranderen de voorspelde permittiviteit niet. Nieuwe modelvariabelen mogen pas worden toegevoegd wanneer zij op dezelfde onafhankelijke eindtest aantoonbaar verbeteren.

## Exhaustive search

De volledige zoekmethode test ieder punt uit het raster in `archived_model_training_config.json`. De standaardinstelling bevat per probe:

| Parameter | Bereik | Stap | Waarden |
|---|---:|---:|---:|
| Regendrempel | 0,5 tot 15,0 mm | 0,5 | 30 |
| Regensterkte | 0,10 tot 1,50 | 0,05 | 29 |
| Maximale multiplier | 0,50 tot 4,00 | 0,25 | 15 |
| Regengeheugen | 0,40 tot 0,95 | 0,05 | 12 |

Dit zijn maximaal `30 x 29 x 15 x 12 = 156.600` combinaties per probe. Drempels waarvoor geen bruikbare regen- en uitdrogingsstatistieken bestaan worden overgeslagen.

De berekening blijft exhaustief, maar voert veel combinaties tegelijk uit met NumPy. Data-inleeswerk, neerslagvensters en historische statistieken worden niet voor iedere combinatie opnieuw opgebouwd. Meerdere probes kunnen parallel worden getraind.

Bij de start meldt het script direct hoeveel sensor-probecombinaties worden verwerkt. Na iedere voltooide, overgeslagen of uit cache gelezen probe verschijnt een afzonderlijke regel met sensor, probenummer, diepte, status, eventuele evaluatie-MAE en het aantal probes dat nog te gaan is. De uitvoer wordt direct geflusht, zodat voortgang ook tijdens een lange run zichtbaar blijft.

Start de volledige training vanuit de projectroot:

```bash
python data_analyse/train_permittivity_prediction_model.py --method exhaustive
```

Beperk het aantal parallelle processen wanneer het systeem weinig geheugen heeft:

```bash
python data_analyse/train_permittivity_prediction_model.py --method exhaustive --workers 2
```

## Coarse-to-fine

De snellere methode test eerst een grof raster van standaard 5.760 combinaties op iedere zevende trainingssituatie. Daarna worden fijne rasterpunten rond de vijf beste grove uitkomsten op alle dagelijkse trainingssituaties getest. Deze methode gebruikt dezelfde uiteindelijke rasterresolutie in de geselecteerde gebieden, maar garandeert niet dat het globale optimum buiten die gebieden wordt gevonden.

```bash
python data_analyse/train_permittivity_prediction_model.py --method coarse-to-fine
```

Gebruik coarse-to-fine alleen als de evaluatie praktisch gelijk blijft aan exhaustive search. Exhaustive search blijft de referentiemethode.

## Hervatten en kleine runs

Een voltooid probe-resultaat wordt in `data_analyse/model_artifacts/training_cache` opgeslagen. Bij een volgende identieke opdracht wordt dit resultaat standaard hergebruikt. De cache wordt automatisch ongeldig wanneer de methode, configuratie, modelcode, sensormeetwaarden of historische neerslag verandert. Iedere probe bewaart zijn werkelijke eigen trainingstijd; het hervatten van een run maakt een ouder cacheresultaat dus niet kunstmatig nieuw.

Forceer een nieuwe berekening met:

```bash
python data_analyse/train_permittivity_prediction_model.py --method exhaustive --no-resume
```

Een beperkt aantal sensoren of probes kan afzonderlijk worden uitgevoerd:

```bash
python data_analyse/train_permittivity_prediction_model.py --method coarse-to-fine --device-ids 1384 1390 --probe-numbers 2 3
```

Een gefilterde run schrijft een gefilterd modelbestand. Gebruik daarom `--model-path` en `--artifact-dir` wanneer zo'n run alleen een experiment is en het volledige operationele model niet mag worden vervangen.

## Training en onafhankelijke evaluatie

De training maakt per probe dagelijkse historische voorspelsituaties:

1. Begin nadat minimaal negentig kalenderdagen meetgeschiedenis beschikbaar zijn.
2. Neem de actuele permittiviteit en de voorafgaande dertig dagen als begintoestand.
3. Gebruik de werkelijk gemeten neerslag voor de volgende zeven dagen.
4. Vereis voor alle zeven dagen een werkelijke sensormeting.
5. Schuif de oorsprongsdatum een dag vooruit.

Alle situaties waarvan de oorsprongsdatum in de geconfigureerde laatste evaluatieweken ligt worden apart gehouden. Hun sensormetingen worden niet gebruikt om parameters, regenstijging, uitdrogingsslope of de kritieke permittiviteitsgrens te trainen. Eerst wordt op alle eerdere complete dagelijkse situaties de beste parametercombinatie gevonden. Daarna wordt die combinatie ongewijzigd op de apart gehouden weken getest.

Historische weersverwachtingsfouten worden bewust niet nagebootst. De evaluatie meet de sensormodelkwaliteit onder de werkelijk opgetreden neerslag.

Het model wordt per probe vergeleken met persistence. Persistence voorspelt voor alle zeven dagen exact de laatst gemeten relatieve permittiviteit. Model-MAE en persistence-MAE staan daarom beide in de oorspronkelijke permittiviteitseenheid van die probe. Een model is alleen aantoonbaar nuttiger wanneer zijn evaluatie-MAE lager is dan deze eenvoudige baseline.

## Trainingsuitvoer

Iedere training schrijft:

- `data_analyse/model_artifacts/archived_sensor_model.json` voor de dagelijkse uitvoering;
- `data_analyse/model_artifacts/training_evaluation_<methode>_<tijdstip>.xlsx` voor controle.

Voer eerst een training uit voordat de dagelijkse uitvoering voor het eerst wordt gestart.

De Excel-evaluatie bevat vier werkbladen:

- `Evaluation`: status, hoeveelheid trainingsdata, aantal geteste combinaties, model-MAE en persistence-MAE per sensor-probe-diepte;
- `Parameters`: de vier gekozen parameters, afgeleide stijging/slope en de probe-eigen kritieke relatieve permittiviteit;
- `Evaluation cases`: fout per apart gehouden week;
- `Run information`: methode, tijdstip, modelpad en trainingsinstellingen.

Controleer na een training minimaal `status`, `model_mae`, `persistence_mae`, `beats_persistence`, `evaluation_cases` en `combinations_tested`. Het script maakt een model ook wanneer een probe persistence niet verslaat, zodat een slechte uitkomst zichtbaar blijft en niet wordt weggefilterd. De operator mag zo'n resultaat niet automatisch als betrouwbaar watergeefadvies behandelen.

## Data-exploratie

Historische sensordata kan los van training en voorspelling worden bekeken:

```bash
python data_analyse/permittivity_data_exploration.py --device-id 1384 --probe-number all
```

`--probe-number` accepteert een positief probenummer of `all`. Bij `all` worden alle geregistreerde probes van de sensor van ondiep naar diep verwerkt, ook wanneer de sensor niet in `usable_sensors.json` staat. De gecombineerde weergave is standaard. Met `--weather-view rain`, `--weather-view energy` of `--weather-view combined` wordt respectievelijk een neerslagpaneel, een energieproxypaneel of een gekoppelde figuur met beide panelen gemaakt.

De PNG's staan in `data_analyse/data_exploration/sensor_<device_id>` en heten `probe_<nummer>_<diepte>cm_<weergave>.png`. Alleen het opnieuw gegenereerde bestand wordt overschreven; andere en oudere exploratiebestanden blijven staan. Na iedere uitvoering opent een unieke tijdelijke browsergalerij met de grafieken van die run, zodat een eerder geopende galerij niet wordt hergebruikt. `--no-open` onderdrukt dit. De exploratie, training en operationele voorspelling gebruiken dezelfde paneelopmaak en weereenheden.

## Trainingvisualisaties

Maak na een training de vier evaluatiegrafieken per getrainde probe met:

```bash
python data_analyse/visualise_permittivity_training.py
```

Het script selecteert alle actieve probes waarvan `device_id` in `usable_sensors.json` staat. De uitvoer staat in `data_analyse/training_visualisation/sensor_<device_id>/probe_<nummer>_<diepte>cm`. De vier evaluatieweken worden verdeeld in vier blokken van zeven dagen. Uit ieder blok wordt de eerste complete voorspelsituatie gebruikt. Iedere beschikbare PNG toont de voorafgaande dertig dagen en de zeven voorspelde dagen in twee panelen. Beide panelen bevatten de gemeten en voorspelde relatieve permittiviteit; het eerste gebruikt neerslagbalken en het tweede energieproxybalken. Voor de evaluatie wordt uitsluitend werkelijk opgetreden weer gebruikt.

Een probe zonder getraind model, sensordata of complete evaluatieweek krijgt geen grafiek en wordt met reden als overgeslagen gemeld. Andere bruikbare probes worden wel verwerkt. Bij een normale complete holdout ontstaan vier grafieken per probe; bij ontbrekende weken worden alleen de beschikbare weken geschreven. Na een geslaagde run wordt `training_visualisation` volledig vervangen, zodat geen oude probe- of weekgrafieken achterblijven. Een onverwachte lees- of renderfout behoudt de vorige volledige map.

Het script meldt de start voordat data wordt ingelezen, daarna de selectie en beschikbare weken per probe, vervolgens iedere geschreven grafiek en ten slotte het totale aantal probes en grafieken. De parametertraining en dagelijkse voorspelling gebruiken hetzelfde patroon van start-, voortgangs-, voltooiings- en foutmeldingen.

## Dagelijkse uitvoering

Na een voltooide training:

```bash
python data_analyse/permittivity_prediction_model.py run
```

Een andere peildatum kan expliciet worden gekozen:

```bash
python data_analyse/permittivity_prediction_model.py run --as-of 2026-08-17
```

De uitvoer staat in:

```text
data_analyse/prediction_results/prediction_YYYY-MM-DD.xlsx
```

Het werkblad `Predictions` bevat precies een regel per actieve sensor-probe-dieptecombinatie. Belangrijke velden zijn:

- `risk_within_7_days_pct`;
- `expected_crossing_date`;
- `retrained_at` en `days_since_retraining`;
- `training_start` en `training_end`;
- `training_daily_observations` en `training_raw_readings`;
- `parameter_training_cases` en `evaluation_cases`;
- `evaluation_model_mae`, `evaluation_persistence_mae` en `evaluation_beats_persistence`.

De regels worden hoofdletterongevoelig alfabetisch gesorteerd op `location_name` en daarna oplopend op `depth_cm`. `device_id` en `probe_number` maken de volgorde bij gelijke locaties en dieptes stabiel. De zeven losse dagvoorspellingen staan niet in Excel; zij blijven intern beschikbaar voor de risicoberekening en worden zichtbaar gemaakt in de grafiek.

Voor iedere regel met status `predicted` staat de operationele grafiek in `data_analyse/prediction_visualisation/sensor_<device_id>/probe_<nummer>_<diepte>cm/prediction.png`. Deze toont de voorafgaande dertig dagen en de zeven voorspelde dagen in dezelfde twee panelen als de trainingvisualisaties. De gemeten permittiviteit is een doorgetrokken lijn, de puntvoorspelling een gestreepte lijn en de verticale markering geeft het begin van de voorspelling aan. Statusregels zonder voorspelling krijgen geen grafiek. De vorige visualisatiemap wordt pas vervangen nadat alle nieuwe grafieken zijn gemaakt.

De energieproxy is uitsluitend een visuele weerindicator en wordt berekend als `zonneschijn_minuten * ((gemiddelde_temperatuur_C + maximumtemperatuur_C) / 2)`. Historische KNMI-zonneschijn wordt van tienden uren naar minuten omgerekend en historische temperaturen van tienden graden naar graden Celsius. De waarde `-1` voor minder dan 0,05 uur zon wordt nul. De forecast bevat zonneschijn al in minuten en temperaturen al in graden Celsius.

Het aantal dagen sinds hertraining wordt berekend als de uitvoerdatum minus `trained_at` in het modelbestand. De hoeveelheid trainingsdata is dus niet een algemene dieptetelling, maar hoort altijd bij precies de sensor, probe en diepte op dezelfde regel.

## Risicopercentage

De puntvoorspelling gebruikt de voorspelde hoeveelheid regen. Voor het risicopercentage worden standaard duizend paden gemaakt. Per pad bepaalt de neerslagkans of de voorspelde regen daadwerkelijk valt. Wanneer evaluatieresiduen beschikbaar zijn, wordt bovendien een volledig historisch zeven-daags foutpad van dezelfde probe toegevoegd.

Het risicopercentage is het aandeel paden waarin minimaal een dag de `critical_relative_permittivity` van diezelfde probe bereikt of onderschrijdt. De training stelt deze ruwe grens standaard gelijk aan het twintigste percentiel van de trainingshistorie van die sensor en probe. Dit is een voorlopige historische grens en nog niet biologisch gevalideerd. Het percentage is daarom een modelrisico, geen bewezen kans op plantsterfte en geen automatisch watergeefbesluit.

## Belangrijkste beperkingen

- Het twintigste percentiel als kritieke relatieve-permittiviteitsgrens moet met plantenkennis en watergeefresultaten worden gevalideerd.
- De oorspronkelijke vergelijking is heuristisch; exhaustive search optimaliseert haar parameters, maar verandert de gekozen wiskundige vorm niet.
- Een kleine evaluatieset kan een instabiele MAE en risicoschatting geven.
- Weersverwachtingsfouten zijn geen onderdeel van de historische evaluatie.
- Watergeefacties zijn nog niet als verklarende invoer in het model opgenomen.
- De evaluatiewerkmap moet na iedere wekelijkse training worden beoordeeld voordat het nieuwe model operationeel wordt gebruikt.
