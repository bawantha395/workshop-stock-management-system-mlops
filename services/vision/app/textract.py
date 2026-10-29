"""Fallback for AI label suggestions: read the printed text with Amazon Textract.

Used only when Bedrock is unavailable (for example, an account quota of zero). Textract
returns the text it can read; simple rules then pick out the catalogue fields. This is
best effort: every field is a suggestion, unreadable fields are left out, and a person
reviews the draft before anything is saved. The label text is treated as data, never as
instructions.
"""
import logging
import re

import boto3
from botocore.config import Config

SOURCE = 'textract'
LIMITS = {'name': 180, 'brand': 100, 'category': 80, 'grade': 80, 'capacity': 60, 'partNumber': 180}
MIN_CONFIDENCE = 70

BRANDS = ['Mobil', 'Castrol', 'Shell', 'Valvoline', 'Total', 'TotalEnergies', 'Caltex', 'Havoline', 'Petronas', 'Gulf',
          'Motul', 'Liqui Moly', 'Repsol', 'Elf', 'Amsoil', 'Toyota', 'Mitsubishi', 'Nissan', 'Honda', 'Suzuki',
          'Bosch', 'Denso', 'NGK', 'Mann', 'Mahle', 'Sakura', 'Fram', 'K&N', 'Ryco', 'Wesfil', 'Hella', 'Valeo',
          'Brembo', 'Akebono', 'TRW', 'Gates', 'Continental', 'Exide', 'Amaron', 'Yuasa', 'Philips', 'Osram']
CATEGORIES = [
    (r'\b(engine|motor|gear|transmission)\s+oil\b|\bsynthetic\b|\bSAE\b|\bATF\b|\blubricant\b', 'Engine oil'),
    (r'\bfilters?\b', 'Filters'),
    (r'\bbrake\b|\bpads?\b', 'Brakes'),
    (r'\bspark\s*plugs?\b', 'Spark plugs'),
    (r'\bcoolant\b|\banti-?freeze\b', 'Coolant'),
    (r'\bgrease\b', 'Grease'),
    (r'\bbatter(y|ies)\b', 'Batteries'),
    (r'\bwipers?\b', 'Wipers'),
    (r'\bbelts?\b', 'Belts'),
]
NAME_WORDS = re.compile(r'\b(oil|filter|brake|plug|coolant|grease|battery|wiper|belt|fluid|pads?)\b', re.I)
PART_KEYS = re.compile(r'\b(P/?N|PART\s*(NO|NUMBER|#)?|REF|MODEL|ITEM|CAT(ALOG)?|SKU|CODE)\b[:#.\s-]*', re.I)
GRADE = re.compile(r'\b(\d{1,2})W[- ]?(\d{2})\b', re.I)
CAPACITY = re.compile(r'\b(\d{1,4}(?:[.,]\d{1,3})?)\s?(LITRES?|LITERS?|LTR|ML|KG|L|G)\b', re.I)
TOKEN = re.compile(r'^[A-Z0-9][A-Z0-9./-]{3,23}[A-Z0-9]$')
UNITS = {'L': 'L', 'LTR': 'L', 'LITRE': 'L', 'LITRES': 'L', 'LITER': 'L', 'LITERS': 'L', 'ML': 'ml', 'KG': 'kg', 'G': 'g'}


def read_lines(settings, image):
    """Return the text lines Textract reads with reasonable confidence."""
    region = getattr(settings, 'textract_region', '') or settings.aws_region
    client = boto3.client('textract', region_name=region, config=Config(
        connect_timeout=5, read_timeout=30, retries={'total_max_attempts': 1}))
    blocks = client.detect_document_text(Document={'Bytes': image}).get('Blocks', [])
    return [b['Text'].strip() for b in blocks
            if b.get('BlockType') == 'LINE' and b.get('Text', '').strip() and b.get('Confidence', 0) >= MIN_CONFIDENCE]


def _grade(text):
    match = GRADE.search(text)
    return f'{match.group(1)}W-{match.group(2)}'.upper() if match else ''


def _capacity(text):
    for match in CAPACITY.finditer(GRADE.sub(' ', text)):
        number = match.group(1).replace(',', '.')
        return number + UNITS[match.group(2).upper()]
    return ''


def _part_number(lines, grade):
    def valid(token):
        token = token.strip(':,;()[]"\'').upper()
        if not TOKEN.match(token) or not re.search(r'\d', token) or not re.search(r'[A-Z]', token):
            return ''
        if GRADE.fullmatch(token) or token == grade or CAPACITY.fullmatch(token):
            return ''
        if re.fullmatch(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', token):
            return ''
        return token
    for line in lines:  # explicit "P/N: ..." style labels first; these may be digits only
        key = PART_KEYS.search(line)
        if key:
            for token in line[key.end():].split():
                token = token.strip(':,;()[]"\'').upper()
                if valid(token) or re.fullmatch(r'\d{4,12}', token):
                    return token
    for line in lines:
        for token in line.split():
            if valid(token):
                return valid(token)
    return ''


def _brand(text):
    for brand in BRANDS:
        if re.search(r'(?<![A-Za-z])' + re.escape(brand) + r'(?![A-Za-z])', text, re.I):
            return brand
    return ''


def _category(text):
    for pattern, name in CATEGORIES:
        if re.search(pattern, text, re.I):
            return name
    return ''


def _name(lines, brand, part, grade, capacity):
    plain = [part, grade, capacity]
    candidates = []
    for line in lines:
        letters = re.findall(r'[A-Za-z]{3,}', line)
        if len(letters) < 1 or not 6 <= len(line) <= 80:
            continue
        rest = line
        for token in plain + [brand]:
            if token:
                rest = re.sub(re.escape(token), '', rest, flags=re.I)
        if len(re.findall(r'[A-Za-z]{3,}', rest)) < 1 or PART_KEYS.fullmatch(line.strip()):
            continue
        candidates.append(line)
    if not candidates:
        return ''
    best = next((line for line in candidates if NAME_WORDS.search(line)), candidates[0])
    best = best.title() if best.isupper() else best
    if brand and brand.lower() not in best.lower():
        best = f'{brand} {best}'
    return best


def parse_lines(lines):
    """Turn label text into catalogue fields. Fields that cannot be found are omitted."""
    text = ' '.join(lines)
    grade, capacity = _grade(text), _capacity(text)
    brand = _brand(text)
    part = _part_number(lines, grade)
    fields = {'name': _name(lines, brand, part, grade, capacity), 'brand': brand, 'partNumber': part,
              'category': _category(text), 'grade': grade, 'capacity': capacity}
    return {key: value[:LIMITS[key]].strip() for key, value in fields.items() if value and value.strip()}


def propose(settings, image):
    """Read the label with Textract; returns the suggested fields (possibly empty)."""
    lines = read_lines(settings, image)
    fields = parse_lines(lines)
    logging.getLogger(__name__).info('Textract label fallback lines=%d fields=%s', len(lines), sorted(fields))
    return fields
