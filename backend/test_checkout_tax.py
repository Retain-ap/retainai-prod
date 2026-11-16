"""All providers are mocked: tax rollout, exact retries, and duplicate-payment guards."""
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('USE_SQLITE', 'false')
import billing_checkout_policy as policy


class CheckoutPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = os.path.join(self.temp.name, 'attempts.json')
        for p in (patch.object(policy, 'ATTEMPTS_FILE', self.file), patch.dict(os.environ, {policy.FLAG: 'false', policy.PAUSE_FLAG: 'false'})):
            p.start(); self.addCleanup(p.stop)
        self.email = 'billing@example.com'
        self.users = {self.email: {'email': self.email, 'status': 'pending_payment', 'terms_accepted_at': '2026-11-01'}}
        self.stripe = Mock()
        self.stripe.Price.retrieve.return_value = {'id': 'price_monthly', 'livemode': False, 'active': True, 'recurring': {'interval': 'month'}, 'tax_behavior': 'exclusive'}
        self.stripe.Customer.retrieve.return_value = {'id': 'cus_existing', 'livemode': False, 'shipping': None}
        self.sessions = {}
        self.requests = {}
        self.stripe.checkout.Session.create.side_effect = self.create
        self.stripe.checkout.Session.retrieve.side_effect = lambda sid, **kw: copy.deepcopy(self.sessions[sid])
        self.find = Mock(return_value=None)

    def create(self, **params):
        key = params['idempotency_key']
        if key in self.requests:
            self.assertEqual(params, self.requests[key])
            return copy.deepcopy(self.sessions['cs_' + key[:16]])
        self.requests[key] = copy.deepcopy(params)
        sid = 'cs_' + key[:16]
        self.sessions[sid] = {'id': sid, 'url': 'https://checkout.stripe.com/c/pay/' + sid,
            'status': 'open', 'mode': 'subscription', 'livemode': False,
            'metadata': copy.deepcopy(params['metadata']), 'customer': params.get('customer'),
            'customer_email': params.get('customer_email'), 'subscription': None,
            'automatic_tax': {'enabled': params.get('automatic_tax', {}).get('enabled', False)}}
        return copy.deepcopy(self.sessions[sid])

    def save(self, value):
        self.users = copy.deepcopy(value)

    def checkout(self, **overrides):
        args = dict(email=self.email, user=copy.deepcopy(self.users.get(self.email, {})), cancel_url='https://www.retainai.ca/login?cancel=1', trial_days=14, recovery=False, stripe=self.stripe,
                    secret_key='sk_test_fixture', price_id='price_monthly', frontend_url='https://www.retainai.ca',
                    load_users=lambda: copy.deepcopy(self.users), save_users=self.save,
                    complimentary_access_active=lambda u: False, find_existing_subscription=self.find,
                    administratively_blocked=lambda u: u.get('status') in {'suspended', 'deletion_pending'},
                    blocking_statuses={'active', 'trialing', 'past_due', 'unpaid', 'incomplete', 'paused'})
        args.update(overrides)
        return policy.create_or_reuse(**args)

    def enabled(self):
        os.environ[policy.FLAG] = 'true'

    def ledger(self):
        with open(self.file) as f:
            return json.load(f)

    def test_default_off_preserves_legacy_request_and_key(self):
        self.users[self.email]['partner_code'] = 'partner'
        self.checkout()
        args = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertNotIn('automatic_tax', args)
        self.assertNotIn('billing_address_collection', args)
        self.assertEqual(args['payment_method_types'], ['card'])
        self.assertEqual(args['idempotency_key'], hashlib.sha256(f'retainai-subscription-checkout:{self.email}:0'.encode()).hexdigest())
        self.assertEqual(args['subscription_data']['trial_period_days'], 14)
        self.assertEqual(args['subscription_data']['metadata']['partner_code'], 'partner')
        self.stripe.Customer.modify.assert_not_called()

    def test_pause_makes_zero_provider_calls_and_no_ledger_write(self):
        os.environ[policy.PAUSE_FLAG] = 'true'
        with self.assertRaises(policy.CheckoutPaused): self.checkout()
        self.assertEqual(self.stripe.mock_calls, [])
        self.assertFalse(os.path.exists(self.file))

    def test_pause_unpause_preserves_exact_pending_retry(self):
        self.stripe.checkout.Session.create.side_effect = TimeoutError('lost')
        with self.assertRaises(TimeoutError): self.checkout()
        frozen = self.ledger()
        os.environ[policy.PAUSE_FLAG] = 'true'; self.stripe.reset_mock()
        with self.assertRaises(policy.CheckoutPaused): self.checkout()
        self.assertEqual(self.stripe.mock_calls, [])
        self.assertEqual(self.ledger(), frozen)
        os.environ[policy.PAUSE_FLAG] = 'false'
        self.stripe.checkout.Session.create.side_effect = self.create
        self.checkout(trial_days=0)
        args = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertEqual(args, {**frozen[self.email]['params'], 'idempotency_key': frozen[self.email]['idempotency_key']})

    def test_pause_during_customer_check_blocks_create_but_keeps_attempt(self):
        self.enabled(); self.users[self.email]['stripe_customer_id'] = 'cus_existing'
        def paused(customer):
            os.environ[policy.PAUSE_FLAG] = 'true'
            return {'id': customer, 'livemode': False, 'shipping': None}
        self.stripe.Customer.retrieve.side_effect = paused
        with self.assertRaises(policy.CheckoutPaused): self.checkout()
        self.stripe.checkout.Session.create.assert_not_called()
        self.assertEqual(self.ledger()[self.email]['session_id'], '')

    def test_pause_during_lookup_prevents_ledger_claim(self):
        self.find.side_effect = lambda *args: os.environ.__setitem__(policy.PAUSE_FLAG, 'true')
        with self.assertRaises(policy.CheckoutPaused): self.checkout()
        self.assertFalse(os.path.exists(self.file))
        self.stripe.checkout.Session.create.assert_not_called()

    def test_pause_during_open_session_retrieval_suppresses_url(self):
        self.checkout()
        frozen = self.ledger()
        def paused(sid, **kwargs):
            os.environ[policy.PAUSE_FLAG] = 'true'
            return copy.deepcopy(self.sessions[sid])
        self.stripe.checkout.Session.retrieve.side_effect = paused
        with self.assertRaises(policy.CheckoutPaused): self.checkout()
        self.assertEqual(self.ledger(), frozen)
        self.stripe.checkout.Session.create.assert_called_once()

    def test_new_customer_tax_uses_minimum_location_collection(self):
        self.enabled(); self.checkout()
        args = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertEqual(args['automatic_tax'], {'enabled': True})
        self.assertEqual(args['customer_email'], self.email)
        for key in ['customer_update', 'billing_address_collection', 'tax_id_collection', 'shipping_address_collection']:
            self.assertNotIn(key, args)

    def test_existing_customer_collects_and_saves_billing_address(self):
        self.enabled(); self.users[self.email]['stripe_customer_id'] = 'cus_existing'; self.checkout()
        args = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertEqual(args['billing_address_collection'], 'required')
        self.assertEqual(args['customer_update'], {'address': 'auto'})
        self.stripe.Customer.modify.assert_not_called()

    def test_saved_shipping_or_wrong_customer_fails_closed(self):
        self.enabled(); self.users[self.email]['stripe_customer_id'] = 'cus_existing'
        for change in [{'shipping': {'address': {'country': 'US'}}}, {'id': 'cus_wrong'}, {'livemode': True}, {'deleted': True}]:
            with self.subTest(change=change):
                self.stripe.Customer.retrieve.return_value = {'id': 'cus_existing', 'livemode': False, **change}
                with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
                self.stripe.checkout.Session.create.assert_not_called()
                self.stripe.Customer.modify.assert_not_called()

    def test_lost_response_retries_exact_frozen_params_and_key(self):
        self.enabled()
        def lost(**kw):
            self.create(**kw)
            raise TimeoutError('provider response lost')
        self.stripe.checkout.Session.create.side_effect = lost
        with self.assertRaises(TimeoutError): self.checkout()
        original = copy.deepcopy(self.stripe.checkout.Session.create.call_args.kwargs)
        self.users[self.email]['partner_code'] = 'later-partner'
        self.stripe.checkout.Session.create.side_effect = self.create
        self.checkout(cancel_url='https://www.retainai.ca/signup', recovery=True, trial_days=0)
        self.assertEqual(original, self.stripe.checkout.Session.create.call_args.kwargs)
        self.assertEqual(len(self.sessions), 1)

    def test_concurrent_callers_share_one_frozen_request(self):
        barrier, provider_lock = threading.Barrier(2), threading.Lock()
        def deferred(**kw):
            barrier.wait(timeout=5)
            with provider_lock:
                return self.create(**kw)
        self.stripe.checkout.Session.create.side_effect = deferred
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self.checkout, trial_days=14)
            b = pool.submit(self.checkout, trial_days=0, cancel_url='https://www.retainai.ca/signup')
            self.assertEqual(a.result(timeout=10)['url'], b.result(timeout=10)['url'])
        calls = self.stripe.checkout.Session.create.call_args_list
        self.assertEqual(calls[0].kwargs, calls[1].kwargs)
        self.assertEqual(len(self.sessions), 1)

    def test_tax_rollback_blocks_lost_and_open_attempts(self):
        self.enabled()
        self.stripe.checkout.Session.create.side_effect = TimeoutError('lost')
        with self.assertRaises(TimeoutError): self.checkout()
        os.environ[policy.FLAG] = 'false'
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.enabled(); self.stripe.checkout.Session.create.side_effect = self.create; self.checkout()
        os.environ[policy.FLAG] = 'false'
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertEqual(self.stripe.checkout.Session.create.call_count, 2)
        self.stripe.checkout.Session.expire.assert_not_called()

    def test_pending_flag_or_price_change_blocks_without_expiring(self):
        self.stripe.checkout.Session.create.side_effect = TimeoutError('lost')
        with self.assertRaises(TimeoutError): self.checkout()
        self.enabled()
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        os.environ[policy.FLAG] = 'false'
        self.stripe.Price.retrieve.return_value['id'] = 'price_changed'
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout(price_id='price_changed')
        self.assertEqual(self.stripe.checkout.Session.create.call_count, 1)
        self.stripe.checkout.Session.expire.assert_not_called()

    def test_uncertain_attempt_at_24_hours_blocks_retry(self):
        self.stripe.checkout.Session.create.side_effect = TimeoutError('lost')
        start = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
        with patch.object(policy, '_now', return_value=start):
            with self.assertRaises(TimeoutError): self.checkout()
        with patch.object(policy, '_now', return_value=start + dt.timedelta(hours=24)):
            with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertEqual(self.stripe.checkout.Session.create.call_count, 1)

    def test_known_open_session_reused_even_after_retry_window(self):
        first = self.checkout()
        with patch.object(policy, '_now', return_value=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)):
            second = self.checkout()
        self.assertEqual(first['url'], second['url'])
        self.assertEqual(second['state'], 'open_checkout')
        self.stripe.checkout.Session.create.assert_called_once()

    def test_open_policy_change_blocks_without_expiring(self):
        self.checkout(); self.enabled()
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.stripe.checkout.Session.create.assert_called_once()
        self.stripe.checkout.Session.expire.assert_not_called()

    def test_unrecorded_legacy_open_tax_session_blocks(self):
        self.enabled(); self.checkout()
        os.remove(self.file)
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.stripe.checkout.Session.create.assert_called_once()

    def test_expired_session_allows_new_generation(self):
        self.checkout()
        next(iter(self.sessions.values()))['status'] = 'expired'
        self.enabled(); self.checkout()
        self.assertEqual(self.ledger()[self.email]['generation'], 1)
        self.assertEqual(len(self.sessions), 2)

    def test_complete_without_resolved_subscription_blocks(self):
        self.checkout()
        session = next(iter(self.sessions.values())); session['status'] = 'complete'
        for sub in [None, 'sub_pending', {}, {'id': 'sub_pending', 'status': 'unknown'}]:
            with self.subTest(sub=sub):
                session['subscription'] = sub
                with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.stripe.checkout.Session.create.assert_called_once()

    def test_complete_with_verified_canceled_subscription_allows_new(self):
        self.checkout()
        session = next(iter(self.sessions.values())); session.update(status='complete', subscription={'id': 'sub_old', 'status': 'canceled'})
        self.checkout()
        self.assertEqual(len(self.sessions), 2)

    def test_complete_active_subscription_preserves_current_admin_state(self):
        self.checkout()
        session = next(iter(self.sessions.values())); session.update(status='complete', subscription={'id': 'sub_active', 'status': 'active'}, customer='cus_created')
        def fetch(sid, **kw):
            self.users[self.email]['status'] = 'suspended'
            self.users[self.email]['name'] = 'Newest name'
            return copy.deepcopy(session)
        self.stripe.checkout.Session.retrieve.side_effect = fetch
        self.assertEqual(self.checkout()['state'], 'existing_subscription')
        self.assertEqual(self.users[self.email]['status'], 'suspended')
        self.assertEqual(self.users[self.email]['name'], 'Newest name')
        self.assertEqual(self.users[self.email]['stripe_customer_id'], 'cus_created')
        self.stripe.checkout.Session.create.assert_called_once()

    def test_existing_subscription_no_migration_or_checkout(self):
        self.enabled()
        def existing(email, user):
            user.update(stripe_customer_id='cus_existing', stripe_subscription_id='sub_existing', billing_status='trialing', status='active')
            self.users[self.email]['status'] = 'suspended'
            return {'id': 'sub_existing', 'status': 'trialing'}
        self.find.side_effect = existing
        self.assertEqual(self.checkout()['state'], 'existing_subscription')
        self.assertEqual(self.users[self.email]['status'], 'suspended')
        self.stripe.checkout.Session.create.assert_not_called()
        self.stripe.Subscription.modify.assert_not_called()
        self.assertFalse(os.path.exists(self.file))

    def test_deleted_account_during_create_is_not_resurrected(self):
        def deleted(**kw):
            result = self.create(**kw); self.users.clear(); return result
        self.stripe.checkout.Session.create.side_effect = deleted
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertEqual(self.users, {})
        self.assertEqual(self.ledger()[self.email]['session_id'], '')

    def test_replaced_account_during_create_is_not_modified(self):
        def replaced(**kw):
            result = self.create(**kw); self.users[self.email] = {'terms_accepted_at': '2026-12-01', 'name': 'New account'}; return result
        self.stripe.checkout.Session.create.side_effect = replaced
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertEqual(self.users[self.email], {'terms_accepted_at': '2026-12-01', 'name': 'New account'})

    def test_recreated_account_during_lookup_cannot_claim_old_params(self):
        def replaced(email, user):
            self.users[email] = {'terms_accepted_at': '2026-12-01', 'name': 'New account'}
        self.find.side_effect = replaced
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertFalse(os.path.exists(self.file))
        self.stripe.checkout.Session.create.assert_not_called()

    def test_late_original_claim_cannot_reuse_replacement_account_attempt(self):
        original_claim = policy._claim
        def replaced_claim(*args, **kwargs):
            self.users[self.email]['terms_accepted_at'] = '2026-12-01'
            replaced_args = list(args); replaced_args[5] = '2026-12-01'
            return original_claim(*replaced_args, **kwargs)
        with patch.object(policy, '_claim', side_effect=replaced_claim):
            with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.stripe.checkout.Session.create.assert_not_called()

    def test_corrupt_ledger_fails_closed(self):
        with open(self.file, 'w') as f: f.write('{not json')
        with self.assertRaises(Exception): self.checkout()
        self.stripe.checkout.Session.create.assert_not_called()

    def test_create_response_tax_mismatch_keeps_known_session_and_blocks_url(self):
        self.enabled()
        def mismatch(**kw):
            result = self.create(**kw); result['automatic_tax']['enabled'] = False; return result
        self.stripe.checkout.Session.create.side_effect = mismatch
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.assertTrue(self.ledger()[self.email]['session_id'])

    def test_provider_response_identity_and_url_checks(self):
        changes = [{'id': 'bad'}, {'livemode': True}, {'mode': 'payment'}, {'metadata': {'user_email': 'other@example.com'}}, {'customer_email': 'other@example.com'}, {'url': 'https://checkout.stripe.com.evil.test/pay'}, {'url': 'http://checkout.stripe.com/pay'}, {'url': 'https://user@checkout.stripe.com/pay'}]
        for change in changes:
            with self.subTest(change=change):
                if os.path.exists(self.file): os.remove(self.file)
                self.users[self.email].pop('stripe_checkout_session_id', None)
                def altered(**kw):
                    return {**self.create(**kw), **change}
                self.stripe.checkout.Session.create.side_effect = altered
                with self.assertRaises(policy.CheckoutPolicyError): self.checkout()

    def test_retrieved_session_id_must_match_requested(self):
        self.checkout()
        self.stripe.checkout.Session.retrieve.side_effect = lambda sid, **kw: {**self.sessions[sid], 'id': 'cs_foreign'}
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
        self.stripe.checkout.Session.create.assert_called_once()

    def test_existing_customer_session_must_match_customer(self):
        self.enabled(); self.users[self.email]['stripe_customer_id'] = 'cus_existing'
        def wrong(**kw): return {**self.create(**kw), 'customer': 'cus_other'}
        self.stripe.checkout.Session.create.side_effect = wrong
        with self.assertRaises(policy.CheckoutPolicyError): self.checkout()

    def test_tax_requires_verified_exclusive_price(self):
        self.enabled()
        for change in [{'id': 'price_other'}, {'livemode': True}, {'tax_behavior': 'unspecified'}, {'tax_behavior': 'inclusive'}]:
            with self.subTest(change=change):
                price = {'id': 'price_monthly', 'livemode': False, 'active': True, 'recurring': {'interval': 'month'}, 'tax_behavior': 'exclusive', **change}
                self.stripe.Price.retrieve.return_value = price
                with self.assertRaises(policy.CheckoutPolicyError): self.checkout()
                self.stripe.checkout.Session.create.assert_not_called()

if __name__ == '__main__': unittest.main()
