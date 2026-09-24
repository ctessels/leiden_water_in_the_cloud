# Water in the Cloud - Leiden

Een data-analyseproject voor het monitoren van bodemvochtigheidssensoren in de stad Leiden. Dit project verzamelt, verwerkt en visualiseert data van bodemvochtigheidssensoren en hun batterijniveaus op verschillende locaties in Leiden.

## Beschrijving

Dit project bestaat uit verschillende componenten:

1. **Data Verzameling**
   - Haalt sensordata op via de Quantified API (relatieve permittiviteit en batterijniveaus)
   - Integreert historische KNMI-data en Meteoserver-weersverwachtingen
   - Beheert sensorlocaties en documentatiegegevens

2. **Data Verwerking**
   - Schoont sensormetingen op en transformeert deze
   - Combineert sensordata met locatie-informatie
   - Verwerkt weerdata voor correlatie-analyse

3. **Visualisatie**
   - Creëert tijdreeksvisualisaties van sensormetingen, neerslag en energieproxy
   - Genereert kwaliteitscontrolegrafieken per sensor
   - Genereert trainings- en voorspellingsgrafieken per sensor, probe en diepte

## Vereisten

- Python 3.12 of nieuwer
- uv (Python package installer en virtual environment manager)

## Installatie

1. Clone de repository:
```bash
git clone https://github.com/joramspan91/leiden_water_in_the_cloud
```

2. Installeer `uv` als je dit nog niet hebt:

Voor macOS:
- Install brew on Mac (als je dit nog niet hebt):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
source ~/.zshrc
brew --version
brew install uv
```

Voor Windows:
Zie > https://docs.astral.sh/uv/getting-started/installation/

3. Maak een virtuele omgeving aan en activeer deze met uv:
```bash
uv venv
source .venv/bin/activate  # Voor macOS
# of
.venv\Scripts\activate     # Voor Windows
```

4. Installeer dependencies:
```bash
uv pip install -r requirements.txt
```

5. Maak of vul `passwordnemail.py` in de projectroot. De actieve scripts verwachten daarin `secrets` voor Quantified en `meteoserver_key` voor Meteoserver. Dit bestand wordt door git genegeerd.

## Project Structuur

```
Documentation/         # Projectdocumentatie, rapporten en modeluitleg
legacy_data/           # Oude data en bewaarde modelexperimenten
data_collection/       # API-imports, weerdata, QC, runtime data en exports
database_scripts/      # Database-definitie en query-hulpmiddelen
data_analyse/          # Data-exploratie, modelontwikkeling en dagelijkse voorspelling
Watergeven.py          # Eenmalige analyse van watergeefdata
```

## Gebruik
Voer commando's bij voorkeur uit vanuit de projectroot.

1. Maak of werk de database bij met `database_scripts/database_definition.py`.
2. Haal sensordata op met `data_collection/sensor_data_import.py`.
3. Haal weerdata op met `data_collection/weather_data_import.py`.
4. Controleer bruikbare sensoren met `data_collection/data_ingestion_QC.py`.
5. Train de sensorparameters met `python data_analyse/train_permittivity_prediction_model.py --method exhaustive` of de snellere methode `--method coarse-to-fine`.
6. Maak de dagelijkse Excel-voorspelling met `python data_analyse/permittivity_prediction_model.py run`.

Data-exploratie staat apart van het model in `data_analyse/permittivity_data_exploration.py`. Gebruik bijvoorbeeld `python data_analyse/permittivity_data_exploration.py --device-id 1384 --probe-number all` voor alle probes van een sensor. De gecombineerde weergave met neerslag en energieproxy is standaard; kies desgewenst `--weather-view rain` of `--weather-view energy`. Iedere uitvoering opent een nieuwe browsergalerij. Het model gebruikt alle probes van sensoren uit `usable_sensors.json` en traint iedere combinatie van sensor, probe en exacte diepte zelfstandig.

Het voorspellende model is nog niet biologisch gevalideerd voor automatische watergeefbesluiten. Controleer na iedere training de Excel-evaluatie en vergelijk model-MAE met persistence-MAE voordat een modelartefact operationeel wordt gebruikt.

Meer uitleg over de workflow, database, scripts en aandachtspunten staat in `Documentation/project_documentatie.md`. De werking van het voorspellende model staat in `Documentation/voorspellend_model.md`.

## Databronnen

- Bodemsensoren: Quantified API
- Historische neerslag: KNMI Valkenburg
- Historische weerdata: KNMI Voorschoten
- Verwachte weerdata: Meteoserver
