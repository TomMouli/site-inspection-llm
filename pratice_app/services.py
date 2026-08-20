import json
import os
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib import request as urlrequest

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ExtractionError(ValueError):
    pass


class ParsedSite(BaseModel):
    model_config = ConfigDict(extra='forbid')

    client_name: str = ''
    address: str = ''
    equipment_notes: str = ''
    estimated_budget: float | None = None

    @field_validator('client_name', 'address', 'equipment_notes', mode='before')
    @classmethod
    def strings_only(cls, value):
        if value is None:
            return ''
        if not isinstance(value, str):
            raise ValueError('must be a string')
        return value.strip()

    @field_validator('estimated_budget', mode='before')
    @classmethod
    def budget_number(cls, value):
        if value in ('', None):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('must be a number')
        return value

    def to_public_dict(self):
        return self.model_dump()


@dataclass
class SiteData:
    client_name: str = ''
    site_name: str = ''
    address: str = ''
    equipment: list[str] | None = None
    estimated_budget: str = ''
    follow_up_date: str = ''
    priority: str = 'Normal'
    notes: str = ''

    def __post_init__(self):
        if self.equipment is None:
            self.equipment = []
        if not isinstance(self.equipment, list):
            raise ValueError('Equipment must be an array of strings.')
        self.equipment = [str(item).strip() for item in self.equipment if str(item).strip()]
        self.client_name = str(self.client_name or '').strip()
        self.site_name = str(self.site_name or '').strip()
        self.address = str(self.address or '').strip()
        self.estimated_budget = str(self.estimated_budget or '').strip()
        self.follow_up_date = str(self.follow_up_date or '').strip()
        self.notes = str(self.notes or '').strip()
        self.priority = self.priority.title()
        if self.priority not in {'Low', 'Normal', 'High', 'Urgent'}:
            raise ValueError('Priority must be Low, Normal, High, or Urgent.')

    def missing_fields(self):
        return [field for field, value in (('Client name', self.client_name), ('Address', self.address)) if not value]

    def validate_for_save(self):
        missing = self.missing_fields()
        if missing:
            raise ValueError(f'{" and ".join(missing)} required.')
        if self.estimated_budget and parse_budget(self.estimated_budget) is None:
            raise ValueError('Budget must be a valid number, for example 250000 or 2.5 lakhs.')
        return self

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('Site data must be a JSON object.')
        allowed = {'client_name', 'site_name', 'address', 'equipment', 'estimated_budget', 'follow_up_date', 'priority', 'notes'}
        unexpected = set(data) - allowed
        if unexpected:
            raise ValueError(f'Unexpected field(s): {", ".join(sorted(unexpected))}.')
        return cls(**{key: data.get(key, '') for key in allowed})

    def to_dict(self):
        return asdict(self)

    def to_public_schema(self):
        budget = parse_budget(self.estimated_budget)
        parsed = ParsedSite(
            client_name=self.client_name,
            address=self.address,
            equipment_notes='; '.join(self.equipment),
            estimated_budget=float(budget) if budget is not None else None,
        )
        return parsed.to_public_dict()


def _value(pattern, text, default=''):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip(' .') if match else default


def parse_budget(value):
    if not value:
        return None
    cleaned = str(value).lower().replace(',', '').replace('$', '').strip()
    multiplier = 1
    if re.search(r'\b(?:lakh|lakhs)\b', cleaned):
        multiplier = 100000
    elif re.search(r'\bk\b', cleaned):
        multiplier = 1000
    cleaned = re.sub(r'\s*(?:lakh|lakhs|k)\b', '', cleaned).strip()
    try:
        return Decimal(cleaned) * multiplier
    except InvalidOperation:
        return None


def _normalise_budget(value):
    amount = parse_budget(value)
    if amount is None:
        return str(value).strip() if value else ''
    return f'${amount:,.0f}' if amount == amount.to_integral() else f'${amount:,.2f}'


def _local_extract(text):
    equipment_text = _value(r'(?:equipment|assets?|systems?)\s*[:\-]?\s*(.+?)(?=\s*(?:location|address|budget|client|customer)\s*[:\-]|$)', text)
    if equipment_text and re.match(r'^\s*[,;]?\s*(?:location|address|budget|client|customer)\b', equipment_text, re.I):
        equipment_text = ''
    if not equipment_text:
        equipment_text = _value(r'(?:has|have|contains|includes)\s+(.+?)(?:\.|$)', text)
    if not equipment_text:
        equipment_text = _value(r'\b((?:old|new|broken|aging|working)\s+equipment)\b', text)
    equipment = [item.strip() for item in re.split(r',|\band\b|\n', equipment_text) if item.strip()] if equipment_text else []
    budget = _value(r'(?:estimated\s+budget|budget)\s*(?:is|around|:)??\s*(\$?\s?[\d,.]+\s*(?:lakh|lakhs|k)?)', text)
    client = _value(r'(?:client(?:\s+name)?|customer)\s*[:\-]\s*(.+?)(?=\s*(?:budget|address|equipment|location|site)\s*[:\-]|$)', text)
    if not client:
        client = _value(r"(?:i\s+am|i'm|my\s+name\s+is)\s+([^.,\n]+)", text)
    if not client:
        client = _value(r'for\s+(.+?)(?:\.|\n|\s+address\s*:)', text)
    if not client:
        client = _value(r'visited\s+(.+?)(?=\s+(?:yesterday|today)|,|$)', text)
    address = _value(r'(?:address|location)\s*[:\-]?\s*(.+?)(?=[,\s]*(?:budget|equipment|client|customer)\b|\.\s*(?:the|client|estimated|please)\b|$)', text)
    site_name = _value(r'(?:site|facility)\s*(?:name)?\s*[:\-]\s*(.+?)(?=\s*(?:address|budget|equipment)\s*:|$)', text)
    if not site_name:
        site_name = _value(r'(?:visited|inspected|at)\s+(?:the\s+)?(.+?)\s+for\s+', text)
    follow_up = _value(r'(?:follow[- ]?up|schedule).*?(?:before|on)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})', text)
    priority = 'Urgent' if re.search(r'urgent|critical|emergency', text, re.I) else 'High' if re.search(r'fault|failure|hazard', text, re.I) else 'Normal'
    if not client:
        client = _value(r'(?:client|customer)\s*:\s*(.+)', text)
    return SiteData(client, site_name, address, equipment, _normalise_budget(budget), follow_up, priority, text)


def _llm_extract(text, api_key):
    schema = {'client_name': 'string', 'address': 'string', 'equipment_notes': 'string', 'estimated_budget': 'number or null'}
    prompt = ('Extract the inspection notes into exactly this JSON object and no other keys: ' + json.dumps(schema) +
              '. client_name, address, and equipment_notes must be strings. estimated_budget must be a number in INR or null. '
              'Convert lakh/lakhs to rupees. Use empty strings or null when unknown. '
              'Respond with raw JSON only: no Markdown, no code fences, no explanation, and never add extra keys. Notes:\n' + text)
    payload = json.dumps({'model': getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'), 'temperature': 0, 'messages': [
        {'role': 'system', 'content': 'You extract structured site inspection data.'},
        {'role': 'user', 'content': prompt},
    ], 'response_format': {'type': 'json_object'}}).encode()
    req = urlrequest.Request('https://api.openai.com/v1/chat/completions', data=payload, headers={
        'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ExtractionError('The LLM API key is invalid. Check your .env file.') from exc
        if exc.code == 429:
            raise ExtractionError('The LLM rate limit was reached. Please try again shortly.') from exc
        raise ExtractionError('The LLM service returned an error. Please try again.') from exc
    except TimeoutError as exc:
        raise ExtractionError('The LLM request timed out. Please try again.') from exc
    except URLError as exc:
        raise ExtractionError('Could not reach the LLM service. Check your network and try again.') from exc
    except json.JSONDecodeError as exc:
        raise ExtractionError('The LLM service returned an invalid response. Please try again.') from exc
    try:
        content = result['choices'][0]['message']['content'].strip()
        public_data = ParsedSite.model_validate(json.loads(content))
        equipment = [item.strip() for item in re.split(r',|\band\b|;', public_data.equipment_notes) if item.strip()]
        budget = _normalise_budget(public_data.estimated_budget)
        return SiteData(public_data.client_name, '', public_data.address, equipment, budget, '', 'Normal', text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ExtractionError('The LLM returned an invalid JSON response. Please try again.') from exc


def extract_site_data(text):
    if not text or not text.strip():
        raise ExtractionError('Please enter site inspection notes.')
    if len(text) > 5000:
        raise ExtractionError('Inspection notes must be 5000 characters or less.')
    try:
        api_key = getattr(settings, 'OPENAI_API_KEY', '') or os.getenv('OPENAI_API_KEY', '')
        site = _llm_extract(text, api_key) if api_key else _local_extract(text)
        if not any((site.client_name, site.address, site.equipment, site.estimated_budget, site.site_name)):
            raise ExtractionError('Could not find site details in these notes. Add a client, address, equipment, or budget.')
        return site
    except Exception as exc:
        if isinstance(exc, ExtractionError):
            raise
        if isinstance(exc, ValueError):
            raise ExtractionError(f'Could not validate extracted data: {exc}') from exc
        raise ExtractionError(f'Extraction failed: {exc}') from exc