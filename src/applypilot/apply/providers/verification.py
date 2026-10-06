"""Application submission verification logic.

Enforces Requirement 5:
Never set APPLIED merely because the AI process started, completed, or returned successfully.
Set APPLIED only after there is strong evidence that the application was actually submitted successfully.
If submission cannot be verified, use failure/pending status mechanism.
"""

import logging
import re
import time
from typing import Tuple
from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)

# Strong positive submission confirmation indicators (text in body or headings)
CONFIRMATION_PATTERNS = [
    r"application\s+submitted",
    r"thank\s+you\s+for\s+applying",
    r"thank\s+you\s+for\s+your\s+application",
    r"we('ve|\s+have)?\s+received\s+your\s+application",
    r"your\s+application\s+has\s+been\s+received",
    r"your\s+application\s+was\s+submitted",
    r"your\s+application\s+has\s+been\s+submitted",
    r"application\s+(was\s+)?successfully\s+submitted",
    r"application\s+received",
    r"thanks\s+for\s+applying",
    r"thanks\s+for\s+your\s+interest",
    r"application\s+complete",
    r"application\s+was\s+sent",
    r"application\s+successfully\s+sent",
    r"you('ve|\s+have)?\s+applied",
    r"congratulations,\s+your\s+application",
]

# URL confirmation keywords
CONFIRMATION_URL_PATTERNS = [
    r"/confirmation",
    r"/confirm",
    r"/applied",
    r"/thank-you",
    r"/thank_you",
    r"/thankyou",
    r"/submitted",
    r"/success",
    r"/application-submitted",
    r"/application_submitted",
    r"/application-complete",
    r"/done",
]

# Negative error markers that show submission was rejected or blocked
ERROR_PATTERNS = [
    r"please\s+fix\s+the\s+following\s+errors",
    r"required\s+fields?\s+(are|is)\s+missing",
    r"there\s+was\s+an\s+error\s+submitting",
    r"submission\s+failed",
    r"failed\s+to\s+submit",
    r"error\s+submitting\s+application",
    r"please\s+correct\s+the\s+errors\s+below",
    r"fix\s+highlighted\s+errors",
    r"captcha\s+verification\s+failed",
]


def verify_page_submission(page: Page) -> Tuple[bool, str]:
    """Verify strong evidence of actual application submission on an open Playwright page.

    Returns:
        (is_verified, reason_or_evidence)
    """
    try:
        url = page.url or ""
        lower_url = url.lower()

        # Check for error indicators first
        body_text = page.inner_text("body", timeout=3000) if page.locator("body").count() > 0 else ""
        lower_text = body_text.lower()

        for err_pattern in ERROR_PATTERNS:
            match = re.search(err_pattern, lower_text)
            if match:
                return False, f"Submission error detected on page: '{match.group(0)}'"

        # Check confirmation URL
        for url_pattern in CONFIRMATION_URL_PATTERNS:
            if re.search(url_pattern, lower_url):
                return True, f"Verified by confirmation URL: '{url}'"

        # Check positive confirmation text patterns
        for text_pattern in CONFIRMATION_PATTERNS:
            match = re.search(text_pattern, lower_text)
            if match:
                return True, f"Verified by confirmation text: '{match.group(0)}'"

        # Check ATS specific elements
        ats_selectors = [
            ".application-confirmation",
            "#application_confirmation",
            ".application-submitted",
            "[data-qa='confirmation']",
            "[data-qa='application-submitted']",
            "[data-automation-id='applicationSubmitted']",
            "[data-automation-id='thankYouMessage']",
            ".thank-you-message",
            ".submission-success",
        ]
        for sel in ats_selectors:
            try:
                if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                    return True, f"Verified by ATS confirmation element: '{sel}'"
            except Exception:
                pass

        return False, "No strong evidence of submission found (missing confirmation text or URL)"

    except Exception as e:
        logger.warning("Error verifying page submission: %s", e)
        return False, f"Verification check failed: {str(e)}"


def verify_submission_on_port(port: int, wait_seconds: float = 0.5) -> Tuple[bool, str]:
    """Connect to running Chrome on CDP port and verify submission evidence across open tabs."""
    try:
        p = sync_playwright().start()
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            # Give page a brief moment if redirecting to confirmation
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            contexts = browser.contexts
            pages = []
            for ctx in contexts:
                pages.extend(ctx.pages)

            if not pages:
                return False, "No active pages found in browser to verify submission"

            # Check newest / active page first, then others
            for page in reversed(pages):
                verified, reason = verify_page_submission(page)
                if verified:
                    return True, reason

            return False, "No open tab shows confirmation of submission"
        finally:
            p.stop()
    except Exception as e:
        logger.warning("Failed to connect to CDP port %d for verification: %s", port, e)
        return False, f"Could not connect to browser for verification: {str(e)}"
