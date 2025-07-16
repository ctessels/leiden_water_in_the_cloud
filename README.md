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

2. Maak een virtuele omgeving aan en activeer deze met uv:
```bash
uv venv
source .venv/bin/activate  # Voor Unix/macOS
# of
.venv\Scripts\activate     # Voor Windows
```

3. Installeer dependencies:
```bash
uv pip install -r requirements.txt
```

4. Maak een `.env` bestand aan in de projectroot met de volgende inhoud:
```
EMAIL=jouw_quantified_email
PASSWORD=jouw_quantified_wachtwoord
```

## Project Structuur

```
src/
├── api_components/           # API-integratie en data ophalen
│   ├── data_loading.py      # Data laad-utilities
│   ├── refresh_external_data.py
│   └── refresh_quantified.py # Quantified API-integratie
├── logic_components/         # Data verwerking en analyse
│   ├── data_transformations.py
│   ├── powerpoint.py
│   └── visuals.py           # Visualisatie functies
├── data/                    # Data opslag
└── visuals/                 # Gegenereerde visualisaties
```

## Gebruik
Om nieuwe sensordata bij te werken, voer notebook `sensor_data_prep.ipynb` uit
Voor analyse en visualisatie, voer notebook `sensor_analyse_fase_1.ipynb` uit
In notebook `sensor_analyse_uitgebreid.ipynb` vind je uitgebreide analyses en visualisaties.

## Databronnen

- Bodemsensoren: Quantified API
- Weerdata: KNMI (station 240 - Schiphol)
- Lokaal weer: Leiden weerstation (Zusterhof)
