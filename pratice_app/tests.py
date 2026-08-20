import json
from unittest.mock import patch
from urllib.error import HTTPError

from django.test import TestCase, override_settings

from .services import ExtractionError, ParsedSite, SiteData, extract_site_data


NOTES = """Visited the Riverside Community Center for Maya Patel.
Address: 42 Harbor Street, Portland, OR 97205.
The rooftop has 18 aging solar panels and one inverter showing a red fault light.
Estimated budget is $24,000. Please schedule a follow-up before October 15, 2026."""


class SiteExtractionTests(TestCase):
	def test_local_extractor_returns_valid_schema(self):
		site = extract_site_data(NOTES)

		self.assertEqual(site.client_name, 'Maya Patel')
		self.assertEqual(site.site_name, 'Riverside Community Center')
		self.assertEqual(site.address, '42 Harbor Street, Portland, OR 97205')
		self.assertEqual(site.estimated_budget, '$24,000')
		self.assertEqual(site.priority, 'High')
		self.assertEqual(len(site.equipment), 2)

	def test_compact_lakh_input_is_normalised(self):
		site = extract_site_data('Client: ABC IndustriesBudget: 2.5 lakhAddress: Chennai')

		self.assertEqual(site.client_name, 'ABC Industries')
		self.assertEqual(site.address, 'Chennai')
		self.assertEqual(site.estimated_budget, '$250,000')

	def test_conversational_input_is_supported(self):
		site = extract_site_data('visited abc industries yesterday, old equipment,location chennai, budget around 250000')

		self.assertEqual(site.client_name, 'abc industries')
		self.assertEqual(site.address, 'chennai')
		self.assertEqual(site.estimated_budget, '$250,000')
		self.assertIn('old equipment', site.equipment)

	def test_first_person_name_is_extracted_without_the_rest_of_sentence(self):
		site = extract_site_data("I'm Rahul. I need a MacBook for development. My budget is 1.5 lakh.")

		self.assertEqual(site.client_name, 'Rahul')

	def test_compact_site_note_keeps_client_name_and_address_separate(self):
		notes = ('Visited the Riverside Community Center for Maya Patel.Address: '
			 '42 Harbor Street, Portland, OR 97205.The rooftop has 18 aging solar panels '
			 'and one inverter showing a red fault light.Client is considering a replacement '
			 'and battery storage.Estimated budget is $24,000.Please schedule a follow-up '
			 'before October 15, 2026.')
		site = extract_site_data(notes)

		self.assertEqual(site.client_name, 'Maya Patel')
		self.assertEqual(site.address, '42 Harbor Street, Portland, OR 97205')
		self.assertEqual(site.estimated_budget, '$24,000')

	def test_missing_fields_are_rendered_without_crashing(self):
		response = self.client.post('/', {'notes': 'Client: ABC Industries'})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Address')
		self.assertContains(response, 'Needs attention before saving')

	def test_empty_and_unrelated_input_have_useful_errors(self):
		empty = self.client.post('/', {'notes': ''})
		unrelated = self.client.post('/', {'notes': 'The weather was sunny today.'})

		self.assertContains(empty, 'Please enter site inspection notes.')
		self.assertContains(unrelated, 'Could not find site details')

	def test_very_long_input_is_rejected(self):
		response = self.client.post('/', {'notes': 'Client: ABC ' + ('x' * 5001)})

		self.assertContains(response, '5000 characters or less')

	def test_dashboard_extracts_posted_notes(self):
		response = self.client.post('/', {'notes': NOTES})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Maya Patel')
		self.assertContains(response, 'Validated')

	def test_parse_site_api_returns_assessment_schema(self):
		response = self.client.post('/api/parse-site/', data=json.dumps({'text': NOTES}), content_type='application/json')
		body = response.json()

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(body), {'client_name', 'address', 'equipment_notes', 'estimated_budget'})
		self.assertEqual(body['client_name'], 'Maya Patel')
		self.assertIsInstance(body['estimated_budget'], float)

	def test_parse_site_api_rejects_invalid_body(self):
		response = self.client.post('/api/parse-site/', data=json.dumps({'notes': 'wrong key'}), content_type='application/json')

		self.assertEqual(response.status_code, 400)

	def test_save_endpoint_validates_edits(self):
		payload = SiteData(client_name='Maya Patel', address='42 Harbor Street').to_dict()
		response = self.client.post('/api/sites/save/', data=json.dumps(payload), content_type='application/json')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['site']['client_name'], 'Maya Patel')

	def test_save_endpoint_rejects_missing_required_fields(self):
		response = self.client.post('/api/sites/save/', data=json.dumps({'client_name': ''}), content_type='application/json')

		self.assertEqual(response.status_code, 400)

	def test_save_endpoint_rejects_invalid_budget(self):
		payload = SiteData(client_name='Maya Patel', address='Chennai', estimated_budget='a lot').to_dict()
		response = self.client.post('/api/sites/save/', data=json.dumps(payload), content_type='application/json')

		self.assertEqual(response.status_code, 400)
		self.assertIn('Budget must be a valid number', response.json()['error'])

	@override_settings(OPENAI_API_KEY='test-key')
	def test_invalid_llm_json_returns_readable_error(self):
		response_mock = type('Response', (), {'read': lambda self: b'{"choices":[{"message":{"content":"not json"}}]}', '__enter__': lambda self: self, '__exit__': lambda self, *args: None})()
		with patch('pratice_app.services.urlrequest.urlopen', return_value=response_mock):
			with self.assertRaisesMessage(ExtractionError, 'invalid JSON response'):
				extract_site_data('Client: ABC Industries Address: Chennai')

	@override_settings(OPENAI_API_KEY='test-key')
	def test_llm_rate_limit_is_safe(self):
		error = HTTPError('https://api.openai.com', 429, 'rate limit', {}, None)
		with patch('pratice_app.services.urlrequest.urlopen', side_effect=error):
			with self.assertRaisesMessage(ExtractionError, 'rate limit'):
				extract_site_data('Client: ABC Industries Address: Chennai')

	@override_settings(OPENAI_API_KEY='test-key')
	def test_llm_timeout_is_safe(self):
		with patch('pratice_app.services.urlrequest.urlopen', side_effect=TimeoutError()):
			with self.assertRaisesMessage(ExtractionError, 'timed out'):
				extract_site_data('Client: ABC Industries Address: Chennai')
