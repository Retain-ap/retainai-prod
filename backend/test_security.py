"""Security-focused regression tests for RetainAI authentication helpers."""

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_account  # noqa: E402
import app_imports  # noqa: E402
import storage  # noqa: E402


class PasswordResetSecurityTests(unittest.TestCase):
    def setUp(self):
        self.email = "customer@example.com"
        self.user = {
            "email": self.email,
            "password": retainai.generate_password_hash("Original password 123!"),
        }

    def test_token_is_bound_to_current_password(self):
        users = {self.email: dict(self.user)}
        token = retainai._password_reset_token(self.email, users[self.email])
        email, _ = retainai._decode_password_reset_token(token, users)
        self.assertEqual(email, self.email)

        users[self.email]["password"] = retainai.generate_password_hash("Different password 456!")
        with self.assertRaises(ValueError):
            retainai._decode_password_reset_token(token, users)

    def test_expired_token_is_rejected(self):
        users = {self.email: dict(self.user)}
        token = retainai._password_reset_token(self.email, users[self.email])
        with patch.object(retainai.time, "time", return_value=time.time() + 1900):
            with self.assertRaises(ValueError):
                retainai._decode_password_reset_token(token, users)

    def test_forgot_password_does_not_reveal_account_existence(self):
        client = retainai.app.test_client()
        with patch.object(retainai, "load_users", return_value={}):
            response = client.post(
                "/api/auth/password/forgot",
                json={"email": "missing@example.com"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("missing", response.get_json()["message"].lower())

    def test_email_verification_token_is_signed(self):
        token = retainai._email_verification_token(self.email)
        self.assertEqual(
            retainai._decode_email_verification_token(token),
            self.email,
        )
        encoded, signature = token.split(".", 1)
        tampered = f"{encoded}.{signature[:-1]}0"
        with self.assertRaises(ValueError):
            retainai._decode_email_verification_token(tampered)


class RequestBoundarySecurityTests(unittest.TestCase):
    def test_cross_origin_authenticated_write_is_rejected(self):
        client = retainai.app.test_client()
        email = "customer@example.com"
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = email
            signed_session["org_email"] = email
            signed_session["security_version"] = 0
        with patch.object(
            retainai,
            "load_users",
            return_value={email: {"email": email, "security_version": 0}},
        ):
            response = client.post(
                "/api/leads",
                json={"leads": []},
                headers={"Origin": "https://malicious.example"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "untrusted_request_origin")


class WorkspaceStorageTests(unittest.TestCase):
    def test_saving_one_workspace_preserves_another(self):
        with tempfile.TemporaryDirectory() as data_root:
            leads_path = os.path.join(data_root, "leads.json")
            with patch.object(storage, "USE_SQLITE", False), patch.object(
                storage, "LEADS_JSON", leads_path
            ):
                storage._write_json(
                    leads_path,
                    {"first@example.com": [{"id": "first"}]},
                )
                storage.save_user_leads(
                    "second@example.com",
                    [{"id": "second"}],
                )
                saved = storage._read_json(leads_path, {})
        self.assertEqual(saved["first@example.com"][0]["id"], "first")
        self.assertEqual(saved["second@example.com"][0]["id"], "second")


class BillingCleanupTests(unittest.TestCase):
    def test_account_deletion_cancels_every_live_subscription(self):
        subscriptions = [
            {"id": "sub_primary", "status": "active"},
            {"id": "sub_duplicate", "status": "trialing"},
            {"id": "sub_finished", "status": "canceled"},
        ]
        page = type(
            "StripePage",
            (),
            {"auto_paging_iter": lambda self: iter(subscriptions)},
        )()
        empty_page = type(
            "StripeEmptyPage",
            (),
            {"auto_paging_iter": lambda self: iter(())},
        )()
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_value"}), patch.object(
            app_account.stripe.Subscription,
            "list",
            side_effect=[page, empty_page],
        ), patch.object(
            app_account.stripe.Subscription,
            "cancel",
        ) as cancel:
            count = app_account._cancel_workspace_subscriptions(
                {
                    "stripe_customer_id": "cus_test",
                    "stripe_subscription_id": "sub_primary",
                }
            )
        self.assertEqual(count, 2)
        self.assertEqual(
            {call.args[0] for call in cancel.call_args_list},
            {"sub_primary", "sub_duplicate"},
        )


class BillingCheckoutSafetyTests(unittest.TestCase):
    class StripeObject(dict):
        __getattr__ = dict.__getitem__

    def test_repeated_checkout_reuses_open_session(self):
        email = "billing@example.com"
        user = {"email": email, "status": "pending_payment"}
        users = {email: user}
        created = self.StripeObject(id="cs_once", url="https://checkout.example/once")
        opened = self.StripeObject(
            id="cs_once",
            url="https://checkout.example/once",
            status="open",
            subscription=None,
        )
        with patch.object(retainai, "STRIPE_SECRET_KEY", "sk_test_value"), patch.object(
            retainai, "STRIPE_PRICE_ID", "price_monthly"
        ), patch.object(
            retainai.stripe.Price,
            "retrieve",
            return_value={"active": True, "recurring": {"interval": "month"}},
        ), patch.object(
            retainai.stripe.Customer,
            "list",
            return_value=SimpleNamespace(data=[]),
        ), patch.object(
            retainai.stripe.checkout.Session,
            "create",
            return_value=created,
        ) as create_session, patch.object(
            retainai.stripe.checkout.Session,
            "retrieve",
            return_value=opened,
        ), patch.object(
            retainai, "load_users", return_value=users
        ), patch.object(
            retainai, "save_users"
        ):
            first = retainai._create_or_reuse_billing_checkout(
                email,
                user,
                cancel_url="https://www.retainai.ca/login?canceled=1",
                trial_days=14,
            )
            second = retainai._create_or_reuse_billing_checkout(
                email,
                user,
                cancel_url="https://www.retainai.ca/login?canceled=1",
                trial_days=14,
            )

        self.assertEqual(first["state"], "new_checkout")
        self.assertEqual(second["state"], "open_checkout")
        create_session.assert_called_once()
        self.assertEqual(
            create_session.call_args.kwargs["subscription_data"]["trial_period_days"],
            14,
        )
        self.assertTrue(create_session.call_args.kwargs["idempotency_key"])

    def test_existing_live_subscription_blocks_new_checkout(self):
        email = "active@example.com"
        user = {
            "email": email,
            "status": "pending_payment",
            "stripe_customer_id": "cus_existing",
        }
        users = {email: user}
        existing = {"id": "sub_existing", "status": "active", "created": 1}
        with patch.object(retainai, "STRIPE_SECRET_KEY", "sk_test_value"), patch.object(
            retainai, "STRIPE_PRICE_ID", "price_monthly"
        ), patch.object(
            retainai.stripe.Price,
            "retrieve",
            return_value={"active": True, "recurring": {"interval": "month"}},
        ), patch.object(
            retainai.stripe.Customer,
            "list",
            return_value=SimpleNamespace(data=[]),
        ), patch.object(
            retainai.stripe.Subscription,
            "list",
            return_value=SimpleNamespace(data=[existing]),
        ), patch.object(
            retainai.stripe.checkout.Session,
            "create",
        ) as create_session, patch.object(
            retainai, "load_users", return_value=users
        ), patch.object(
            retainai, "save_users"
        ):
            result = retainai._create_or_reuse_billing_checkout(
                email,
                user,
                cancel_url="https://www.retainai.ca/login?canceled=1",
            )

        self.assertEqual(result["state"], "existing_subscription")
        self.assertEqual(user["stripe_subscription_id"], "sub_existing")
        self.assertEqual(user["status"], "active")
        create_session.assert_not_called()

    def test_create_invoice_sends_the_finalized_invoice(self):
        email = "billing@example.com"
        users = {
            email: {
                "email": email,
                "org_id": email,
                "role": "owner",
                "status": "active",
                "security_version": 0,
                "stripe_account_id": "acct_connected",
            }
        }
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = email
            signed_session["org_email"] = email
            signed_session["security_version"] = 0

        customer = self.StripeObject(id="cus_invoice")
        draft = self.StripeObject(id="in_invoice")
        sent = self.StripeObject(
            id="in_invoice",
            currency="cad",
            customer={"name": "Customer"},
            customer_email="customer@example.com",
            amount_due=2500,
            amount_paid=0,
            total=2500,
            status="open",
            due_date=1_800_000_000,
            hosted_invoice_url="https://invoice.example/in_invoice",
            number="INV-1",
            metadata={"customer_name": "Customer"},
        )

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai.stripe.Customer, "list", return_value=SimpleNamespace(data=[])
        ), patch.object(
            retainai.stripe.Customer, "create", return_value=customer
        ), patch.object(
            retainai.stripe.Invoice, "create", return_value=draft
        ), patch.object(
            retainai.stripe.InvoiceItem, "create"
        ), patch.object(
            retainai.stripe.Invoice, "finalize_invoice", return_value=sent
        ), patch.object(
            retainai.stripe.Invoice, "send_invoice", return_value=sent
        ) as send_invoice, patch.object(
            retainai.stripe.Invoice, "list", return_value=SimpleNamespace(data=[sent])
        ):
            response = client.post(
                "/api/stripe/invoice",
                json={
                    "customer_name": "Customer",
                    "customer_email": "customer@example.com",
                    "description": "Consultation",
                    "amount": 25,
                    "currency": "cad",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["email_sent"])
        send_invoice.assert_called_once_with("in_invoice", stripe_account="acct_connected")


class ComplimentaryAccountTests(unittest.TestCase):
    def test_only_platform_owner_can_create_free_access_account(self):
        client = retainai.app.test_client()
        users = {}
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "owner@retainai.ca"
            signed_session["org_email"] = "owner@retainai.ca"
            signed_session["security_version"] = 0
            signed_session["mfa_assured"] = True
        authenticated_users = {
            "owner@retainai.ca": {
                "email": "owner@retainai.ca",
                "role": "owner",
                "org_id": "owner@retainai.ca",
                "security_version": 0,
            }
        }
        with patch.object(
            retainai, "load_users", return_value=authenticated_users
        ), patch.object(app_account, "load_users", return_value=users), patch(
            "app_owner.load_users", return_value=users
        ), patch("app_owner.load_leads", return_value={}), patch(
            "app_owner.save_users"
        ) as save:
            response = client.post(
                "/api/owner/accounts",
                json={
                    "email": "tester@example.com",
                    "password": "A secure launch password 123!",
                    "name": "Trusted Tester",
                    "business": "Launch Partner",
                },
            )
        self.assertEqual(response.status_code, 201)
        created = save.call_args.args[0]["tester@example.com"]
        self.assertTrue(created["billing_exempt"])
        self.assertTrue(created["complimentary_access"])
        self.assertEqual(created["billing_status"], "complimentary")
        self.assertNotEqual(created["password"], "A secure launch password 123!")

    def test_expired_complimentary_access_is_inactive(self):
        self.assertFalse(
            retainai._complimentary_access_active(
                {
                    "billing_exempt": True,
                    "complimentary_access": True,
                    "complimentary_expires_at": "2000-01-01T00:00:00Z",
                }
            )
        )

    def test_platform_trial_extension_restores_actual_access(self):
        owner = "owner@retainai.ca"
        customer = "returning@example.com"
        users = {
            owner: {
                "email": owner,
                "org_id": owner,
                "role": "owner",
                "status": "active",
                "security_version": 0,
            },
            customer: {
                "email": customer,
                "org_id": customer,
                "role": "owner",
                "status": "pending_payment",
                "access_status": "inactive",
                "billing_status": "past_due",
                "trial_eligible": False,
                "security_version": 2,
            },
        }
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = owner
            signed_session["org_email"] = owner
            signed_session["security_version"] = 0
            signed_session["mfa_assured"] = True

        with patch.object(retainai, "load_users", return_value=users), patch(
            "app_owner.load_users", return_value=users
        ), patch("app_owner.save_users") as save_users, patch("app_owner._audit"):
            response = client.post(
                f"/api/owner/accounts/{customer}/action",
                json={"action": "extend_trial", "days": 7},
            )

        self.assertEqual(response.status_code, 200)
        updated = save_users.call_args.args[0][customer]
        self.assertTrue(updated["trial_eligible"])
        self.assertEqual(updated["billing_status"], "trial")
        self.assertEqual(updated["security_version"], 3)
        self.assertTrue(retainai._account_has_access(updated))


class TenantIdentitySecurityTests(unittest.TestCase):
    @staticmethod
    def _active_user(email, **overrides):
        user = {
            "email": email,
            "org_id": email,
            "role": "owner",
            "status": "active",
            "security_version": 0,
        }
        user.update(overrides)
        return user

    @staticmethod
    def _sign_in(client, actor, org=None):
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = actor
            signed_session["org_email"] = org or actor
            signed_session["security_version"] = 0

    def test_automation_history_uses_session_workspace(self):
        client = retainai.app.test_client()
        actor = "member@example.com"
        owner = "owner@example.com"
        users = {
            actor: self._active_user(actor, org_id=owner, role="member"),
            owner: self._active_user(owner),
        }
        self._sign_in(client, actor, owner)

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "_automation_history_for_user", return_value=[]
        ) as history:
            response = client.get(
                "/api/automations/history?user=victim@example.com"
            )

        self.assertEqual(response.status_code, 200)
        history.assert_called_once_with(owner)

    def test_google_routes_use_signed_workspace_not_supplied_identity(self):
        client = retainai.app.test_client()
        actor = "member@example.com"
        owner = "owner@example.com"
        users = {
            actor: self._active_user(actor, org_id=owner, role="member"),
            owner: self._active_user(owner),
        }
        self._sign_in(client, actor, owner)

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            app_imports, "_get_token", return_value=None
        ) as get_token, patch.object(
            app_imports, "_get_sync_token", return_value=None
        ) as get_sync_token, patch.object(
            app_imports, "_load_leads_bucket", return_value=[]
        ) as load_bucket:
            status_response = client.get(
                f"/api/google/status?userEmail={owner}"
            )
            import_response = client.post(
                "/api/google/import-now",
                json={"userEmail": owner},
            )
            debug_response = client.get(f"/api/google/debug-list?userEmail={owner}")

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(import_response.status_code, 400)
        self.assertEqual(debug_response.status_code, 404)
        self.assertEqual(
            [item.args[0] for item in get_token.call_args_list],
            [owner, owner],
        )
        get_sync_token.assert_called_once_with(owner)
        load_bucket.assert_called_once_with(owner)

    def test_google_complete_updates_only_signed_in_account(self):
        client = retainai.app.test_client()
        actor = "actor@example.com"
        victim = "victim@example.com"
        users = {
            actor: self._active_user(actor, name="Actor"),
            victim: self._active_user(victim, name="Victim"),
        }
        self._sign_in(client, actor)

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "save_users"
        ) as save_users:
            response = client.post(
                "/api/oauth/google/complete",
                json={"email": victim, "name": "Updated Actor"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(users[actor]["name"], "Updated Actor")
        self.assertEqual(users[victim]["name"], "Victim")
        save_users.assert_called_once_with(users)

    def test_send_ai_message_cannot_find_another_workspaces_lead(self):
        client = retainai.app.test_client()
        actor = "actor@example.com"
        victim_owner = "victim-owner@example.com"
        victim_lead = "victim-lead@example.com"
        users = {actor: self._active_user(actor)}
        leads = {
            actor: [{"email": "own-lead@example.com"}],
            victim_owner: [{"email": victim_lead}],
        }
        self._sign_in(client, actor)

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_leads", return_value=leads
        ), patch.object(retainai, "send_email_with_template") as send_email:
            response = client.post(
                "/api/send-ai-message",
                json={"to": victim_lead, "message": "Hello"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "lead_not_found")
        send_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
