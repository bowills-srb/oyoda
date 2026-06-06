#!/usr/bin/env python3
"""
Read and import the updated UNIT INFO.xlsx into the database.
"""

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import json
from pathlib import Path

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

def main():
    # Read the Excel file
    excel_path = Path(__file__).parent.parent / "UNIT INFO.xlsx"
    print(f"Reading: {excel_path}")
    
    df = pd.read_excel(excel_path)
    
    print("\n" + "=" * 70)
    print("EXCEL FILE CONTENTS")
    print("=" * 70)
    
    print(f"\nColumns ({len(df.columns)}):")
    for i, col in enumerate(df.columns):
        print(f"  {i+1}. {col}")
    
    print(f"\nRows: {len(df)}")
    
    print("\n" + "=" * 70)
    print("FIRST 3 PROPERTIES")
    print("=" * 70)
    
    for idx, row in df.head(3).iterrows():
        print(f"\n--- Property {idx+1} ---")
        for col in df.columns:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                print(f"  {col}: {val}")
    
    print("\n" + "=" * 70)
    print("COLUMN MAPPING PREVIEW")
    print("=" * 70)
    
    # Show what columns we have vs what we need
    db_columns = [
        'property_code', 'address_street', 'address_city', 'address_state', 'address_zip',
        'community', 'bedrooms', 'bathrooms', 'sleeps', 'check_in_time', 'check_out_time',
        'wifi_network', 'wifi_password', 'lock_type', 'property_guide_url',
        'has_pool', 'pool_heated', 'has_hot_tub', 'has_grill', 'has_bikes', 'bike_count',
        'has_beach_gear', 'has_washer_dryer', 'pets_allowed', 'rep_name', 
        'housekeeper_name', 'housekeeper_phone', 'quiet_hours_start', 'quiet_hours_end',
        'general_notes'
    ]
    
    excel_cols_lower = [c.lower().strip() for c in df.columns]
    
    print("\nMatching columns:")
    for db_col in db_columns:
        matches = [c for c in df.columns if db_col.replace('_', ' ') in c.lower() or db_col.replace('_', '') in c.lower().replace(' ', '')]
        if matches:
            print(f"  ✓ {db_col} → {matches[0]}")
        else:
            print(f"  ✗ {db_col} → (not found)")
    
    # Save to JSON for inspection
    output_path = Path(__file__).parent.parent / "data" / "unit_info_preview.json"
    df.head(5).to_json(output_path, orient='records', indent=2)
    print(f"\nPreview saved to: {output_path}")


if __name__ == "__main__":
    main()
