# Bewaarde modelexperimenten

Deze map bevat eerdere modelversies als referentie. Zij maken geen deel uit van de actieve workflow en zijn bij het verplaatsen inhoudelijk niet gewijzigd.

## permittivity_prediction_model_before_dynamic.py

Dit is de volledige versie van `data_analyse/permittivity_prediction_model.py` van voor de dynamische dieptemodellen. De versie gebruikt alleen probe 1 en bevat handmatige parameters per sensor, modelberekening, evaluatie en interactieve grafieken in hetzelfde bestand.

## Model_fit.py

Een CatBoost-experiment dat per sensor SMI voorspelt uit eerdere SMI, regen, weer en seizoenskenmerken. Waardevol als referentie voor feature engineering en tijdgeordende evaluatie. De implementatie gebruikt alleen probe 1, normaliseert over de volledige reeks en maakt een niet-gekalibreerd betrouwbaarheidsinterval.

## Model_voorspelling.py

Een experiment dat dagelijkse SMI-verandering voorspelt en toekomstige SMI recursief simuleert. Het idee van een toestandsverandering per dag is bruikbaar, maar de implementatie heeft verschillen tussen trainings- en voorspellingskenmerken en integreert de operationele weersverwachting niet volledig.

## voorspelling_2.py

Een direct multi-horizon CatBoost-experiment dat tien toekomstige SMI-waarden tegelijk voorspelt en toekomstig weer als kenmerken gebruikt. Het vermijdt recursieve foutopbouw, maar bevat vaste historische datums, traint per sensor en heeft onvoldoende onafhankelijke validatie voor operationeel gebruik.
