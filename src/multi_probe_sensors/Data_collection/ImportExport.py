# Imports
from datetime import date, datetime
from pathlib import Path
import sqlite3

import pandas as pd

# Constants
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "multi_probe_data" / "database.db"


# Functions
def _get_db_path(db_path: Path | str) -> Path:
    return Path(db_path).resolve()


def _normalise_sql_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _dataframe_rows(dataframe: pd.DataFrame) -> list[tuple[object, ...]]:
    return [
        tuple(_normalise_sql_value(value) for value in row)
        for row in dataframe.itertuples(index=False, name=None)
    ]


def export_dimsensor_to_excel(db_path: Path | str = DB_PATH) -> Path:
    db_path = _get_db_path(db_path)
    query = "SELECT * FROM DimSensor"
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
        output_path = db_path.parent / "DimSensor.xlsx"
        df.to_excel(output_path, index=False, sheet_name="DimSensor")

    print(f"Exported {len(df)} rows to {output_path}")
    return output_path


def import_dimsensor_from_excel(db_path: Path | str = DB_PATH) -> None:
    db_path = _get_db_path(db_path)
    df = pd.read_excel(db_path.parent / "DimSensor.xlsx", sheet_name="DimSensor")

    if df.empty:
        print("Excel file is empty. Nothing to import.")
        return

    columns = list(df.columns)
    quoted_cols = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)

    insert_sql = f"""
        INSERT INTO DimSensor ({quoted_cols})
        VALUES ({placeholders})
    """

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM DimSensor")
        cur.executemany(insert_sql, _dataframe_rows(df))
        conn.commit()

    print(f"Truncated DimSensor and inserted {len(df)} rows.")


def export_factsensordata_to_excel(db_path: Path | str = DB_PATH) -> Path:
    db_path = _get_db_path(db_path)
    query = "SELECT * FROM FactSensorData"
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
        output_path = db_path.parent / "FactSensorData.xlsx"
        df.to_excel(output_path, index=False, sheet_name="FactSensorData")

    print(f"Exported {len(df)} rows to {output_path}")
    return output_path


def import_factsensordata_from_excel(db_path: Path | str = DB_PATH) -> None:
    db_path = _get_db_path(db_path)
    df = pd.read_excel(
        db_path.parent / "FactSensorData.xlsx",
        sheet_name="FactSensorData",
    )

    if df.empty:
        print("Excel file is empty. Nothing to import.")
        return

    columns = list(df.columns)
    quoted_cols = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)

    insert_sql = f"""
        INSERT INTO FactSensorData ({quoted_cols})
        VALUES ({placeholders})
    """

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM FactSensorData")
        cur.executemany(insert_sql, _dataframe_rows(df))
        conn.commit()

    print(f"Truncated FactSensorData and inserted {len(df)} rows.")


def export_dimbattery_to_excel(db_path: Path | str = DB_PATH) -> Path:
    db_path = _get_db_path(db_path)
    query = "SELECT * FROM DimBattery"

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
        output_path = db_path.parent / "DimBattery.xlsx"
        df.to_excel(output_path, index=False, sheet_name="DimBattery")

    print(f"Exported {len(df)} rows to {output_path}")
    return output_path


def import_dimbattery_from_excel(db_path: Path | str = DB_PATH) -> None:
    db_path = _get_db_path(db_path)
    input_path = db_path.parent / "DimBattery.xlsx"
    df = pd.read_excel(input_path, sheet_name="DimBattery")

    if df.empty:
        print("Excel file is empty. Nothing to import.")
        return

    columns = list(df.columns)
    quoted_cols = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)

    insert_sql = f"""
        INSERT INTO DimBattery ({quoted_cols})
        VALUES ({placeholders})
    """

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM DimBattery")
        cur.executemany(insert_sql, _dataframe_rows(df))
        conn.commit()

    print(f"Truncated DimBattery and inserted {len(df)} rows.")


if __name__ == "__main__":
    export_factsensordata_to_excel(DB_PATH)
