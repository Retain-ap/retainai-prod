"""Read-only operator report rejects account/plan mismatches and omits identifiers."""
import unittest
from unittest.mock import Mock
import stripe_tax_preflight as preflight


class TaxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.accounts.retrieve_current.return_value = {'id': 'acct_expected', 'email': 'private@example.com'}
        self.client.prices.retrieve.return_value = {'id': 'price_expected', 'livemode': True, 'active': True, 'currency': 'cad', 'unit_amount': 2000, 'recurring': {'interval': 'month'}, 'tax_behavior': 'exclusive', 'product': {'id': 'prod_expected', 'livemode': True, 'active': True, 'tax_code': 'txcd_10000000'}}
        self.client.tax.settings.retrieve.return_value = {'status': 'active', 'livemode': True}
        self.client.tax.registrations.list.return_value.auto_paging_iter.return_value = [{'country': 'CA', 'status': 'active', 'livemode': True, 'active_from': 1, 'expires_at': None, 'country_options': {'ca': {'type': 'standard'}}, 'id': 'taxreg_private'}]
        self.client.subscriptions.list.return_value.auto_paging_iter.return_value = [{'status': 'active', 'livemode': True, 'customer': 'cus_private'}, {'status': 'active', 'livemode': True}, {'status': 'trialing', 'livemode': True}]

    def inspect(self):
        return preflight.inspect(self.client, expected_account='acct_expected', expected_product='prod_expected', price_id='price_expected', livemode=True)

    def test_report_contains_only_safe_summary_and_approved_plan(self):
        report = self.inspect()
        self.assertTrue(report['technical_checks_pass'])
        self.assertEqual(report['subscription_status_counts'], {'active': 2, 'trialing': 1})
        self.assertNotIn('private', str(report))
        self.client.subscriptions.list.assert_called_once_with({'price': 'price_expected', 'status': 'all', 'limit': 100})

    def test_wrong_account_or_plan_fails_closed(self):
        self.client.accounts.retrieve_current.return_value['id'] = 'acct_other'
        with self.assertRaises(ValueError): self.inspect()
        self.client.prices.retrieve.assert_not_called()
        self.client.accounts.retrieve_current.return_value['id'] = 'acct_expected'
        self.client.prices.retrieve.return_value['product']['id'] = 'prod_other'
        with self.assertRaises(ValueError): self.inspect()
        self.client.tax.settings.retrieve.assert_not_called()

    def test_missing_registration_prevents_technical_ready_status(self):
        self.client.tax.registrations.list.return_value.auto_paging_iter.return_value = []
        report = self.inspect()
        self.assertFalse(report['technical_checks_pass'])
        self.assertFalse(report['readiness']['active_canada_federal_registration'])

    def test_nonfederal_or_not_current_registrations_cannot_pass(self):
        import time
        baseline = {'country': 'CA', 'status': 'active', 'livemode': True, 'active_from': 1, 'expires_at': None, 'country_options': {'ca': {'type': 'standard'}}}
        for change in [{'country_options': {'ca': {'type': 'province_standard'}}}, {'country_options': {'ca': {'type': 'simplified'}}}, {'status': 'scheduled'}, {'status': 'expired'}, {'active_from': None}, {'active_from': time.time() + 600}, {'expires_at': time.time() - 1}]:
            with self.subTest(change=change):
                self.client.tax.registrations.list.return_value.auto_paging_iter.return_value = [{**baseline, **change}]
                self.assertFalse(self.inspect()['readiness']['active_canada_federal_registration'])

    def test_wrong_provider_mode_is_rejected(self):
        self.client.tax.settings.retrieve.return_value['livemode'] = False
        with self.assertRaises(ValueError): self.inspect()
        self.client.tax.settings.retrieve.return_value['livemode'] = True
        self.client.tax.registrations.list.return_value.auto_paging_iter.return_value = [{'livemode': False}]
        with self.assertRaises(ValueError): self.inspect()
        self.client.tax.registrations.list.return_value.auto_paging_iter.return_value = []
        self.client.subscriptions.list.return_value.auto_paging_iter.return_value = [{'livemode': False}]
        with self.assertRaises(ValueError): self.inspect()

    def test_missing_product_tax_code_does_not_pass(self):
        self.client.prices.retrieve.return_value['product']['tax_code'] = None
        self.assertFalse(self.inspect()['technical_checks_pass'])

if __name__ == '__main__': unittest.main()
