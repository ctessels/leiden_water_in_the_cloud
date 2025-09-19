import sqlite3

conn = sqlite3.connect('multi_probe_data/database.db')
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
    probe_number INTEGER NOT NULL,
    timestamp DATETIME NOT NULL, --Unix timestamp, so its actually an INT
    gateway_receive_time DATETIME,
    temperature REAL,
    relative_permittivity REAL,
    electric_conductivity REAL,
    FOREIGN KEY (device_id) REFERENCES DimSensor (device_id)
    UNIQUE(device_id, probe_number, timestamp)
);
""")

conn.commit()

# Check if initial data insert has happened already
cursor.execute("SELECT 1 FROM DimSensor WHERE device_name = ?", ("1038",))
exists = cursor.fetchone()

# Insert initial data
if not exists:
    initial_insert_sql = """
    INSERT INTO DimSensor (
        device_id,
        device_name,
        measuring_points,
        planned_coordinate,
        actual_coordinate,
        actual_location_gmaps_link,
        location_name,
        location_remark,
        original_placement_date,
        last_placement_date,
        mp_depth_1,
        mp_depth_2,
        mp_depth_3,
        remarks,
        is_active
    )
    VALUES (
        1432,
        '1038',
        2,
        '(52.166002807050205, 4.495401084423066)',
        '(52.1659414, 4.4951657)',
        'https://maps.app.goo.gl/HqMpwnCtmifjt3Sj9',
        'van_der_paauwkade',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        50,
        NULL,
        'De tweede pin zit in een kleibodemachtige laag, niet meer in de ‘nieuwe’ grond',
        1
    ),
    (
        1384,
        '1189',
        3,
        '(52.14727171823178, 4.446818232536317)',
        '(52.1472801, 4.4470898)',
        'https://maps.app.goo.gl/fbnmx6CoBfoa6sj79',
        'marie_jungiusstraat',
        '137cm vanaf de stoep in lijn met de noordelijke lantarenpaal.',
        '2025-07-31',
        '2025-07-31',
        15,
        50,
        70,
        'Zachte zandbodem die overgaat in ietsjes harder grijs zand. Klei?',
        1
    ),
    (
        1385,
        '1190',
        2,
        '(52.16178157625613, 4.4823575019836435)',
        '(52.1614895, 4.4822653)',
        'https://maps.app.goo.gl/RkHjYYGXp55msUYu7',
        'park_de_put',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        30,
        NULL,
        'Op een gegeven moment kwamen we op een harde zand / klei laag terecht. Daar kwamen we met de schep niet doorheen. Dan heb je zwaarder materieel nodig',
        1
    ),
    (
        1386,
        '1191',
        3,
        '(52.17853619213568, 4.497281312942506)',
        '(52.1786081, 4.4973403)',
        'https://maps.app.goo.gl/LGbne8qBdSKCRQfS8',
        'wijnbes',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        50,
        75,
        'Vergeten foto te maken op het moment dat de pinnen er in zitten. Zachte grond. Totdat het overging in zacht zand',
        1
    ),
    (
        1387,
        '1192',
        2,
        '(52.15940199412685, 4.4511714577674875)',
        '(52.1593881, 4.4513532)',
        'https://maps.app.goo.gl/DP8GbZH3hrewiNxP7',
        'nelson_mandelapad',
        '430cm vanaf de stoep naar de sensor in lijn met de regenpijp',
        '2025-07-31',
        '2025-07-31',
        15,
        50,
        NULL,
        'Zachte grondbodem',
        1
    ),
    (
        1390,
        '1195',
        3,
        '(52.15185886689011, 4.491552114486695)',
        '(52.1509141, 4.4973403)',
        'https://maps.app.goo.gl/zP4qmuEKQbEdqvC27',
        'lelie_lindestraat',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        50,
        70,
        'Eerst losse aarde, toen een beetje zand, toen wat steviger, leek op klei. Geen stenen',
        1
    ),
    (
        1391,
        '1196',
        2,
        '(52.17184864238036, 4.491621851921082)',
        '(52.1723575, 4.4917848)',
        'https://maps.app.goo.gl/xmgrXJTUifFKrq2j8',
        'gabriel_metzusstraat',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        50,
        NULL,
        'Vergeten foto te maken van de id van de sensor. Hier en daar wat steentjes in de grond. Verwachten niet dat die zijn geraakt door de pinnen',
        1
    ),
    (
        1392,
        '1197',
        3,
        '(52.15939090039548, 4.499016702175141)',
        '(52.1593988, 4.4990264)',
        'https://maps.app.goo.gl/qo1ko6xSo6hn21Mc6',
        'ing_driessenstraat',
        NULL,
        '2025-07-18',
        '2025-07-18',
        15,
        50,
        70,
        'We kwamen niet dieper dan 75 centimeter omdat we allemaal stenen tegenkwamen. Er lag daar een grint bodem met dakpan achtige stenen.',
        1
    ),
    (
        399,
        '176',
        1,
        '(52.143043108582724, 4.477859437465669)',
        '(52.1434156, 4.4777203)',
        'https://maps.app.goo.gl/Bj4V8EPd4FMDGUxX8',
        'opstandingskerk',
        '120cm van de stoep in lijn met de boom',
        '2025-08-07',
        '2025-08-07',
        30,
        NULL,
        NULL,
        'Sensor op 30cm. Eerste 10cm wortels van kleine planten, daarna losse grond, en de sensor zit in zand.',
        1
    ),
    (
        360,
        '135',
        1,
        '(52.14853796589655, 4.514796137809754)',
        '(52.1483721, 4.5151492)',
        'https://maps.app.goo.gl/dmrUkxcof7Bsq1UV9',
        'Agrippinastraat',
        '107cm van stoep in lijn met boom',
        '2025-08-07',
        '2025-08-07',
        30,
        NULL,
        NULL,
        'Tot 20cm veel wortels. Daarna gewoon grond.',
        1
    ),
    (
        1393,
        '1200',
        3,
        '(52.158239366231655, 4.50286595759141)',
        '(52.1581423, 4.5026749)',
        "https://www.google.com/maps/place/52%C2%B009\'29.7%22N+4%C2%B030\'10.3%22E/@52.1581768,4.5027587,150m/data=!3m1!1e3!4m13!1m8!3m7!1s0x47c5c68ffde88c81:0x61ab599d88945b80!2sLakenplein,+2312+WM+Leiden!3b1!8m2!3d52.1580913!4d4.5024529!16s%2Fg%2F11ss1kgq6_!3m3!8m2!3d52.15825!4d4.502861?entry=ttu&g_ep=EgoyMDI1MDgxMy4wIKXMDSoASAFQAw%3D%3D",
        'Lakenplein',
        '~360cm van de stoep in lijn met de boom.',
        '2025-08-07',
        '2025-08-07',
        30,
        30,
        30,
        'De sensoren zijn zo geplaatst dat nummer 1 dicht bij de boom ligt naast een struikje die nog een beetje zal overwoekerde. Nummer 2 ligt buiten het plantsoentje in de volle zon waar de grasmat begint. Nummer 3 ligt onder de woekerplanten. Allemaal op 30cm. Sensor ligt bij nummer 3. Het was moeilijk om de draden goed weg te werken dus hopen dat er niks met de sensor gebeurt. Geen idee wat het effect van de planten op het signaal is.',
        1
    )
    """
    cursor.execute(initial_insert_sql)
    conn.commit()
else:
    print('Initial data already exists')


import query_helper as qh

select_dimsensor = """
SELECT
    device_id,
    device_name,
    measuring_points,
    actual_coordinate,
    location_name,
    mp_depth_1,
    mp_depth_2,
    mp_depth_3,
    is_active
FROM DimSensor
ORDER BY measuring_points DESC
"""
qh.select(cursor=cursor, query=select_dimsensor)

conn.close()