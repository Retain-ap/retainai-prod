"""Read-only Stripe Tax preflight. Never creates or updates Stripe resources.

Run in the intended server environment; credentials come only from its environment.
No emails, addresses, registration numbers, customer IDs or API keys are printed.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

import stripe


def inspect(client, *, expected_account, expected_product, price_id, livemode):
    account = client.accounts.retrieve_current()
    if account.get('id') != expected_account:
        raise ValueError('Stripe account does not match the approved account')
    price = client.prices.retrieve(price_id, {'expand': ['product']})
    product = price.get('product') or {}
    if (price.get('id') != price_id or price.get('livemode') is not livemode
            or not isinstance(product, dict) or product.get('id') != expected_product
            or product.get('livemode') is not livemode):
        raise ValueError('Configured price/product or mode does not match the approved plan')
    settings = client.tax.settings.retrieve()
    if settings.get('livemode') is not livemode:
        raise ValueError('Tax settings mode does not match the approved account')
    registrations = list(client.tax.registrations.list({'status': 'all', 'limit': 100}).auto_paging_iter())
    subscriptions = list(client.subscriptions.list({'price': price_id, 'status': 'all', 'limit': 100}).auto_paging_iter())
    if any(row.get('livemode') is not livemode for row in registrations + subscriptions):
        raise ValueError('Registration/subscription mode does not match the approved account')
    now = time.time()
    def current_federal(row):
        active_from, expires_at = row.get('active_from'), row.get('expires_at')
        return (row.get('country') == 'CA' and row.get('status') == 'active'
                and ((row.get('country_options') or {}).get('ca') or {}).get('type') == 'standard'
                and type(active_from) in (int, float) and active_from <= now
                and (expires_at is None or (type(expires_at) in (int, float) and expires_at > now)))
    subscription_counts = Counter(row.get('status') for row in subscriptions)
    readiness = {
        'price_active': price.get('active') is True,
        'product_active': product.get('active') is True,
        'monthly': (price.get('recurring') or {}).get('interval') == 'month',
        'tax_exclusive': price.get('tax_behavior') == 'exclusive',
        'tax_settings_active': settings.get('status') == 'active',
        'active_canada_federal_registration': any(current_federal(row) for row in registrations),
        'product_tax_code_present': isinstance(product.get('tax_code'), str) and product['tax_code'].startswith('txcd_'),
    }
    return {
        'read_only': True, 'account_id': account['id'], 'livemode': livemode,
        'price_id': price_id, 'product_id': product['id'], 'currency': price.get('currency'),
        'unit_amount': price.get('unit_amount'), 'tax_behavior': price.get('tax_behavior'),
        'product_tax_code': product.get('tax_code'),
        'tax_settings_status': settings.get('status'),
        'registrations': [{'country': row.get('country'), 'status': row.get('status'),
                           'canada_scheme': ((row.get('country_options') or {}).get('ca') or {}).get('type'),
                           'active_from': row.get('active_from'), 'expires_at': row.get('expires_at'),
                           'livemode': row.get('livemode')} for row in registrations],
        'subscription_status_counts': dict(sorted(subscription_counts.items())),
        'readiness': readiness, 'technical_checks_pass': all(readiness.values()),
        'activation_still_requires': ['owner-approved product classification and fees', 'pending/legacy checkout inventory and drain', 'sandbox checkout and invoice evidence', 'separate existing-subscription decision'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-account', required=True)
    parser.add_argument('--expected-product', required=True)
    parser.add_argument('--mode', choices=['test', 'live'], required=True)
    args = parser.parse_args()
    key, price_id = os.getenv('STRIPE_SECRET_KEY', ''), os.getenv('STRIPE_PRICE_ID', '')
    prefix = ('sk_live_', 'rk_live_') if args.mode == 'live' else ('sk_test_', 'rk_test_')
    if not price_id or not key.startswith(prefix):
        parser.error('Configured Stripe key mode or price is missing/mismatched; no request was sent.')
    try:
        client = stripe.StripeClient(key, stripe_version='2023-10-16')
        report = inspect(client, expected_account=args.expected_account, expected_product=args.expected_product, price_id=price_id, livemode=args.mode == 'live')
        print(json.dumps(report, indent=2))
        return 0 if report['technical_checks_pass'] else 2
    except Exception as exc:
        # Provider messages can contain customer/account details. Do not echo them.
        print(json.dumps({'read_only': True, 'error_type': type(exc).__name__, 'status': 'preflight_failed_no_changes'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
