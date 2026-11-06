"""Value Receipt: only real, linked, net paid merchant revenue is counted."""

import datetime as dt
import json
import os
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_value  # noqa: E402
import storage  # noqa: E402
import value_receipt as vr  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
UTC = dt.timezone.utc


def ts(text):
    return int(dt.datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


def invoice(invoice_id="in_1", *, email="ana@example.com", amount=12000, currency="cad", created="2026-10-10T10:00:00",
            paid="2026-10-12T15:00:00", refunded=0, credit_notes=0, out_of_band=False, livemode=True, status="paid"):
    return {
        "id": invoice_id, "status": status, "currency": currency, "amount_paid": amount, "livemode": livemode,
        "customer_email": email, "customer_name": "Ana", "number": f"N-{invoice_id}", "created": ts(created),
        "status_transitions": {"paid_at": ts(paid), "finalized_at": ts(created)},
        "charge": {"id": "ch_1", "paid": True, "status": "succeeded", "captured": True, "amount_captured": amount,
                   "disputed": False, "currency": currency, "amount": amount, "livemode": livemode, "amount_refunded": refunded},
        "post_payment_credit_notes_amount": credit_notes,
        "paid_out_of_band": out_of_band,
    }


def followup(at, *, lead_id="a", email="", channel="email"):
    return {"lead_id": lead_id, "lead_email": email, "channel": channel, "sent_at": at, "evidence": "test",
            "_at": vr._utc(at)}


LEADS = [{"id": "a", "name": "Ana", "email": "ana@example.com"}, {"id": "b", "name": "Ben", "email": "ben@example.com"}]
START = dt.datetime(2026, 10, 1, tzinfo=UTC)
END = dt.datetime(2026, 11, 1, tzinfo=UTC)


def receipt(records, followups=(), appointments=(), leads=LEADS, **kwargs):
    return vr.build_receipt(records=records, leads=list(leads), followups=list(followups),
                            appointments=list(appointments), start=START, end=END, window_days=kwargs.pop("window_days", 30), **kwargs)


class EvidenceRuleTests(unittest.TestCase):
    def test_amounts_are_exact_minor_units(self):
        self.assertEqual(vr.to_minor("120.50", "cad"), 12050)
        self.assertEqual(vr.to_minor("5000", "jpy"), 5000)
        for bad, currency in (("1.005", "cad"), ("1.5", "jpy"), ("0", "cad"), ("-3", "cad"), ("abc", "cad"), ("2000000", "cad")):
            with self.subTest(bad=bad), self.assertRaises(vr.EvidenceError):
                vr.to_minor(bad, currency)
        with self.assertRaises(vr.EvidenceError):
            vr.normalize_currency("btc")

    def test_only_a_proven_successful_charge_is_provider_verified(self):
        verified = vr.stripe_invoice_record(invoice(), "acct_1")
        self.assertEqual((verified["verification"], verified["settlement"], verified["amount_minor"]), (vr.VERIFIED, "charge", 12000))
        self.assertEqual(verified["stripe_api_version"], "2023-10-16")
        cases = {
            "no charge (credit balance or minimum amount)": ({"charge": None}, vr.UNCONFIRMED, "no_charge"),
            "unexpanded charge id": ({"charge": "ch_1"}, vr.UNCONFIRMED, "charge_unreadable"),
            "charge not succeeded": ({"charge": {**invoice()["charge"], "status": "pending"}}, vr.UNCONFIRMED, "charge_incomplete"),
            "charge not paid": ({"charge": {**invoice()["charge"], "paid": False}}, vr.UNCONFIRMED, "charge_incomplete"),
            "part paid from credit": ({"charge": {**invoice()["charge"], "amount": 7000}}, vr.UNCONFIRMED, "charge_incomplete"),
            "currency mismatch": ({"charge": {**invoice()["charge"], "currency": "usd"}}, vr.UNCONFIRMED, "charge_incomplete"),
            "test charge on live invoice": ({"charge": {**invoice()["charge"], "livemode": False}}, vr.UNCONFIRMED, "charge_incomplete"),
            "marked paid outside Stripe": ({"paid_out_of_band": True, "charge": None}, vr.OWNER, "outside_stripe"),
            "authorized, not captured": ({"charge": {**invoice()["charge"], "captured": False, "amount_captured": 0}}, vr.UNCONFIRMED, "charge_incomplete"),
            "captured flag missing": ({"charge": {k: v for k, v in invoice()["charge"].items() if k != "captured"}}, vr.UNCONFIRMED, "charge_incomplete"),
            "partly captured": ({"charge": {**invoice()["charge"], "amount_captured": 6000}}, vr.UNCONFIRMED, "charge_incomplete"),
            "disputed": ({"charge": {**invoice()["charge"], "disputed": True}}, vr.UNCONFIRMED, "disputed"),
        }
        for label, (change, verification, settlement) in cases.items():
            with self.subTest(label):
                record = vr.stripe_invoice_record({**invoice(), **change}, "acct_1")
                self.assertEqual((record["verification"], record["settlement"]), (verification, settlement))
        # A credit note that refunded the charge is subtracted once, not twice.
        self.assertEqual(vr.stripe_invoice_record(invoice(refunded=3000, credit_notes=3000), "acct_1")["refunded_minor"], 3000)
        self.assertEqual(vr.stripe_invoice_record(invoice(refunded=0, credit_notes=2000), "acct_1")["refunded_minor"], 2000)
        self.assertIsNone(vr.stripe_invoice_record(invoice(status="open"), "acct_1"))
        self.assertIsNone(vr.stripe_invoice_record(invoice(currency="xyz"), "acct_1"))
        broken_time = invoice()
        broken_time["status_transitions"] = {"paid_at": 10 ** 20}
        self.assertIsNone(vr.stripe_invoice_record(broken_time, "acct_1"))

    def test_unconfirmed_stripe_payments_are_shown_but_never_counted(self):
        record = vr.stripe_invoice_record({**invoice(), "charge": None}, "acct_1")
        result = receipt([record], [followup("2026-10-05T09:00:00Z")])
        item = result["items"][0]
        self.assertFalse(item["linked"])
        self.assertIn("Payment not confirmed", item["reason"])
        self.assertEqual(result["totals"]["cad"]["linked_verified_minor"], 0)
        self.assertEqual(result["totals"]["cad"]["paid_verified_minor"], 0)
        self.assertEqual(result["totals"]["cad"]["paid_unconfirmed_minor"], 12000)

    def test_invalid_windows_and_pathological_dates_are_rejected(self):
        for bad in ("abc", "3", "1000", "-5", "7.5"):
            with self.subTest(bad=bad), self.assertRaises(vr.EvidenceError):
                vr.parse_window(bad)
        now = dt.datetime(2026, 11, 6, tzinfo=UTC)
        for since, until in (("9999-12-30", "9999-12-31"), ("0001-01-01", "0001-01-02"), ("2026-13-01", "")):
            with self.subTest(since=since), self.assertRaises(vr.EvidenceError):
                vr.parse_period(since, until, "UTC", now)
        self.assertIsNone(vr._utc(10 ** 20))
        self.assertIsNone(vr._utc("9999-12-31T23:59:59Z"))
        self.assertIsNone(vr._utc(True))

    def test_a_corrupt_evidence_file_fails_closed_and_is_never_overwritten(self):
        path = os.path.join(_TEST_DATA.name, f"rev-{uuid.uuid4().hex}.json")
        with open(path, "w") as handle:
            handle.write('{"ws": {"records": {"stripe:in_1": ')  # truncated write
        store = vr.RevenueStore(path)
        with self.assertRaises(vr.EvidenceStoreError):
            store.records("ws")
        with self.assertRaises(vr.EvidenceStoreError):
            store.upsert_stripe("ws", [], "2026-11-06T00:00:00Z", complete=True)
        with open(path) as handle:
            self.assertEqual(handle.read(), '{"ws": {"records": {"stripe:in_1": ')
        self.assertEqual(vr.RevenueStore(os.path.join(_TEST_DATA.name, "missing.json")).records("ws"), [])

    def test_day_only_payments_never_invent_a_same_day_order(self):
        store = vr.RevenueStore(os.path.join(_TEST_DATA.name, f"rev-{uuid.uuid4().hex}.json"))
        now = dt.datetime(2026, 10, 20, 23, 0, tzinfo=UTC)
        lead = {"id": "b", "email": "ben@example.com", "name": "Ben"}
        day_only, _ = store.add_manual("ws", {"amount": "80", "currency": "cad", "paid_at": "2026-10-20", "idempotency_key": "day-only-0001"},
                                       lead=lead, recorded_by="o", now=now, timezone_name="America/Toronto")
        self.assertEqual((day_only["paid_precision"], day_only["paid_at"]), ("day", "2026-10-20T04:00:00Z"))
        timed, _ = store.add_manual("ws", {"amount": "80", "currency": "cad", "paid_at": "2026-10-20", "paid_time": "16:30",
                                           "idempotency_key": "timed-00001"}, lead=lead, recorded_by="o", now=now, timezone_name="America/Toronto")
        self.assertEqual(timed["paid_at"], "2026-10-20T20:30:00Z")
        same_day_booking = {"id": "appt", "lead_id": "b", "status": "completed", "created_at": "2026-10-20T15:00:00Z"}
        follow = [followup("2026-10-18T12:00:00Z", lead_id="b")]
        day_only, timed = dict(day_only, booking_ref="appt"), dict(timed, booking_ref="appt")
        unknown = receipt([day_only], follow, [same_day_booking])
        self.assertFalse(unknown["items"][0]["linked"])
        self.assertIn("order is unknown", unknown["items"][0]["reason"])
        self.assertEqual(unknown["totals"]["cad"]["linked_owner_recorded_minor"], 0)
        known = receipt([timed], follow, [same_day_booking])
        self.assertTrue(known["items"][0]["linked"])
        earlier_booking = dict(same_day_booking, created_at="2026-10-19T15:00:00Z")
        self.assertTrue(receipt([day_only], follow, [earlier_booking])["items"][0]["linked"])
        with self.assertRaises(vr.EvidenceError):
            store.add_manual("ws", {"amount": "80", "currency": "cad", "paid_at": "2026-10-20", "paid_time": "23:30",
                                    "idempotency_key": "future-time-1"}, lead=lead, recorded_by="o", now=now, timezone_name="America/Toronto")

    def test_a_partial_sync_reports_payments_whose_refunds_were_not_rechecked(self):
        store = vr.RevenueStore(os.path.join(_TEST_DATA.name, f"rev-{uuid.uuid4().hex}.json"))
        old = vr.stripe_invoice_record(invoice("in_old"), "acct")
        new = vr.stripe_invoice_record(invoice("in_new"), "acct")
        store.upsert_stripe("ws", [old, dict(new)], "2026-11-01T00:00:00Z", complete=True)
        result = store.upsert_stripe("ws", [dict(new)], "2026-11-06T00:00:00Z", complete=False)
        self.assertEqual((result["not_refreshed"], result["complete"]), (1, False))
        built = receipt(store.records("ws"), last_sync=store.meta("ws")["last_sync"])
        stale = {item["id"]: item["refunds_stale"] for item in built["items"]}
        self.assertEqual(stale, {"stripe:in_old": True, "stripe:in_new": False})
        self.assertEqual((built["sync"]["complete"], built["sync"]["not_refreshed"], built["sync"]["stale_items"]), (False, 1, 1))

    def test_counts_only_a_follow_up_then_invoice_then_payment(self):
        record = vr.stripe_invoice_record(invoice(), "acct_1")
        linked = receipt([record], [followup("2026-10-05T09:00:00Z")])
        item = linked["items"][0]
        self.assertTrue(item["linked"])
        self.assertEqual(item["followup"]["channel"], "email")
        self.assertEqual(item["confirmation"]["kind"], "invoice")
        self.assertEqual(linked["totals"]["cad"]["linked_verified_minor"], 12000)
        self.assertIn("does not prove", linked["rules"]["not_causal"])

        after = receipt([record], [followup("2026-10-11T09:00:00Z")])  # follow-up after the invoice
        self.assertFalse(after["items"][0]["linked"])
        self.assertEqual(after["totals"]["cad"]["linked_verified_minor"], 0)
        self.assertEqual(after["totals"]["cad"]["paid_verified_minor"], 12000)

        too_early = receipt([record], [followup("2026-09-01T09:00:00Z")])  # outside the 30-day window
        self.assertIn("No recorded follow-up in the 30 days", too_early["items"][0]["reason"])

    def test_owner_recorded_payment_links_through_a_booking_and_stays_separate(self):
        manual = {"id": "manual:k1", "source": "manual", "verification": vr.OWNER, "amount_minor": 8000, "refunded_minor": 0,
                  "currency": "cad", "paid_at": "2026-10-20T18:00:00Z", "lead_id": "b", "customer_email": "ben@example.com", "livemode": True,
                  "booking_ref": "appt-1"}
        booking = {"id": "appt-1", "lead_id": "b", "lead_email": "ben@example.com", "status": "completed",
                   "created_at": "2026-10-15T12:00:00Z", "appointment_time": "2026-10-20T17:00:00"}
        cancelled = dict(booking, id="appt-2", status="cancelled")
        result = receipt([manual], [followup("2026-10-14T12:00:00Z", lead_id="b")], [booking])
        self.assertTrue(result["items"][0]["linked"])
        self.assertEqual(result["items"][0]["confirmation"]["kind"], "booking")
        self.assertEqual(result["totals"]["cad"]["linked_owner_recorded_minor"], 8000)
        self.assertEqual(result["totals"]["cad"]["linked_verified_minor"], 0)
        cancelled_ref = receipt([dict(manual, booking_ref="appt-2")], [followup("2026-10-14T12:00:00Z", lead_id="b")], [booking, cancelled])
        self.assertEqual(cancelled_ref["items"][0]["reason"], "The booking selected for this payment no longer exists or was cancelled")
        unselected = receipt([dict(manual, booking_ref="")], [followup("2026-10-14T12:00:00Z", lead_id="b")], [booking])
        self.assertEqual(unselected["items"][0]["reason"], "No booking selected for this payment")
        self.assertEqual(unselected["totals"]["cad"]["linked_owner_recorded_minor"], 0)

    def test_an_unrelated_older_booking_never_links_a_later_payment(self):
        # 2025: a follow-up and a booking. 2026: an unrelated payment from the same customer.
        old_follow = [followup("2025-05-01T12:00:00Z", lead_id="b")]
        old_booking = {"id": "appt-old", "lead_id": "b", "status": "completed", "created_at": "2025-05-02T12:00:00Z"}
        manual = {"id": "manual:k2", "source": "manual", "verification": vr.OWNER, "amount_minor": 9000, "refunded_minor": 0,
                  "currency": "cad", "paid_at": "2026-10-20T18:00:00Z", "lead_id": "b", "livemode": True, "booking_ref": ""}
        stripe_paid = vr.stripe_invoice_record(invoice("in_late", email="ben@example.com", created="2026-10-10T10:00:00",
                                                       paid="2026-10-12T15:00:00"), "acct")
        result = receipt([manual, stripe_paid], old_follow, [old_booking])
        self.assertTrue(all(not item["linked"] for item in result["items"]))
        self.assertEqual(result["totals"]["cad"]["linked_verified_minor"], 0)
        self.assertEqual(result["totals"]["cad"]["linked_owner_recorded_minor"], 0)
        # An invoice links only through its own finalization, or a booking it explicitly carries.
        no_finalized = dict(stripe_paid, invoice_issued_at="")
        self.assertFalse(receipt([no_finalized], [followup("2026-10-05T09:00:00Z", lead_id="b")], [old_booking])["items"][0]["linked"])
        carried = dict(no_finalized, booking_ref="appt-new")
        new_booking = {"id": "appt-new", "lead_id": "b", "status": "scheduled", "created_at": "2026-10-06T12:00:00Z"}
        linked = receipt([carried], [followup("2026-10-05T09:00:00Z", lead_id="b")], [old_booking, new_booking])
        self.assertTrue(linked["items"][0]["linked"])
        self.assertEqual(linked["items"][0]["confirmation"]["id"], "appt-new")

    def test_owner_must_pick_one_of_this_customers_bookings(self):
        store = vr.RevenueStore(os.path.join(_TEST_DATA.name, f"rev-{uuid.uuid4().hex}.json"))
        lead = {"id": "b", "email": "ben@example.com"}
        mine = {"id": "appt-b", "lead_id": "b", "status": "completed", "created_at": "2026-10-01T12:00:00Z"}
        theirs = {"id": "appt-x", "lead_id": "x", "status": "completed", "created_at": "2026-10-01T12:00:00Z"}
        cancelled = {"id": "appt-c", "lead_id": "b", "status": "cancelled", "created_at": "2026-10-01T12:00:00Z"}
        now = dt.datetime(2026, 10, 20, tzinfo=UTC)
        base = {"amount": "10", "currency": "cad", "paid_at": "2026-10-19"}
        for bad in ("appt-x", "appt-c", "missing"):
            with self.subTest(bad=bad), self.assertRaises(vr.EvidenceError):
                store.add_manual("ws", {**base, "appointment_id": bad, "idempotency_key": f"pick-{bad}-1"}, lead=lead,
                                 recorded_by="o", now=now, bookings=[mine, theirs, cancelled])
        record, _ = store.add_manual("ws", {**base, "appointment_id": "appt-b", "idempotency_key": "pick-ok-001"}, lead=lead,
                                     recorded_by="o", now=now, bookings=[mine, theirs, cancelled])
        self.assertEqual(record["booking_ref"], "appt-b")

    def test_refunds_test_mode_ambiguous_contacts_currencies_and_period(self):
        follow = [followup("2026-10-05T09:00:00Z"), followup("2026-10-05T09:00:00Z", lead_id="", email="ana@example.com")]
        records = [
            vr.stripe_invoice_record(invoice("in_part", refunded=2000), "acct"),
            vr.stripe_invoice_record(invoice("in_full", refunded=12000), "acct"),
            vr.stripe_invoice_record(invoice("in_test", livemode=False), "acct"),
            vr.stripe_invoice_record(invoice("in_usd", currency="usd", amount=5000), "acct"),
            vr.stripe_invoice_record(invoice("in_old", paid="2026-09-20T10:00:00", created="2026-09-19T10:00:00"), "acct"),
        ]
        result = receipt(records, follow)
        by_id = {item["id"]: item for item in result["items"]}
        self.assertNotIn("stripe:in_old", by_id)  # outside the period
        self.assertEqual(by_id["stripe:in_part"]["net_minor"], 10000)
        self.assertEqual(by_id["stripe:in_full"]["reason"], "Fully refunded")
        self.assertIn("test-mode", by_id["stripe:in_test"]["reason"])
        self.assertEqual(result["totals"]["cad"]["linked_verified_minor"], 10000)  # never test or refunded money
        self.assertEqual(result["totals"]["usd"]["linked_verified_minor"], 5000)  # never added to CAD
        twins = [{"id": "a", "email": "ana@example.com"}, {"id": "z", "email": "ana@example.com"}]
        ambiguous = receipt([records[0]], follow, leads=twins)
        self.assertEqual(ambiguous["items"][0]["reason"], "No single matching contact in RetainAI")

    def test_legacy_follow_ups_come_only_from_real_sends(self):
        rows = vr.collect_followups("ws", log_entries=[], notifications=[
            {"subject": "AI email sent", "lead_email": "Ana@Example.com", "timestamp": "2026-10-05T09:00:00Z"},
            {"subject": "Appointment created", "lead_email": "ana@example.com", "timestamp": "2026-10-05T09:00:00Z"},
            {"subject": "AI email sent", "lead_email": "ana@example.com", "timestamp": "2026-10-05T09:00:20Z"},  # same minute
        ], chats={"a": [{"direction": "outbound", "time": "2026-10-06T09:00:00Z"},
                        {"direction": "inbound", "time": "2026-10-06T10:00:00Z"},
                        {"direction": "outbound", "status": "failed", "time": "2026-10-06T11:00:00Z"}]})
        self.assertEqual(sorted((row["channel"], row["lead_email"] or row["lead_id"]) for row in rows),
                         [("email", "ana@example.com"), ("whatsapp", "a")])

    def test_csv_export_neutralises_formulas(self):
        record = vr.stripe_invoice_record(invoice(), "acct")
        record["customer_name"] = "=HYPERLINK(\"http://x\")"
        text = vr.receipt_csv(receipt([record], [followup("2026-10-05T09:00:00Z")], leads=[{"id": "a", "email": "ana@example.com"}]))
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("Provider-verified (Stripe charge)", text)
        self.assertIn("120.00", text)


class FakeListing:
    def __init__(self, items):
        self.items = items

    def auto_paging_iter(self):
        return iter(self.items)


class ValueReceiptApiTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.member = f"member-{uuid.uuid4().hex[:8]}@example.com"
        self.other = f"other-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {
            self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                         "security_version": 0, "stripe_account_id": "acct_owner", "timezone": "America/Toronto"},
            self.other: {"email": self.other, "role": "owner", "org_id": self.other, "status": "active",
                         "security_version": 0, "stripe_account_id": "acct_other"},
            f"user::{self.member}": {"email": self.member, "role": "member", "org_id": self.owner, "security_version": 0},
            self.member: {"email": self.member, "role": "member", "org_id": self.owner, "status": "active", "security_version": 0},
        }
        patcher = patch.object(retainai, "load_users", side_effect=lambda: self.users)
        patcher.start()
        self.addCleanup(patcher.stop)
        storage.save_user_leads(self.owner, [{"id": "a", "name": "Ana", "email": "ana@example.com"}])
        storage.save_user_leads(self.other, [{"id": "x", "name": "Xu", "email": "ana@example.com"}])

    def client(self, email):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = email
            signed["org_email"] = self.owner if email == self.member else email
            signed["security_version"] = 0
        return client

    def sync(self, email, invoices):
        with patch.object(retainai.stripe.Invoice, "list", return_value=FakeListing(invoices)) as listed:
            response = self.client(email).post("/api/value-receipt/sync", headers=ORIGIN)
        return response, listed

    def test_only_the_workspace_owner_can_read_or_change_revenue(self):
        anonymous = retainai.app.test_client().get("/api/value-receipt")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(self.client(self.member).get("/api/value-receipt").status_code, 403)
        self.assertEqual(self.client(self.member).post("/api/value-receipt/sync", headers=ORIGIN).status_code, 403)
        self.assertEqual(self.client(self.owner).get("/api/value-receipt").status_code, 200)

    def test_sync_reads_only_the_owners_connected_account_and_is_idempotent(self):
        now = dt.datetime.now(UTC)
        recent = invoice(created=(now - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S"),
                         paid=(now - dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"))
        response, listed = self.sync(self.owner, [recent])
        self.assertEqual(response.get_json()["added"], 1)
        self.assertEqual(listed.call_args.kwargs["stripe_account"], "acct_owner")
        self.assertEqual(listed.call_args.kwargs["status"], "paid")
        self.assertEqual(listed.call_args.kwargs["stripe_version"], "2023-10-16")
        self.assertEqual(listed.call_args.kwargs["expand"], ["data.charge"])
        refunded = dict(recent, charge={**recent["charge"], "amount_refunded": 2000})
        again, _ = self.sync(self.owner, [refunded])
        self.assertEqual((again.get_json()["added"], again.get_json()["updated"]), (0, 1))
        app_value.followup_log.record(self.owner, lead_id="a", channel="email", source="test",
                                      sent_at=(now - dt.timedelta(days=5)).isoformat())
        body = self.client(self.owner).get("/api/value-receipt").get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["totals"]["cad"]["linked_verified_minor"], 10000)
        # Another workspace with a same-email contact sees none of it.
        other = self.client(self.other).get("/api/value-receipt").get_json()
        self.assertEqual(other["items"], [])

    def test_a_capped_sync_is_reported_as_partial(self):
        now = dt.datetime.now(UTC)
        stamp = lambda days: (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        invoices = [invoice(f"in_{n}", created=stamp(n + 3), paid=stamp(n + 2)) for n in range(3)]
        with patch.object(app_value, "MAX_SYNC_INVOICES", 2):
            response, _ = self.sync(self.owner, invoices)
        body = response.get_json()
        self.assertEqual((body["truncated"], body["complete"], body["read"]), (True, False, 2))
        receipt_body = self.client(self.owner).get("/api/value-receipt").get_json()
        self.assertFalse(receipt_body["sync"]["complete"])

    def test_bad_window_returns_400_and_an_unreadable_store_returns_503_without_writing(self):
        self.assertEqual(self.client(self.owner).get("/api/value-receipt?window_days=abc").status_code, 400)
        self.assertEqual(self.client(self.owner).get("/api/value-receipt?window_days=999").status_code, 400)
        self.assertEqual(self.client(self.owner).get("/api/value-receipt?since=9999-12-30&until=9999-12-31").status_code, 400)
        original = None
        if os.path.exists(app_value.REVENUE_FILE):
            with open(app_value.REVENUE_FILE, "rb") as handle:
                original = handle.read()
        try:
            with open(app_value.REVENUE_FILE, "w") as handle:
                handle.write("{not json")
            client = self.client(self.owner)
            self.assertEqual(client.get("/api/value-receipt").status_code, 503)
            payment = {"lead_id": "a", "amount": "5", "currency": "cad", "paid_at": "2026-11-01", "idempotency_key": "corrupt-0001"}
            self.assertEqual(client.post("/api/value-receipt/payments", json=payment, headers=ORIGIN).status_code, 503)
            with open(app_value.REVENUE_FILE) as handle:
                self.assertEqual(handle.read(), "{not json")
        finally:
            if original is None:
                os.remove(app_value.REVENUE_FILE)
            else:
                with open(app_value.REVENUE_FILE, "wb") as handle:
                    handle.write(original)

    def test_sync_needs_a_connected_account_and_reports_stripe_failures(self):
        self.users[self.owner]["stripe_account_id"] = ""
        self.assertEqual(self.client(self.owner).post("/api/value-receipt/sync", headers=ORIGIN).status_code, 400)
        self.users[self.owner]["stripe_account_id"] = "acct_owner"
        with patch.object(retainai.stripe.Invoice, "list", side_effect=RuntimeError("boom")):
            failed = self.client(self.owner).post("/api/value-receipt/sync", headers=ORIGIN)
        self.assertEqual((failed.status_code, failed.get_json()["error"]), (502, "stripe_read_failed"))

    def test_owner_recorded_payments_are_validated_idempotent_and_removable(self):
        client = self.client(self.owner)
        payment = {"lead_id": "a", "amount": "80.00", "currency": "CAD", "paid_at": "2026-11-01", "reference": "Cash",
                   "idempotency_key": "pay-0001-abcd"}
        first = client.post("/api/value-receipt/payments", json=payment, headers=ORIGIN)
        self.assertEqual(first.status_code, 201)
        record = first.get_json()["record"]
        self.assertEqual((record["verification"], record["amount_minor"], record["recorded_by"]), ("owner_recorded", 8000, self.owner))
        self.assertEqual(client.post("/api/value-receipt/payments", json=payment, headers=ORIGIN).status_code, 200)
        changed = dict(payment, amount="90.00")
        self.assertEqual(client.post("/api/value-receipt/payments", json=changed, headers=ORIGIN).status_code, 409)
        for bad in ({**payment, "lead_id": "x"}, {**payment, "idempotency_key": "k"}, {**payment, "currency": "btc"},
                    {**payment, "paid_at": "2099-01-01"}, {**payment, "amount": "1.234"}, ["not", "an", "object"],
                    {**payment, "appointment_id": "not-a-booking-of-this-customer", "idempotency_key": "pay-0002-abcd"}):
            with self.subTest(bad=bad):
                self.assertEqual(client.post("/api/value-receipt/payments", json=bad, headers=ORIGIN).status_code, 400)
        refund = client.post(f"/api/value-receipt/payments/{record['id']}/refund", json={"refunded_amount": "20"}, headers=ORIGIN)
        self.assertEqual(refund.get_json()["record"]["refunded_minor"], 2000)
        too_big = client.post(f"/api/value-receipt/payments/{record['id']}/refund", json={"refunded_amount": "100"}, headers=ORIGIN)
        self.assertEqual(too_big.status_code, 400)
        # Another workspace can't touch it; Stripe records can't be edited or removed here.
        self.assertEqual(self.client(self.other).delete(f"/api/value-receipt/payments/{record['id']}", headers=ORIGIN).status_code, 404)
        self.assertEqual(client.delete("/api/value-receipt/payments/stripe:in_1", headers=ORIGIN).status_code, 404)
        self.assertEqual(client.delete(f"/api/value-receipt/payments/{record['id']}", headers=ORIGIN).status_code, 200)

    def test_export_is_csv_for_the_owner_only(self):
        response = self.client(self.owner).get("/api/value-receipt/export.csv?since=2026-10-01&until=2026-10-31")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("text/csv"))
        self.assertIn("retainai-value-receipt-2026-10-01-to-2026-10-31.csv", response.headers["Content-Disposition"])
        self.assertTrue(response.get_data(as_text=True).startswith("paid_at_utc,paid_time_known,customer"))
        self.assertEqual(self.client(self.member).get("/api/value-receipt/export.csv").status_code, 403)
        self.assertEqual(self.client(self.owner).get("/api/value-receipt?since=2026-12-01&until=2026-01-01").status_code, 400)

    def test_platform_webhook_ignores_connected_account_events(self):
        self.users[self.owner]["billing_status"] = "canceled"
        event = {"id": "evt_connect", "type": "invoice.paid", "account": "acct_owner", "created": 1,
                 "data": {"object": {"object": "invoice", "customer_email": "ana@example.com",
                                     "metadata": {"user_email": self.owner}}}}
        with patch.object(retainai.stripe.Webhook, "construct_event", return_value=event), \
                patch.object(retainai, "save_users") as saved:
            response = retainai.app.test_client().post("/api/stripe/webhook", data=json.dumps(event),
                                                       headers={"stripe-signature": "t=1,v1=x"})
        self.assertEqual(response.status_code, 200)
        saved.assert_not_called()
        self.assertEqual(self.users[self.owner]["billing_status"], "canceled")


if __name__ == "__main__":
    unittest.main()
