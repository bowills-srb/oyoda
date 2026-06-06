#!/usr/bin/env python3
"""Check actual database schema for properties table."""

import psycopg2

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("=" * 70)
print("DATABASE SCHEMA CHECK")
print("=" * 70)

# List all tables
print("\n📋 Tables in database:")
cur.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
""")
for row in cur.fetchall():
    print(f"   {row[0]}")

# Check properties table schema
print("\n📊 'properties' table columns:")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'properties' 
    ORDER BY ordinal_position
""")
rows = cur.fetchall()
if rows:
    for col_name, data_type, nullable in rows:
        print(f"   {col_name:<30} {data_type:<20} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
else:
    print("   (table does not exist)")

# Check property_availability schema
print("\n📊 'property_availability' table columns:")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'property_availability' 
    ORDER BY ordinal_position
""")
rows = cur.fetchall()
if rows:
    for col_name, data_type, nullable in rows:
        print(f"   {col_name:<30} {data_type:<20} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
else:
    print("   (table does not exist)")

# Check property_bookings schema
print("\n📊 'property_bookings' table columns:")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'property_bookings' 
    ORDER BY ordinal_position
""")
rows = cur.fetchall()
if rows:
    for col_name, data_type, nullable in rows:
        print(f"   {col_name:<30} {data_type:<20} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
else:
    print("   (table does not exist)")

# Sample data from properties
print("\n📝 Sample property data:")
cur.execute("SELECT * FROM properties LIMIT 1")
if cur.description:
    cols = [desc[0] for desc in cur.description]
    row = cur.fetchone()
    if row:
        for col, val in zip(cols, row):
            print(f"   {col}: {val}")
    else:
        print("   (no data)")
else:
    print("   (table does not exist)")

cur.close()
conn.close()
