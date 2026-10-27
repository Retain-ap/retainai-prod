"""Regression tests for the SendGrid unsubscribe-footer tool (no network)."""

import os
import tempfile
import unittest


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import sendgrid_unsubscribe_footer as footer  # noqa: E402


class SendGridFooterTests(unittest.TestCase):
    def test_covers_every_customer_facing_template_the_app_sends(self):
        self.assertEqual(
            set(footer.CUSTOMER_TEMPLATES),
            {
                retainai.SG_TEMPLATE_BIRTHDAY,
                retainai.SG_TEMPLATE_FOLLOWUP_LEAD,
                retainai.SG_TEMPLATE_REENGAGE_LEAD,
                retainai.SG_TEMPLATE_APOLOGY_LEAD,
                retainai.SG_TEMPLATE_UPSELL_LEAD,
            },
        )

    def test_footer_goes_before_body_close(self):
        html_body, plain = footer.add_footer("<html><body><p>Hi</p></body></html>", "Hi")
        self.assertTrue(footer.has_unsubscribe_link(html_body))
        self.assertLess(html_body.index("unsubscribe_url"), html_body.index("</body>"))
        self.assertIn("{{unsubscribe_url}}", plain)

    def test_footer_appended_without_body_tag_and_blank_plain_left_alone(self):
        html_body, plain = footer.add_footer("<p>Hi {{lead_name}}</p>", "")
        self.assertTrue(html_body.startswith("<p>Hi {{lead_name}}</p>"))
        self.assertTrue(footer.has_unsubscribe_link(html_body))
        self.assertEqual(plain, "")

    def test_existing_links_are_detected(self):
        self.assertTrue(footer.has_unsubscribe_link('<a href="{{unsubscribe_url}}">x</a>'))
        self.assertTrue(footer.has_unsubscribe_link('<a href="{{{ unsubscribe_link }}}">x</a>'))
        self.assertFalse(footer.has_unsubscribe_link("<a href=\"<%asm_group_unsubscribe_raw_url%>\">x</a>"))


if __name__ == "__main__":
    unittest.main()
