#!/usr/bin/env python3
"""
Load properties from UNIT INFO.xlsx into the properties table.

Usage:
    python scripts/load_properties_from_xlsx.py

Or with a specific file:
    python scripts/load_properties_from_xlsx.py --file /path/to/UNIT_INFO.xlsx

Requires:
    pip install pandas openpyxl psycopg2-binary
"""

import argparse
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values, Json


# Default tenant ID - replace with your actual tenant
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Database connection — use direct Supabase URL (not pooler) for psycopg2 scripts
# Pooler (port 6543) drops SSL connections for long-running scripts
_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)
# Convert asyncpg URL to psycopg2 format and force direct connection
DATABASE_URL = (
    _raw_url
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace(":6543/", ":5432/")  # use direct port, not pooler
)
# Ensure sslmode is set
if "sslmode" not in DATABASE_URL:
    DATABASE_URL += "?sslmode=require"


def parse_bedrooms(value: str) -> tuple[int, bool]:
    """Parse bedrooms field, extracting count and bike status."""
    if pd.isna(value):
        return 0, True
    
    value_str = str(value)
    # Extract number
    match = re.search(r'(\d+)', value_str)
    bedrooms = int(match.group(1)) if match else 0
    
    # Check for NO BIKES
    has_bikes = "NO BIKES" not in value_str.upper()
    
    return bedrooms, has_bikes


def parse_bathrooms(value) -> Decimal:
    """Parse bathrooms field."""
    if pd.isna(value):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except:
        return Decimal("0")


def parse_housekeeper(value: str) -> tuple[str, str]:
    """Parse housekeeper field into name and phone."""
    if pd.isna(value) or str(value) == "nan":
        return None, None
    
    value_str = str(value).strip()
    
    # Try to extract phone number in parentheses
    match = re.search(r'(.+?)\s*\(([^)]+)\)', value_str)
    if match:
        name = match.group(1).strip()
        phone = match.group(2).strip().replace("-", "").replace(" ", "")
        return name, phone
    
    # Try to find phone pattern without parentheses
    phone_match = re.search(r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})', value_str)
    if phone_match:
        phone = phone_match.group(1).replace("-", "").replace(".", "").replace(" ", "")
        name = value_str.replace(phone_match.group(1), "").strip()
        return name or value_str, phone
    
    return value_str, None


def parse_community(value: str) -> str:
    """Parse community to enum value."""
    if pd.isna(value) or str(value) == "nan":
        return "other"
    
    community_map = {
        "watercolor": "watercolor",
        "water color": "watercolor",
        "rosemary beach": "rosemary_beach",
        "rosemary": "rosemary_beach",
        "alys beach": "alys_beach",
        "alys": "alys_beach",
        "seaside": "seaside",
        "grayton beach": "grayton_beach",
        "grayton": "grayton_beach",
        "blue mountain": "blue_mountain",
        "blue mountain beach": "blue_mountain",
        "seagrove": "seagrove",
        "seagrove beach": "seagrove",
        "watersound": "watersound",
        "water sound": "watersound",
        "seacrest": "seacrest",
        "seacrest beach": "seacrest",
        "inlet beach": "inlet_beach",
        "inlet": "inlet_beach",
    }
    
    value_lower = str(value).lower().strip()
    return community_map.get(value_lower, "other")


def safe_str(value) -> str:
    """Convert value to string, handling NaN."""
    if pd.isna(value) or str(value) == "nan":
        return None
    return str(value).strip()


def load_properties(filepath: str, tenant_id: str, dry_run: bool = False):
    """Load properties from Excel file into database."""
    
    print(f"Loading properties from: {filepath}")
    print(f"Tenant ID: {tenant_id}")
    print(f"Database: {DATABASE_URL}")
    print()
    
    # Read Excel file
    df = pd.read_excel(filepath)
    print(f"Found {len(df)} rows in spreadsheet")
    print()
    
    # Parse each row
    properties = []
    errors = []
    
    for idx, row in df.iterrows():
        try:
            unit_code = safe_str(row.get("UNIT CODE"))
            if not unit_code:
                errors.append(f"Row {idx}: Missing UNIT CODE")
                continue
            
            bedrooms, has_bikes = parse_bedrooms(row.get("BEDROOMS"))
            bathrooms = parse_bathrooms(row.get("BATHROOMS"))
            housekeeper_name, housekeeper_phone = parse_housekeeper(row.get("HOUSEKEEPER"))
            community = parse_community(row.get("COMMUNITY"))
            
            # Build property record
            prop = {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "property_code": unit_code,
                "address_street": safe_str(row.get("ADDRESS")) or "Unknown",
                "community": community,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "wifi_network": safe_str(row.get("WIFI NAME")),
                "wifi_password": safe_str(row.get("WIFI PASSWORD")),
                "property_guide_url": safe_str(row.get("PROPERTY GUIDE")),
                "rep_name": safe_str(row.get("REP NAME")),
                "housekeeper_name": housekeeper_name,
                "housekeeper_phone": housekeeper_phone,
                "breaker_box_location": safe_str(row.get("BREAKER BOX LOCATIONS(s)")),
                "has_bikes": has_bikes,
                "bike_count": 0 if not has_bikes else None,
                "general_notes": safe_str(row.get("NOTES")),
                "known_issues": [{"description": safe_str(row.get("KNOWN ISSUES")), "status": "open"}] 
                               if safe_str(row.get("KNOWN ISSUES")) else [],
                "warranty_items": [{"item": safe_str(row.get("PARTS UNDER WARRANTY"))}]
                                 if safe_str(row.get("PARTS UNDER WARRANTY")) else [],
                "data_source": "import",
                "confidence_score": Decimal("0.80"),
                "missing_fields": ["kitchen", "pool", "hvac", "parking", "sleeps"],
            }
            
            properties.append(prop)
            print(f"  ✓ {unit_code}: {bedrooms}BR/{bathrooms}BA in {community}")
            
        except Exception as e:
            errors.append(f"Row {idx} ({row.get('UNIT CODE', 'unknown')}): {e}")
    
    print()
    print(f"Parsed {len(properties)} properties successfully")
    if errors:
        print(f"Errors ({len(errors)}):")
        for err in errors:
            print(f"  ✗ {err}")
    print()
    
    if dry_run:
        print("DRY RUN - not inserting into database")
        return
    
    # Insert into database
    print("Inserting into database...")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Check if properties already exist
        cur.execute(
            "SELECT property_code FROM properties WHERE tenant_id = %s",
            (tenant_id,)
        )
        existing = {row[0] for row in cur.fetchall()}
        
        if existing:
            print(f"Found {len(existing)} existing properties")
        
        inserted = 0
        updated = 0
        
        for prop in properties:
            if prop["property_code"] in existing:
                # Update existing
                cur.execute("""
                    UPDATE properties SET
                        address_street = %(address_street)s,
                        community = %(community)s,
                        bedrooms = %(bedrooms)s,
                        bathrooms = %(bathrooms)s,
                        wifi_network = %(wifi_network)s,
                        wifi_password = %(wifi_password)s,
                        property_guide_url = %(property_guide_url)s,
                        rep_name = %(rep_name)s,
                        housekeeper_name = %(housekeeper_name)s,
                        housekeeper_phone = %(housekeeper_phone)s,
                        breaker_box_location = %(breaker_box_location)s,
                        has_bikes = %(has_bikes)s,
                        bike_count = %(bike_count)s,
                        general_notes = %(general_notes)s,
                        known_issues = %(known_issues)s,
                        warranty_items = %(warranty_items)s,
                        updated_at = NOW()
                    WHERE tenant_id = %(tenant_id)s AND property_code = %(property_code)s
                """, {
                    **prop,
                    "known_issues": Json(prop["known_issues"]),
                    "warranty_items": Json(prop["warranty_items"]),
                })
                updated += 1
            else:
                # Insert new
                cur.execute("""
                    INSERT INTO properties (
                        id, tenant_id, property_code, address_street, community,
                        bedrooms, bathrooms, wifi_network, wifi_password,
                        property_guide_url, rep_name, housekeeper_name, housekeeper_phone,
                        breaker_box_location, has_bikes, bike_count, general_notes,
                        known_issues, warranty_items, data_source, confidence_score,
                        missing_fields
                    ) VALUES (
                        %(id)s, %(tenant_id)s, %(property_code)s, %(address_street)s, %(community)s,
                        %(bedrooms)s, %(bathrooms)s, %(wifi_network)s, %(wifi_password)s,
                        %(property_guide_url)s, %(rep_name)s, %(housekeeper_name)s, %(housekeeper_phone)s,
                        %(breaker_box_location)s, %(has_bikes)s, %(bike_count)s, %(general_notes)s,
                        %(known_issues)s, %(warranty_items)s, %(data_source)s, %(confidence_score)s,
                        %(missing_fields)s
                    )
                """, {
                    **prop,
                    "known_issues": Json(prop["known_issues"]),
                    "warranty_items": Json(prop["warranty_items"]),
                })
                inserted += 1
        
        conn.commit()
        print()
        print(f"✅ Inserted: {inserted}")
        print(f"✅ Updated: {updated}")
        print(f"✅ Total: {len(properties)}")
        
        # Link to concierge_knowledge
        print()
        print("Linking to concierge_knowledge...")
        
        cur.execute("""
            UPDATE concierge_knowledge ck
            SET canonical_property_id = p.id
            FROM properties p
            WHERE ck.tenant_id = p.tenant_id
              AND ck.property_external_id = p.property_code
              AND ck.canonical_property_id IS NULL
        """)
        linked = cur.rowcount
        conn.commit()
        print(f"✅ Linked {linked} concierge_knowledge records to properties")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Database error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Load properties from UNIT INFO.xlsx")
    parser.add_argument(
        "--file", "-f",
        default="UNIT INFO.xlsx",
        help="Path to Excel file (default: UNIT INFO.xlsx)"
    )
    parser.add_argument(
        "--tenant", "-t",
        default=DEFAULT_TENANT_ID,
        help=f"Tenant UUID (default: {DEFAULT_TENANT_ID})"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Parse only, don't insert into database"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        sys.exit(1)
    
    load_properties(args.file, args.tenant, args.dry_run)


if __name__ == "__main__":
    main()
