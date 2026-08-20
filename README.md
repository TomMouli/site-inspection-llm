# Fieldnote

Fieldnote turns messy site inspection notes into a validated, editable site card. It accepts voice-memo transcripts, emails, and raw text logs.

## Run locally

```powershell
..\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
..\Scripts\python.exe manage.py migrate
..\Scripts\python.exe manage.py runserver
```

Add an OpenAI key to `.env` for LLM extraction. Without a key, the deterministic local parser keeps the app usable for development and demos. Never commit `.env`.

## Extraction contract

The LLM must return exactly this JSON object. Unknown values are empty strings and `equipment` is always an array:

```json
{
  "client_name": "ABC Industries",
  "site_name": "",
  "address": "Chennai",
  "equipment": ["old equipment"],
  "estimated_budget": "$250,000",
  "follow_up_date": "",
  "priority": "Normal",
  "notes": "Original inspection notes"
}
```

The server validates the JSON shape and priority. Extraction can show incomplete fields so missing address, equipment, or budget does not crash the page. Saving requires client name and address; if a budget is supplied, it must be numeric and supports values such as `250000`, `$250,000`, `2.5 lakh`, and `2.5 lakhs`.

## REST API

`POST /api/parse-site/` accepts:

```json
{"text": "ABC Industries visited their site at 24 Mount Road, Chennai. Budget around 2.5 lakhs."}
```

It returns the strict assessment schema:

```json
{
  "client_name": "ABC Industries",
  "address": "24 Mount Road, Chennai",
  "equipment_notes": "",
  "estimated_budget": 250000.0
}
```

The browser dashboard uses the same extraction and validation service, then renders the richer editable site card. API failures and invalid LLM JSON return a JSON `error` response with HTTP 400 instead of an application crash.

## Example input

```text
Client: ABC IndustriesBudget: 2.5 lakhAddress: Chennai
```

```text
visited abc industries yesterday, old equipment,location chennai, budget around 250000
```

Both formats are handled by the local fallback parser. LLM failures, invalid JSON, timeouts, invalid keys, rate limits, and network errors are converted into readable UI errors.

## Tests

```powershell
..\Scripts\python.exe manage.py check
..\Scripts\python.exe manage.py test
```
