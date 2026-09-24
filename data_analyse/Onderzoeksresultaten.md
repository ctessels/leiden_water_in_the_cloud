# Regel gestuurd voorspellen

> Status: historische onderzoeksnotities. De observaties hieronder zijn niet opnieuw gevalideerd en de checklist is geen actuele ontwikkelplanning. Gebruik `Documentation/voorspellend_model.md` voor de actieve modelwerking en `permittivity_data_exploration.py` voor reproduceerbare grafieken.

### Te doen
- [ ] Wat is 'zware regen'? Hypothese: Alles boven de 10 mm per dag.
- [ ] Wat is het effect van meerdere dagen niet-zware regen? Controleer andere sensoren.
- [ ] Wat is het seizoensgebonden effect van de afname in vocht? Breng dit in een grafiek weer. Sinusgolf door het jaar heen.
- [ ] Hoeveel piek per regenbui in tegenstelling tot de neerwaartse trend?
- [ ] Effecten van temperatuur op negatieve piek?
- [x] Kan bodemtemperatuur inderdaad een kleinere negatieve trend verklaren? Controleer andere meetpunten met een stijgende trend. Antwoord: Nee
- [ ] Hoe verschillen de verschillende probes van dezelfde sensoren van elkaar?
- [ ] Is de Oegstgeestsensor te verklaren.



### Notes
Eenvoudige grafiek ing_driessenstraat (id: 1392) van bodemgegevens met regengegevens
Conclusies:   Het vochtgehalte lijkt goed te reageren op hevige regen, met misschien een dag vertraging.
              In de maanden voorafgaand aan de zomer is er een dalende trend.
              Pieken worden veroorzaakt door regen, maar de daling lijkt voornamelijk seizoensgebonden te zijn.
Te doen:      Wat is 'zware regen'? Hypothese: Alles boven de 10 mm per dag.
              Wat is het effect van meerdere dagen niet-zware regen? Controleer andere sensoren.
              Wat is het seizoensgebonden effect van de afname in vocht? Breng dit in een grafiek weer. Sinusgolf door het jaar heen.
              Hoeveel piek per regenbui in tegenstelling tot de neerwaartse trend?
              Effecten van temperatuur op negatieve piek?
```bash
python data_analyse/permittivity_data_exploration.py --device-id 1392 --probe-number all --weather-view rain
```

gabriel_metzusstraat negeert al deze conclusies
```bash
python data_analyse/permittivity_data_exploration.py --device-id 1391 --probe-number all --weather-view rain
```

De van_der_paauwkade vertoont veel meer stabiliteit door de seizoenen heen en laat zelfs een lichte stijging in vochtgehalte zien.
Reageert ook stabieler op regen.
```bash
python data_analyse/permittivity_data_exploration.py --device-id 1432 --probe-number all --weather-view rain
```

Het Lakenplein lijkt dezelfde logica te volgen als de gabriel_metzusstraat. Vreemd.
```bash
python data_analyse/permittivity_data_exploration.py --device-id 1393 --probe-number all --weather-view rain
```

Als je alle bruikbare sensoren naast elkaar bekijkt, lijkt het erop dat een stijgende trend misschien wel vaker voorkomt.
De actieve exploratietool maakt geen gezamenlijke figuur van meerdere sensoren. Gebruik de sensor-ID's uit `data_collection/sensor_data/usable_sensors.json` en voer het bovenstaande commando per sensor uit.

Als we de ing_driessenstraat en het Lakenplein vergelijken,  lijkt het erop dat de bodemtemperatuur op het Lakenplein sterker is gedaald.
Een lagere bodemtemperatuur zou leiden tot minder verdamping.
Inderdaad, in de ing_driessenstraat is het vochtgehalte gedaald, terwijl dat op het Lakenplein niet het geval is.
