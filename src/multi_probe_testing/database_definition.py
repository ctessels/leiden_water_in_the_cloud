import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Create tables
cursor.execute("""
CREATE TABLE IF NOT EXISTS DimSensor (
    device_id INTEGER PRIMARY KEY,
    device_name TEXT,
    measuring_points INTEGER,
    planned_coordinate TEXT,
    actual_coordinate TEXT,
    actual_location_gmaps_link TEXT,
    location_name TEXT,
    location_remark TEXT,
    original_placement_date DATE,
    last_placement_date DATE,
    mp_depth_1 INTEGER,
    mp_depth_2 INTEGER,
    mp_depth_3 INTEGER,
    remarks TEXT,
    is_active INTEGER
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS FactSensorData (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    gateway_receive_time DATETIME,
    temperature REAL,
    relative_permittivity REAL,
    electric_conductivity REAL,
    FOREIGN KEY (device_id) REFERENCES DimSensor (device_id)
);
""")

conn.commit()

# Insert initial data
innitial_insert_sql = """
-- 1038.0 — van_der_paauwkade (2-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1038.0', 2, '(52.166002807050205, 4.495401084423066)', '(52.1659414, 4.4951657)',
       'https://maps.app.goo.gl/HqMpwnCtmifjt3Sj9', 'van_der_paauwkade', NULL,
       '2025-07-18', NULL,
       15, 50, NULL, 'De tweede pin zit in een kleibodem achtige laag, niet meer in de ‘nieuwe’ grond', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1038.0');

-- 1189.0 — marie_jungiusstraat (3-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1189.0', 3, '(52.14727171823178, 4.446818232536317)', '(52.1472801, 4.4470898)',
       'https://maps.app.goo.gl/fbnmx6CoBfoa6sj79', 'marie_jungiusstraat', '137cm vanaf de stoep in lijn met de noordelijke lantaarnpaal',
       '2025-07-31', NULL,
       15, 50, 70, 'Zachte zandbodem die overgaat in ietsjes hardere laag', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1189.0');

-- 1190.0 — park_de_put (2-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1190.0', 2, '(52.16178157625613, 4.4823575019836435)', '(52.1614895, 4.4822653)',
       'https://maps.app.goo.gl/RkHjYYGXp55msUYu7', 'park_de_put', NULL,
       '2025-07-18', NULL,
       15, 30, NULL, 'Op een gegeven moment kwamen we op een harde zandlaag', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1190.0');

-- 1191.0 — wijnbes (3-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1191.0', 3, '(52.17853619213568, 4.497281312942506)', '(52.1786081, 4.4973403)',
       'https://maps.app.goo.gl/LGbne8qBdSKCRQfS8', 'wijnbes', NULL,
       '2025-07-18', NULL,
       15, 50, 75, 'Vergeten foto te maken op het moment dat de pinnen er in zitten. Zachte grond. Totdat het overging in zacht zand', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1191.0');

-- 1192.0 — nelson_mandelapad (2-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1192.0', 2, '(52.15940199412685, 4.4511714577674875)', '(52.1593881, 4.4513532)',
       'https://maps.app.goo.gl/DP8GbZH3hrewiNxP7', 'nelson_mandelapad', '430cm vanaf de stoep naar de sensor in lijnmet de regenpijp',
       '2025-07-31', NULL,
       15, 50, NULL, 'Zachte grondbodem', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1192.0');

-- 1195.0 — lelie_lindestraat (3-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1195.0', 3, '(52.15185886689011, 4.491552114486695)', '(52.1509141, 4.4973403)',
       'https://maps.app.goo.gl/zP4qmuEKQbEdqvC27', 'lelie_lindestraat', NULL,
       '2025-07-18', NULL,
       15, 50, 70, 'Eerst losse aarde, toen een beetje zand, toen wat steviger, leek op klei. Geen stenen', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1195.0');

-- 1196.0 — gabriel_metzusstraat (2-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1196.0', 2, '(52.17184864238036, 4.491621851921082)', '(52.1723575, 4.4917848)',
       'https://maps.app.goo.gl/xmgrXJTUifFKrq2j8', 'gabriel_metzusstraat', NULL,
       '2025-07-18', NULL,
       15, 50, NULL, 'Vergeten foto te maken van de id van de sensor. Hier en daar wat...in de grond. Verwachten niet dat die zijn geraakt door de pinnen', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1196.0');

-- 1197.0 — ing_driessenstraat (3-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1197.0', 3, '(52.15939090039548, 4.499016702175141)', '(52.1593988, 4.4990264)',
       'https://maps.app.goo.gl/qo1ko6xSo6hn21Mc6', 'ing_driessenstraat', NULL,
       '2025-07-18', NULL,
       15, 50, 70, 'We kwamen niet dieper dan 75 centimeter omdat we allemaal stenen...enkwamen. Er lag daar een grint bodem met dakpan achtige stenen.', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '1197.0');

-- 176.0 — opstandingskerk (1-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '176.0', 1, '(52.143043108582724, 4.477859437465669)', '(52.1434156, 4.4777203)',
       'https://maps.app.goo.gl/Bj4V8EPd4FMDGUxX8', 'opstandingskerk', '120cm van de stoep in lijn met de boom',
       '2025-08-07', NULL,
       30, NULL, NULL, 'Sensor op 30cm. Eerste 10cm wortels van kleine planten, daarna losse grond, en de sensor zit in zand.', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '176.0');

-- 135.0 — Agrippinastraat (1-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '135.0', 1, '(52.15930091445541, 4.502333768167688)', NULL,
       'https://maps.app.goo.gl/dmrUkxcof7Bsq1UV9', 'Agrippinastraat', NULL,
       '2025-08-07', NULL,
       30, NULL, NULL, 'Tot 20cm veel wortels. Daarna gewoon grond.', 1
WHERE NOT EXISTS (SELECT 1 FROM DimSensor WHERE device_name = '135.0');

-- 1200.0 — Lakenplein (3-laags)
INSERT INTO DimSensor (
    device_name, measuring_points, planned_coordinate, actual_coordinate,
    actual_location_gmaps_link, location_name, location_remark,
    original_placement_date, last_placement_date,
    mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active
)
SELECT '1200.0', 3, '(52.158239366231655, 4.50286595759141)', '(52.1581423, 4.5026749)',
       'https://www.google.com/maps/place/52%C2%B009''29.7%22N+4%C2%B030''10.3%22E/@52.1582394,4.502866,18z/data=!4m10!1m2!2m1!1s52.158239366231655,+4.50286595759141!3m6!1s0x47c5c6d8f56ac98f:0x5d3f13d43a9a7c7a!8m2!3d52.158249!4d4.502862!15sCiA1Mi4xNTgyMzkzNjYyMzE2NTUsIDQuNTAyODY1OTU3NTkxNDEiA5IBEVBsdW1iZXJfY29vcmRpbmF0ZSI

"""

conn.commit()

conn.close()