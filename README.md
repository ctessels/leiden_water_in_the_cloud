# Water in the Cloud - Leiden

Een data-analyseproject voor het monitoren van bodemvochtigheidssensoren in de stad Leiden. Dit project verzamelt, verwerkt en visualiseert data van bodemvochtigheidssensoren en hun batterijniveaus op verschillende locaties in Leiden.

## Beschrijving

Dit project bestaat uit verschillende componenten:

1. **Data Verzameling**
   - Haalt sensordata op via de Quantified API (permeabiliteit en batterijniveaus)
   - Integreert weerdata van KNMI en lokale Leidse weerstations
   - Beheert sensorlocaties en documentatiegegevens

2. **Data Verwerking**
   - Schoont sensormetingen op en transformeert deze
   - Combineert sensordata met locatie-informatie
   - Verwerkt weerdata voor correlatie-analyse

3. **Visualisatie**
   - Creëert tijdreeksvisualisaties van sensormetingen
   - Brengt sensorlocaties in kaart met hun huidige status
   - Genereert rapporten met gecombineerde sensor- en weerdata

## Vereisten

- Python 3.12
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

5. Maak een `.env` bestand aan in de projectroot met de volgende inhoud:
```
EMAIL=jouw_quantified_email
PASSWORD=jouw_quantified_wachtwoord
```

## Project Structuur

```
src/
└── multi_probe_sensors/
    ├── Data_collection/      # API-imports, weerdata en kwaliteitscontrole
    ├── Data-analyse/         # Analyse op basis van de SQLite-database
    ├── Database_scripts/     # Database-definitie en query-hulpmiddelen
    └── Watergeven.py         # Eenmalige analyse van watergeefdata
```

## Gebruik
De huidige workflow staat in `src/multi_probe_sensors`.

1. Maak of werk de database bij met `Database_scripts/database_definition.py`.
2. Haal sensordata op met `Data_collection/multi_probe_data_import.py`.
3. Haal weerdata op met `Data_collection/weather_data_import.py`.
4. Controleer bruikbare sensoren met `Data_collection/data_ingestion_QC.py`.
5. Voer analyses uit vanuit `Data-analyse/Data-analyse.py` of de scripts in `Schroothoop`.

## Databronnen

- Bodemsensoren: Quantified API
- Historische neerslag: KNMI Valkenburg
- Historische weerdata: KNMI Voorschoten
- Verwachte weerdata: Meteoserver
