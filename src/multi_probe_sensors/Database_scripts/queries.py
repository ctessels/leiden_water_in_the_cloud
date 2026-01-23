"""
Een onoverzichtelijke hoeveelheid queries die ik vaker gebruik.
ChatGPT heeft een poging gedaan het te ordenen
"""

import sqlite3
import query_helper as qh
from datetime import datetime
from time import mktime

DB_PATH = "../multi_probe_data/database.db"

# ----------------------------
# Helpers
# ----------------------------
def run_select(cursor, sql: str):
    qh.select(cursor, sql)


def run_execute(cursor, sql: str, params=None):
    if params is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, params)


# ----------------------------
# FactSensorData: inspection
# ----------------------------
SQL_FACT_BY_DEVICE_ORDERED = """
select *
from FactSensorData
where device_id = 1392
order by timestamp, device_id, probe_number
"""

SQL_ACTIVE_PROBE1_WITH_METADATA = """
select
    fsd.row_id,
    fsd.device_id,
    ds.device_name,
    ds.location_name,
    fsd.probe_number,
    fsd.timestamp,
    fsd.temperature as ground_temperature,
    fsd.relative_permittivity,
    ds.is_active,
    ds.mp_depth_1,
    ds.mp_depth_2,
    ds.mp_depth_3
from FactSensorData fsd
left join DimSensor ds
    on fsd.device_id = ds.device_id
where ds.is_active = 1
  and fsd.probe_number = 1
  and ds.last_placement_date < '2025-09-08'
  and ds.last_placement_date is not null
"""

SQL_FACT_MIN_MAX_TS = """
select
    device_id,
    max(timestamp) as max_ts,
    min(timestamp) as min_ts
from FactSensorData
where device_id = 356
"""


# ----------------------------
# FactSensorData: cleanup (redeployment cutoff)
# ----------------------------
def delete_fact_before_timestamp(cursor, device_id: int, cutoff_epoch: int):
    run_execute(
        cursor,
        """
        delete from FactSensorData
        where device_id = ?
          and timestamp < ?
        """,
        (device_id, cutoff_epoch),
    )
# Example:
# cutoff = int(mktime(datetime(2025, 9, 20).timetuple()))
# delete_fact_before_timestamp(cursor, device_id=1386, cutoff_epoch=cutoff)


# ----------------------------
# DimSensor: corrections (single sensor)
# ----------------------------
def update_dimsensor_metadata_full(cursor, device_id: int):
    run_execute(
        cursor,
        """
        update DimSensor
        set planned_coordinate = '(52.150338078309105, 4.4439471059158775)',
            actual_coordinate = '(52.15008391730577, 4.444019004241613)',
            actual_location_gmaps_link = 'https://maps.app.goo.gl/t6QaaYLQgWB8cUGz7',
            location_name = 'Annie van Hattemstraat',
            location_remark = 'Vanaf 30cm zand. Daarboven gewoon grond.',
            original_placement_date = '2025-10-28',
            last_placement_date = '2025-10-28',
            mp_depth_1 = 15,
            mp_depth_2 = 50,
            mp_depth_3 = 70,
            remarks = 'Vanaf 30cm zand. Daarboven gewoon grond.',
            is_active = 1,
            situation = 'Volledig functioneel',
            datavalidatie = 'Trends kloppen vanaf laatste plaatsing'
        where device_id = ?
        """,
        (device_id,),
    )


def set_sensor_active_status_by_name(cursor, device_name: int, is_active: int, situation: str):
    run_execute(
        cursor,
        """
        update DimSensor
        set is_active = ?,
            situation = ?
        where device_name = ?
        """,
        (is_active, situation, device_name),
    )


def set_datavalidatie_by_device_id(cursor, device_id: int, datavalidatie: str):
    run_execute(
        cursor,
        """
        update DimSensor
        set datavalidatie = ?
        where device_id = ?
        """,
        (datavalidatie, device_id),
    )


# ----------------------------
# DimSensor: bulk edits
# ----------------------------
def set_last_placement_date_bulk(cursor, device_ids, last_placement_date: str):
    placeholders = ",".join("?" for _ in device_ids)
    run_execute(
        cursor,
        f"""
        update DimSensor
        set last_placement_date = ?
        where device_id in ({placeholders})
        """,
        (last_placement_date, *device_ids),
    )
# Example:
# set_last_placement_date_bulk(cursor, [356, 369, 361, 372, 395, 397, 404, 414, 416, 418], "2025-07-18")


# ----------------------------
# DimSensor: inserts (new sensors)
# ----------------------------
def insert_dimsensors_minimal(cursor, rows):
    """
    rows: list of tuples matching:
    (device_id, device_name, measuring_points, planned_coordinate,
     actual_location_gmaps_link, location_name, mp_depth_1, situation, datavalidatie)
    """
    cursor.executemany(
        """
        insert into DimSensor (
            device_id, device_name, measuring_points, planned_coordinate, actual_coordinate,
            actual_location_gmaps_link, location_name, location_remark, original_placement_date,
            last_placement_date, mp_depth_1, mp_depth_2, mp_depth_3, remarks, is_active,
            situation, datavalidatie
        ) values (?, ?, ?, ?, null, ?, ?, null, null, null, ?, null, null, null, 1, ?, ?)
        """,
        rows,
    )


# ----------------------------
# Forecast tables: inspection
# ----------------------------
SQL_SELECT_TENDAYFORECAST = "select * from TenDayForecast"


# ----------------------------
# DimSensor: reporting
# ----------------------------
SQL_LIST_DIMSENSOR_OVERVIEW = """
select distinct
    device_id,
    device_name,
    location_name,
    actual_location_gmaps_link,
    is_active,
    last_placement_date,
    datavalidatie,
    measuring_points
from DimSensor
"""

SQL_USEFUL_SENSORS = """
select distinct
    device_id,
    device_name,
    location_name,
    actual_location_gmaps_link,
    is_active,
    measuring_points,
    last_placement_date,
    datavalidatie
from DimSensor
where is_active = 1
  and last_placement_date = '2025-07-18'
  and datavalidatie = 'Trends kloppen'
"""



def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Examples of typical one-off actions ---
    # run_select(cursor, SQL_LIST_DIMSENSOR_OVERVIEW)

    # set_sensor_active_status_by_name(cursor, device_name=190, is_active=0,
    #                                 situation="Geen data sinds 3 oktober. Verloren gegaan")

    # set_datavalidatie_by_device_id(cursor, 397, "Datafrequentie te laag")

    run_select(cursor, SQL_LIST_DIMSENSOR_OVERVIEW)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()