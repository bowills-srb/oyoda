"""
Guest Q&A Extractor.

Extracts historical guest questions and answers from CSV/Excel uploads.
This is REFERENCE data for context and phrase tuning, not automation.

IMPORTANT: This does NOT enable auto-reply.
It provides:
- Context for concierge
- Phrase tuning
- Pattern recognition
- Operator review data
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import (
    DocumentExtractor, DocumentType, ExtractionResult,
    ExtractedField, FieldConfidence
)


class GuestQAExtractor(DocumentExtractor):
    """
    Extract guest Q&A history from structured data.
    
    Target fields:
    - guest_qa_records: Individual Q&A pairs
    - qa_categories: Frequency by category
    - common_questions: Most frequent question patterns
    """
    
    document_type = DocumentType.MISC
    
    # Column name patterns
    QUESTION_COLUMNS = ['question', 'query', 'message', 'guest_message', 'inquiry', 'q']
    ANSWER_COLUMNS = ['answer', 'response', 'reply', 'host_response', 'a']
    CATEGORY_COLUMNS = ['category', 'type', 'topic', 'tag']
    DATE_COLUMNS = ['date', 'created', 'timestamp', 'sent_at', 'created_at']
    
    # Auto-categorization keywords
    CATEGORY_PATTERNS = {
        'wifi': ['wifi', 'wi-fi', 'internet', 'password', 'network'],
        'check_in': ['check-in', 'checkin', 'check in', 'arrival', 'key', 'access', 'lock', 'code'],
        'check_out': ['check-out', 'checkout', 'check out', 'departure', 'leaving'],
        'late_checkout': ['late checkout', 'late check-out', 'extend', 'stay longer'],
        'amenities': ['pool', 'hot tub', 'grill', 'bbq', 'beach', 'kayak', 'bike', 'golf cart'],
        'parking': ['parking', 'garage', 'car', 'driveway'],
        'directions': ['direction', 'address', 'location', 'find', 'where', 'get there'],
        'local_info': ['restaurant', 'beach', 'store', 'grocery', 'near', 'recommend'],
        'maintenance': ['broken', 'fix', 'repair', 'not working', 'issue', 'problem'],
        'noise': ['noise', 'loud', 'quiet', 'neighbor'],
        'pets': ['pet', 'dog', 'cat', 'animal'],
        'booking': ['book', 'reservation', 'cancel', 'refund', 'change date'],
    }
    
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """Extract guest Q&A from text or structured data."""
        fields = []
        errors = []
        warnings = []
        
        # Get structured rows
        rows = metadata.get('structured_rows') if metadata else None
        
        if not rows:
            # Try to parse text as CSV
            rows = self._parse_csv_text(text)
        
        if not rows:
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                errors=["Could not parse Q&A data - no structured rows found"],
            )
        
        # Identify columns
        columns = self._identify_columns(rows)
        
        if not columns.get('question'):
            warnings.append("Could not identify question column")
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                warnings=warnings,
            )
        
        # Extract Q&A records
        qa_records = []
        category_counts = {}
        
        for row in rows:
            record = self._extract_row(row, columns)
            if record:
                qa_records.append(record)
                
                # Count categories
                cat = record.get('category', 'uncategorized')
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if not qa_records:
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                warnings=["No valid Q&A records extracted"],
            )
        
        # Individual Q&A records
        for record in qa_records[:100]:  # Limit to 100 for evidence
            fields.append(self._extract_field(
                name="guest_qa_record",
                value=record,
                confidence=FieldConfidence.HIGH if record.get('answer') else FieldConfidence.MEDIUM,
            ))
        
        # Category summary
        fields.append(self._extract_field(
            name="qa_categories",
            value={
                "counts": category_counts,
                "total_records": len(qa_records),
                "with_answers": sum(1 for r in qa_records if r.get('answer')),
            },
            confidence=FieldConfidence.HIGH,
        ))
        
        # Common question patterns
        common = self._find_common_patterns(qa_records)
        if common:
            fields.append(self._extract_field(
                name="common_questions",
                value=common,
                confidence=FieldConfidence.MEDIUM,
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
        
        columns = list(rows[0].keys())
        columns_lower = {c: c.lower().strip() for c in columns}
        
        result = {}
        
        # Find question column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.QUESTION_COLUMNS):
                result['question'] = col
                break
        
        # Find answer column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.ANSWER_COLUMNS):
                result['answer'] = col
                break
        
        # Find category column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.CATEGORY_COLUMNS):
                result['category'] = col
                break
        
        # Find date column
        for col, col_lower in columns_lower.items():
            if any(pattern in col_lower for pattern in self.DATE_COLUMNS):
                result['date'] = col
                break
        
        return result
    
    def _extract_row(
        self, 
        row: Dict, 
        columns: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Extract a single Q&A record from a row."""
        try:
            record = {}
            
            # Extract question (required)
            if columns.get('question'):
                question = row.get(columns['question'])
                if question and str(question).strip():
                    record['question'] = str(question).strip()
                else:
                    return None
            else:
                return None
            
            # Extract answer (optional)
            if columns.get('answer'):
                answer = row.get(columns['answer'])
                if answer and str(answer).strip():
                    record['answer'] = str(answer).strip()
            
            # Extract or infer category
            if columns.get('category'):
                record['category'] = str(row.get(columns['category'], '')).strip().lower()
            
            if not record.get('category'):
                record['category'] = self._auto_categorize(record['question'])
            
            # Extract date
            if columns.get('date'):
                date_val = row.get(columns['date'])
                if date_val:
                    record['date'] = str(date_val)
            
            return record
            
        except Exception:
            return None
    
    def _auto_categorize(self, question: str) -> str:
        """Auto-categorize a question based on keywords."""
        question_lower = question.lower()
        
        for category, keywords in self.CATEGORY_PATTERNS.items():
            if any(kw in question_lower for kw in keywords):
                return category
        
        return 'general'
    
    def _find_common_patterns(self, records: List[Dict]) -> List[Dict]:
        """Find common question patterns."""
        # Group by category
        by_category = {}
        for record in records:
            cat = record.get('category', 'general')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(record.get('question', ''))
        
        # Get top categories with example questions
        common = []
        for cat, questions in sorted(by_category.items(), key=lambda x: -len(x[1])):
            if len(questions) >= 2:
                common.append({
                    'category': cat,
                    'count': len(questions),
                    'examples': questions[:3],  # First 3 examples
                })
        
        return common[:10]  # Top 10 categories
