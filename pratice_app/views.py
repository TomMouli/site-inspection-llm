import json

from django.http import JsonResponse
from django.shortcuts import render

from .services import ExtractionError, extract_site_data


SAMPLE_NOTES = """Visited the Riverside Community Center for Maya Patel.
Address: 42 Harbor Street, Portland, OR 97205.
The rooftop has 18 aging solar panels and one inverter showing a red fault light.
Client is considering a replacement and battery storage. Estimated budget is $24,000.
Please schedule a follow-up before October 15, 2026."""


def dashboard(request):
	source_text = request.POST.get('notes', '').strip() if request.method == 'POST' else SAMPLE_NOTES
	context = {'source_text': source_text, 'site_data': None, 'site_json': 'null', 'missing_fields': [], 'error': None}
	if request.method == 'POST':
		try:
			context['site_data'] = extract_site_data(source_text)
			context['site_json'] = json.dumps(context['site_data'].to_dict())
			context['missing_fields'] = context['site_data'].missing_fields()
		except ExtractionError as exc:
			context['error'] = str(exc)
	return render(request, 'dashboard.html', context)


def parse_site(request):
	if request.method != 'POST':
		return JsonResponse({'error': 'POST required.'}, status=405)
	try:
		payload = json.loads(request.body)
		if not isinstance(payload, dict) or not isinstance(payload.get('text'), str):
			raise ValueError('Request body must contain a text string.')
		return JsonResponse(extract_site_data(payload['text']).to_public_schema())
	except (json.JSONDecodeError, ValueError, TypeError) as exc:
		return JsonResponse({'error': str(exc)}, status=400)


def save_site(request):
	if request.method != 'POST':
		return JsonResponse({'error': 'POST required.'}, status=405)
	try:
		from .services import SiteData
		site = SiteData.from_dict(json.loads(request.body)).validate_for_save()
	except (json.JSONDecodeError, ValueError, TypeError) as exc:
		return JsonResponse({'error': str(exc)}, status=400)
	return JsonResponse({'ok': True, 'site': site.to_dict()})

