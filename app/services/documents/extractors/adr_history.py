"""
ADR History Extractor.

Extracts historical ADR (Average Daily Rate) data from CSV/Excel uploads.
Does NOT aggregate - lets analytics do that later.

IMPORTANT: Each row becomes its own PropertyEvidence.
This preserves granularity for trend analysis.
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .base import (
    DocumentExtractor, DocumentType, ExtractionResult,
    ExtractedField, FieldConfidence
)


class AdrHistoryExtractor(DocumentExtractor):
    """
    Extract ADR history from structured data.
    
    Target fields:
    - historical_adr: Individual date/rate records
    - adr_summary: Basic aggregations (for quick reference)
    
    Expected input formats:
    - CSV: date,adr,occupied (or similar)
    - Excel: Same structure
    - JSON: Array of {date, adr, occupied}
    """
    
    document_type = DocumentType.RENT_ROLL  # Reuse type
    
    # Common column name patterns
    DATE_COLUMNS = ['date', 'day', 'night', 'check_in', 'checkin', 'reservation_date']
    ADR_COLUMNS = ['adr', 'rate', 'daily_rate', 'nightly_rate', 'price', 'amount']
    OCCUPIED_COLUMNS = ['occupied', 'booked', 'rented', 'status', 'is_occupied']
    REVENUE_COLUMNS = ['revenue', 'income', 'total', 'gross']
    
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """
        Extract ADR history from text or structured data.
        
        If metadata contains 'structured_rows', uses that directly.
        Otherwise, attempts to parse text as CSV.
        """
        fields = []
        errors = []
        warnings = []
        
        # Get structured rows if available
        rows = metadata.get('structured_rows') if metadata else None
        
        if not rows:
            # Try to parse text as CSV
            rows = self._parse_csv_text(text)
        
        if not rows:
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                errors=["Could not parse ADR data - no structured rows found"],
            )
        
        # Identify columns
        columns = self._identify_columns(rows)
        
        if not columns.get('date') or not columns.get('adr'):
            warnings.append("Could not identify date and ADR columns")
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                warnings=warnings,
            )
        
        # Extract each row as a field
        adr_records = []
        total_revenue = 0.0
        occupied_days = 0
        
        for row in rows:
            record = self._extract_row(row, columns)
            if record:
                adr_records.append(record)
                
                # Track aggregates
                if record.get('occupied', False):
                    occupied_days += 1
                    if record.get('adr'):
                        total_revenue += record['adr']
        
        if not adr_records:
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                warnings=["No valid ADR records extracted"],
            )
        
        # Create individual fields for each record
        # (This preserves granularity for trend analysis)
        for record in adr_records:
            fields.append(self._extract_field(
                name="historical_adr",
                value=record,
                confidence=FieldConfidence.HIGH if record.get('adr') else FieldConfidence.MEDIUM,
                source_text=f"Date: {record.get('date')}",
            ))
        
        # Create summary field (for quick reference)
        if adr_records:
            adrs = [r['adr'] for r in adr_records if r.get('adr')]
            
            fields.append(self._extract_field(
                name="adr_summary",
                value={
                    "total_records": len(adr_records),
                    "occupied_days": occupied_days,
                    "total_revenue": round(total_revenue, 2),
                    "avg_adr": round(sum(adrs) / len(adrs), 2) if adrs else 0,
                    "min_adr": min(adrs) if adrs else 0,
                    "max_adr": max(adrs) if adrs else 0,
                    "date_range": {
                        "start": min(r['date'] for r in adr_records if r.get('date')),
                        "end": max(r['date'] for r in adr_records if r.get('date')),
                    } if adr_records else None,
                },
                confidence=FieldConfidence.HIGH,
            ))
        
        return ExtractionResult(
            document_type=self.document_type,
            fields=fields,
            errors=errors,
            warnings=warnings,
        )
    
    def _parse_csv_text(self, text: str) -> Optional[List[Dict]]:
        """Attempt to parse text as CSV."""
        import csv
        from io import StringIO
        
        try:
            reader = csv.DictReader(StringIO(text))
            return list(reader)
        except:
            return None
    
    def _identify_columns(self, rows: List[Dict]) -> Dict[str, str]:
        """Identify which columns contain which data."""
        if not rows:
            return {}
        
        # Get all column names from first row
        columns = list(rows[0].keys())
        columns_lower = {c: c.lower().strip() for c in columns}
        
        result = {}
        
        # Find date column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.DATE_COLUMNS):
                result['date'] = col
                break
        
        # Find ADR column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.ADR_COLUMNS):
                result['adr'] = col
                break
        
        # Find occupied column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.OCCUPIED_COLUMNS):
                result['occupied'] = col
                break
        
        # Find revenue column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.REVENUE_COLUMNS):
                result['revenue'] = col
                break
        
        return result
    
    def _extract_row(
        self, 
        row: Dict, 
        columns: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Extract a single ADR record from a row."""
        try:
            record = {}
            
            # Extract date
            if columns.get('date'):
                date_val = row.get(columns['date'])
                if date_val:
                    record['date'] = self._parse_date(date_val)
            
            # Extract ADR
            if columns.get('adr'):
                adr_val = row.get(columns['adr'])
                if adr_val:
                    record['adr'] = self._parse_number(adr_val)
            
            # Extract occupied status
            if columns.get('occupied'):
                occ_val = row.get(columns['occupied'])
                record['occupied'] = self._parse_bool(occ_val)
            elif record.get('adr') and record['adr'] > 0:
                # Infer occupied if ADR > 0
                record['occupied'] = True
            
            # Extract revenue if available
            if columns.get('revenue'):
                rev_val = row.get(columns['revenue'])
                if rev_val:
                    record['revenue'] = self._parse_number(rev_val)
            
            # Only return if we have at least date and ADR
            if record.get('date') and (record.get('adr') is not None):
                return record
            
            return None
            
        except Exception as e:
            return None
    
    def _parse_date(self, value: Any) -> Optional[str]:
        """Parse date value to ISO string."""
        if isinstance(value, (date, datetime)):
            return value.isoformat()[:10]
        
        if isinstance(value, str):
            # Try common formats
            formats = [
                '%Y-%m-%d',
                '%m/%d/%Y',
                '%m-%d-%Y',
                '%d/%m/%Y',
                '%Y/%m/%d',
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(value.strip(), fmt).date().isoformat()
                except:
                    continue
        
        return str(value) if value else None
    
    def _parse_number(self, value: Any) -> Optional[float]:
        """Parse number value."""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Remove currency symbols and commas
            cleaned = re.sub(r'[$,]', '', value.strip())
            try:
                return float(cleaned)
            except:
                pass
        
        return None
    
    def _parse_bool(self, value: Any) -> bool:
        """Parse boolean value."""
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            return value.lower().strip() in ('true', 'yes', '1', 'occupied', 'booked')
        
        if isinstance(value, (int, float)):
            return value > 0
        
        return False
