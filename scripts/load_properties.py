import pandas as pd
import psycopg2
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
EXCEL_PATH = BASE_DIR / "UNIT INFO.xlsx"

DB_URL = __import__("os").environ["DATABASE_URL"]

def normalize_geo(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.strip().lower())

def main():
    df = pd.read_excel(EXCEL_PATH)

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # -------------------------------
    # Load geos (COMMUNITY)
    # -------------------------------
    communities = (
        df["COMMUNITY"]
        .dropna()
        .astype(str)
        .unique()
    )

    geo_map = {}

    for name in communities:
        geo_code = normalize_geo(name)

        cur.execute("""
            INSERT INTO geos (geo_code, geo_name, geo_type)
            VALUES (%s, %s, 'COMMUNITY')
            ON CONFLICT (geo_code) DO UPDATE
            SET geo_name = EXCLUDED.geo_name
            RETURNING id;
        """, (geo_code, name))

        geo_map[name] = cur.fetchone()[0]

    # -------------------------------
    # Load properties (approved fields only)
    # -------------------------------
    for _, row in df.iterrows():
        if pd.isna(row["UNIT CODE"]) or pd.isna(row["ADDRESS"]):
            continue

        cur.execute("""
            INSERT INTO properties (
                property_code,
                address_raw,
                geo_id,
                bedrooms,
                bathrooms,
                guide_url
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (property_code) DO UPDATE SET
                address_raw = EXCLUDED.address_raw,
                geo_id = EXCLUDED.geo_id,
                bedrooms = EXCLUDED.bedrooms,
                bathrooms = EXCLUDED.bathrooms,
                guide_url = EXCLUDED.guide_url;
        """, (
            str(row["UNIT CODE"]).strip(),
            str(row["ADDRESS"]).strip(),
            geo_map.get(row["COMMUNITY"]),
            str(row.get("BEDROOMS", "")).strip(),
            str(row.get("BATHROOMS", "")).strip(),
            str(row.get("PROPERTY GUIDE", "")).strip()
        ))

    conn.commit()
    cur.close()
    conn.close()

    print("✅ Properties and geos loaded successfully.")

if __name__ == "__main__":
    main()
