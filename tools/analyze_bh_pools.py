#!/usr/bin/env python3
"""Quick analysis of scraped Beach Habitats data."""

import json

with open('/Users/dhuntermckenzie/Downloads/STR-Beach_Habitats/scraped_properties.json') as f:
    data = json.load(f)

print(f"Total Beach Habitats properties: {len(data)}")
print()

# Pool type distribution
pool_types = {}
for p in data:
    pt = p.get('pool_type') or 'none'
    pool_types[pt] = pool_types.get(pt, 0) + 1

print("Pool types:")
for pt, count in sorted(pool_types.items(), key=lambda x: -x[1]):
    pct = count / len(data) * 100
    print(f"  {pt}: {count} ({pct:.0f}%)")

print()

# Properties with private pools
private_pools = [p for p in data if p.get('pool_type') == 'private']
print(f"Properties with PRIVATE pools ({len(private_pools)}):")
for p in private_pools[:10]:
    print(f"  - {p['name']}: {p.get('bedrooms')}BR")

print()

# Properties with shared/community pools
shared_pools = [p for p in data if p.get('pool_type') in ('shared', 'community', 'communal')]
print(f"Properties with SHARED/COMMUNITY pools ({len(shared_pools)}):")
for p in shared_pools[:5]:
    print(f"  - {p['name']}: {p.get('bedrooms')}BR")

print()

# WaterColor access
wc_access = [p for p in data if p.get('has_watercolor_access')]
print(f"Properties with WaterColor amenity access: {len(wc_access)}")

# Wristband counts
wristbands = [p for p in data if p.get('wristband_count')]
print(f"Properties with wristband counts: {len(wristbands)}")
if wristbands:
    print(f"  Wristband range: {min(p['wristband_count'] for p in wristbands)} - {max(p['wristband_count'] for p in wristbands)}")
