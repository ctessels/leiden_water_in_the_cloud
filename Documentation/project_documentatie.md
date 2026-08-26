# Projectdocumentatie Water in the Cloud Leiden

Dit project verwerkt bodemvochtdata van sensoren in Leiden. De actieve workflow staat nu direct in de projectroot. De oude tussenlaag `src/multi_probe_sensors` is verwijderd, omdat single-probe- en multi-probe-data inmiddels in dezelfde database en workflow worden verwerkt.

De lokale SQLite-database is de centrale bron voor sensordata, batterijniveaus, sensorinformatie en weersverwachtingen.

## Mappenstructuur

```text
leiden_water_in_the_cloud/
├── Documentation/
│   ├── project_documentatie.md
│   └── voorspellend_model.md
├── legacy_data/
│   └── model_experiments/
│       ├── permittivity_prediction_model_before_dynamic.py
│       ├── Model_fit.py
│       ├── Model_voorspelling.py
│       ├── voorspelling_2.py
│       └── README.md
├── data_analyse/
│   ├── permittivity_prediction_model.py
│   ├── train_permittivity_prediction_model.py
│   ├── visualise_permittivity_training.py
│   ├── permittivity_data_exploration.py
│   ├── benchmark_archived_model.py
│   ├── archived_model_training_config.json
│   ├── model_artifacts/
│   ├── data_exploration/
│   ├── prediction_results/
│   ├── prediction_visualisation/
│   ├── training_visualisation/
│   ├── helpers.py
│   └── Onderzoeksresultaten.md
├── data_collection/
│   ├── sensor_data/
│   │   ├── database.db
│   │   ├── valkenburg_precipitation.csv
│   │   ├── voorschoten_weerdata.csv
│   │   ├── usable_sensors.json
│   │   └── quality_control_plots/
│   ├── database_exports/
│   │   ├── DimSensor.xlsx
│   │   ├── DimSensor_met_notes.xlsx
│   │   ├── DimBattery.xlsx
│   │   └── FactSensorData.xlsx
│   ├── sensor_data_import.py
│   ├── weather_data_import.py
│   ├── data_ingestion_QC.py
│   └── ImportExport.py
├── database_scripts/
│   ├── database_definition.py
│   └── query_helper.py
└── Watergeven.py
```

## Naamgeving

De oude naam `multi_probe_data` is vervangen door `sensor_data`, omdat de workflow tegenwoordig zowel single-probe- als multi-probe-sensoren verwerkt. In `FactSensorData` worden beide typen opgeslagen met `device_id`, `probe_number` en `timestamp`.

De oude map `Data-analyse` is vervangen door `data_analyse`. Het belangrijkste script heet nu `permittivity_prediction_model.py`, omdat het niet alleen algemene analyse doet maar het huidige voorspellende model bevat.

Database-exportbestanden staan niet meer tussen de databasescripts of live data. `database_scripts` bevat alleen schema- en queryhulpmiddelen. `data_collection/sensor_data` bevat runtime data. `data_collection/database_exports` bevat Excel- en CSV-exportbestanden voor handmatige controle, overdracht of herstel.

## Databronnen

- Quantified API: sensormetingen, elektrische geleidbaarheid, temperatuur, relatieve permittiviteit en batterijniveaus.
- KNMI Valkenburg: historische neerslagdata.
- KNMI Voorschoten: historische weerdata zoals temperatuur, wind, neerslag, zonneschijn en verdamping.
- Meteoserver: tiendaagse weersverwachting voor Leiden.

De credentials staan op dit moment in `passwordnemail.py` in de projectroot. Dat bestand wordt door git genegeerd. De actieve imports verwachten daar `secrets` en `meteoserver_key`. Een latere verbetering is om deze waarden naar environment variables te verplaatsen.

## Database

De database staat in `data_collection/sensor_data/database.db`.

Belangrijkste tabellen:

- `DimSensor`: sensorstamgegevens, locaties, meetpunten, dieptes, actieve status en datum vanaf wanneer data bruikbaar is.
- `FactSensorData`: ruwe sensormetingen per sensor, probe en timestamp.
- `DimBattery`: laatste bekende batterijpercentage per sensor.
- `TenDayForecast`: weersverwachting per dag, inclusief temperatuur, wind, neerslagkans, zon en conditie.

`FactSensorData` heeft een unieke combinatie van `device_id`, `probe_number` en `timestamp`. Daardoor kan de import opnieuw worden uitgevoerd zonder dezelfde meting dubbel in te voegen.

## Gebruikelijke workflow

Voer de commando's bij voorkeur uit vanuit de projectroot `leiden_water_in_the_cloud`.

1. Database aanmaken of schema bijwerken:

```bash
python database_scripts/database_definition.py
```

2. Sensordata en batterijniveaus ophalen:

```bash
python data_collection/sensor_data_import.py
```

Dit script haalt de laatste 100 dagen op uit Quantified, schrijft nieuwe sensorregels naar `FactSensorData`, schoont bekende onbruikbare data van sensor `1386` voor 2025-09-20 op en werkt `DimBattery` bij.

3. Weerdata ophalen:

```bash
python data_collection/weather_data_import.py
```

Dit script werkt `valkenburg_precipitation.csv`, `voorschoten_weerdata.csv` en `TenDayForecast` bij.

4. Kwaliteitscontrole uitvoeren:

```bash
python data_collection/data_ingestion_QC.py
```

De kwaliteitscontrole controleert actieve sensoren met ten minste drie maanden historie. Een sensor slaagt wanneer:

- het batterijpercentage minimaal 25 procent is;
- elke verwachte probe in de laatste 14 volledige UTC-dagen op minimaal 12 dagen data heeft;
- `usable_from` voldoende ver in het verleden ligt voor de betreffende categorie.

De output bestaat uit:

- een voorstel voor `usable_sensors.json`;
- grafieken per sensor in `data_collection/sensor_data/quality_control_plots`;
- eventueel een Excel-export van `DimSensor` in `data_collection/database_exports` wanneer `usable_from` handmatig moet worden aangepast.

5. Voorspellend model ontwikkelen of verversen:

```bash
python data_analyse/train_permittivity_prediction_model.py --method exhaustive
```

Dit voert per sensor, probe en exacte diepte een volledige rasterzoekactie uit. Gebruik `--method coarse-to-fine` voor een veel kleinere grove zoekactie met een fijne vervolgzoekactie rond de beste gebieden. Beide methoden houden de recentste weken buiten de parametertraining en schrijven een Excel-evaluatie en het operationele JSON-model naar `data_analyse/model_artifacts`.

De bewaarde handmatig gekalibreerde modelversie kan afzonderlijk tegen persistence worden gebenchmarkt zonder het operationele model opnieuw te trainen:

```bash
python data_analyse/benchmark_archived_model.py --probes 1 2 3 --output data_analyse/model_artifacts/archived_model_benchmark_probes_1_2_3.csv
```

Dit schrijft een samenvatting naar het opgegeven CSV-bestand en de onderliggende eindtests naar een bestand met `_cases` achter dezelfde basisnaam. Zonder `--output` worden `archived_model_benchmark.csv` en `archived_model_benchmark_cases.csv` overschreven. Kies daarom voor nieuwe controles een herkenbare eigen naam, zodat de bewaarde benchmarks intact blijven. De benchmark is referentiemateriaal en vervangt de wekelijkse parametertraining niet.

6. Beschikbare onafhankelijke evaluatiegrafieken per getrainde probe maken:

```bash
python data_analyse/visualise_permittivity_training.py
```

Het script begint bij alle actieve probes van sensoren uit `usable_sensors.json` en schrijft iedere beschikbare evaluatiegrafiek in `data_analyse/training_visualisation/sensor_<device_id>/probe_<nummer>_<diepte>cm`. Bij vier complete evaluatieweken zijn dit vier grafieken per probe. Een ontbrekend model of weekvenster wordt zichtbaar overgeslagen zonder andere bruikbare probes tegen te houden. Na een geslaagde run vervangt de nieuwe visualisatiemap de bestaande map volledig.

7. Dagelijkse voorspelling uitvoeren:

```bash
python data_analyse/permittivity_prediction_model.py run
```

Deze stap traint niets opnieuw. Het bestaande modelartefact en de actuele weersverwachting worden gebruikt voor een Excel-bestand in `data_analyse/prediction_results`. De regels staan alfabetisch op locatie en daarbinnen van ondiepe naar diepe probe. Voor iedere probe met status `predicted` wordt daarnaast `data_analyse/prediction_visualisation/sensor_<device_id>/probe_<nummer>_<diepte>cm/prediction.png` gemaakt. Ook deze gegenereerde map wordt alleen na een volledig geslaagde run vervangen.

De parametertraining, trainingvisualisatie en dagelijkse voorspelling melden direct hun start, tonen voortgang per probe of grafiek en sluiten af met een voltooiingsregel en de uitvoerpaden. Bij een fout verschijnt eerst een herkenbare stopregel voordat Python de foutdetails toont.

Alle probes van sensoren uit `usable_sensors.json` worden voorspeld. Actieve sensoren buiten die lijst krijgen per probe de status `insufficient_history`. Iedere sensor-probe-dieptecombinatie heeft eigen parameters; gegevens en parameters worden niet tussen sensoren of dieptes gedeeld. De volledige werking en actuele beperkingen staan in `Documentation/voorspellend_model.md`.

8. Data verkennen zonder het model uit te voeren:

```bash
python data_analyse/permittivity_data_exploration.py --device-id 1390 --probe-number 2
```

De standaardweergave bevat twee gekoppelde panelen: relatieve permittiviteit met neerslag en relatieve permittiviteit met de energieproxy. Alleen neerslag of alleen energie kan ook:

```bash
python data_analyse/permittivity_data_exploration.py --device-id 1390 --probe-number 2 --weather-view rain
python data_analyse/permittivity_data_exploration.py --device-id 1390 --probe-number 2 --weather-view energy
```

Gebruik `--probe-number all` om alle in de sensordatabase geregistreerde probes van een sensor te verwerken. Dit staat los van `usable_sensors.json`; die selectie geldt voor het voorspellingsmodel, niet voor handmatige data-exploratie. De probes worden van ondiep naar diep verwerkt. De PNG's staan standaard direct onder `data_analyse/data_exploration/sensor_<device_id>` met de naam `probe_<nummer>_<diepte>cm_<weergave>.png`.

Na een geslaagde uitvoering opent een nieuwe tijdelijke browsergalerij met alle grafieken uit precies die uitvoering. Een volgende uitvoering opent een nieuwe tab en laat een al geopende galerij staan. Gebruik `--no-open` om alleen PNG's te schrijven. `--output-dir` kiest een andere hoofdmap; `--output` kiest bij precies een probe één exact PNG-pad. De start- en einddatum zijn inclusief en kunnen met `--start YYYY-MM-DD` en `--end YYYY-MM-DD` worden begrensd.

De energieproxy is alleen een visuele indicator en verandert geen sensordata of modeluitkomst. De formule en eenheden staan in `Documentation/voorspellend_model.md`.

## Import en export

`data_collection/ImportExport.py` ondersteunt handmatige rondes via Excel:

- `export_dimsensor_to_excel`
- `import_dimsensor_from_excel`
- `export_factsensordata_to_excel`
- `import_factsensordata_from_excel`
- `export_dimbattery_to_excel`
- `import_dimbattery_from_excel`

Deze Excel-bestanden staan in `data_collection/database_exports`. `DimSensor_met_notes.xlsx` is een handmatig aangevulde controlesnapshot en wordt niet door `ImportExport.py` als standaardinvoer gelezen. De bestanden zijn overdrachts- of controlemateriaal en geen live invoer, behalve wanneer een importfunctie bewust wordt gestart.

## Aandachtspunten

- `passwordnemail.py` bevat gevoelige gegevens. Laat dit bestand buiten git en verplaats de waarden later bij voorkeur naar environment variables.
- De import- en weerscripts muteren lokale data en gebruiken externe APIs. Draai ze dus alleen wanneer data echt bijgewerkt moet worden.
- De handmatig gekalibreerde oorspronkelijke versie en drie geselecteerde CatBoost-experimenten staan in `legacy_data/model_experiments`. Zij zijn referentiemateriaal en geen actieve workflow.
- Na iedere training moet het Excel-evaluatiebestand worden gecontroleerd. Een getraind sensormodel is niet automatisch beter dan persistence.
- `catboost_info` is output van modeltraining en geen broncode.
- `data_collection/sensor_data` bevat live runtimebestanden. Verwijder daar niet zomaar bestanden zonder eerst te controleren welk script ze opnieuw kan opbouwen.
- `data_collection/database_exports` bevat snapshots en handmatige exports. Die bestanden kunnen opnieuw worden opgebouwd uit de database, maar kunnen ook handmatige correcties bevatten.

## Snelle controle

Controleer of de database de verwachte tabellen bevat:

```python
import sqlite3

conn = sqlite3.connect("data_collection/sensor_data/database.db")
cur = conn.cursor()
print(cur.execute("select name from sqlite_master where type='table' order by name").fetchall())
conn.close()
```

Verwachte tabellen:

- `DimBattery`
- `DimSensor`
- `FactSensorData`
- `TenDayForecast`

Controleer of de Python-scripts syntactisch geldig zijn:

```bash
python -m compileall -q data_collection database_scripts Watergeven.py
python -m py_compile data_analyse/benchmark_archived_model.py data_analyse/permittivity_data_exploration.py data_analyse/permittivity_prediction_model.py data_analyse/train_permittivity_prediction_model.py data_analyse/visualise_permittivity_training.py
```

Voer daarna de geautomatiseerde model- en visualisatietests uit:

```bash
python -m unittest discover -s data_analyse -p "test_*.py"
```
