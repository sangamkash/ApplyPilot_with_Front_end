"""Playwright-based Browser Controller for AI Application Providers.

Controls an existing Chrome instance connected via CDP on http://localhost:{port}.
Provides high-level actions used by LLM agents:
- navigate
- inspect/snapshot page elements & forms
- autofill fields
- upload resume/cover letter
- click buttons
- verify submission evidence
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from applypilot.apply.providers.verification import verify_page_submission

logger = logging.getLogger(__name__)


class BrowserController:
    """Controls a Chrome browser instance connected over CDP."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def __enter__(self) -> "BrowserController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def connect(self) -> None:
        """Connect to the Chrome instance on CDP port."""
        if self._browser is not None:
            return

        self._playwright = sync_playwright().start()
        cdp_url = f"http://127.0.0.1:{self.port}"
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
            # Pick existing context or create one
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context()

            # Track newly opened pages/popups automatically
            self._context.on("page", self._on_new_page)

            # Pick active page or open one
            if self._context.pages:
                self._page = self._context.pages[-1]
            else:
                self._page = self._context.new_page()

            logger.info("Connected to Chrome via CDP on %s", cdp_url)
        except Exception as e:
            self.disconnect()
            raise RuntimeError(f"Failed to connect to Chrome on port {self.port}: {e}") from e

    def _on_new_page(self, page: Page) -> None:
        """Handler for when target site opens a popup or new tab (e.g. Apply on Company Site)."""
        logger.info("New browser tab/window detected: %s", page.url)
        self._page = page
        try:
            page.bring_to_front()
        except Exception:
            pass

    def disconnect(self) -> None:
        """Disconnect Playwright from Chrome without killing Chrome."""
        self._browser = None
        self._context = None
        self._page = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    @property
    def page(self) -> Page:
        if self._context and self._context.pages:
            if not self._page or self._page.is_closed() or self._page not in self._context.pages:
                self._page = self._context.pages[-1]
        elif not self._page or self._page.is_closed():
            if self._context:
                self._page = self._context.new_page()
            else:
                raise RuntimeError("Browser is not connected")
        return self._page

    def switch_to_tab(self, index_or_url: Any) -> dict:
        """Switch active page to another open tab by index (0, 1..) or URL/title substring."""
        if not self._context or not self._context.pages:
            return {"error": "No pages open"}
        pages = self._context.pages
        target = None
        if isinstance(index_or_url, int):
            if 0 <= index_or_url < len(pages):
                target = pages[index_or_url]
        else:
            q = str(index_or_url).lower()
            for p in pages:
                if q in (p.url or "").lower() or q in (p.title() or "").lower():
                    target = p
                    break
        if target:
            self._page = target
            try:
                target.bring_to_front()
            except Exception:
                pass
            return {"switched": True, "url": target.url, "title": target.title()}
        return {
            "error": f"Tab matching '{index_or_url}' not found",
            "open_tabs": [{"index": i, "url": p.url, "title": p.title()} for i, p in enumerate(pages)],
        }

    def navigate(self, url: str) -> dict:
        """Navigate to target application URL."""
        logger.info("Navigating to %s", url)
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        return {"url": self.page.url, "title": self.page.title()}

    def get_snapshot(self) -> dict:
        """Extract a structured summary of the current page including form fields and buttons."""
        p = self.page
        url = p.url
        title = p.title()

        # Extract open tabs summary
        open_tabs: List[dict] = []
        if self._context and self._context.pages:
            for i, pg in enumerate(self._context.pages):
                try:
                    open_tabs.append({
                        "index": i,
                        "url": pg.url,
                        "title": pg.title(),
                        "is_active": (pg == p),
                    })
                except Exception:
                    pass

        # Extract form inputs, textareas, selects
        fields_data: List[dict] = []
        try:
            raw_fields = p.evaluate("""() => {
                const results = [];
                const elements = document.querySelectorAll('input, textarea, select');
                for (const el of elements) {
                    if (el.type === 'hidden' || el.style.display === 'none' || el.style.visibility === 'hidden') {
                        continue;
                    }
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0 && el.type !== 'file') {
                        continue;
                    }

                    let label = '';
                    if (el.id) {
                        const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (lbl) label = lbl.innerText.trim();
                    }
                    if (!label && el.closest('label')) {
                        label = el.closest('label').innerText.trim();
                    }
                    if (!label) {
                        label = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                    }

                    results.push({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || 'text',
                        name: el.name || '',
                        id: el.id || '',
                        label: label.replace(/\\s+/g, ' ').slice(0, 100),
                        placeholder: el.placeholder || '',
                        required: el.required || el.getAttribute('aria-required') === 'true',
                        value: (el.type === 'password' || el.type === 'file') ? '' : (el.value || ''),
                    });
                }
                return results;
            }""")
            fields_data = raw_fields or []
        except Exception as e:
            logger.warning("Failed to evaluate form fields: %s", e)

        # Extract buttons
        buttons_data: List[dict] = []
        try:
            raw_buttons = p.evaluate("""() => {
                const results = [];
                const buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"], a[role="button"]');
                for (const b of buttons) {
                    const rect = b.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) continue;
                    const text = (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();
                    if (text) {
                        results.push({
                            text: text.replace(/\\s+/g, ' ').slice(0, 60),
                            type: b.type || 'button',
                            id: b.id || '',
                        });
                    }
                }
                return results;
            }""")
            buttons_data = raw_buttons or []
        except Exception as e:
            logger.warning("Failed to evaluate buttons: %s", e)

        # Extract body text snippet
        body_snippet = ""
        try:
            body_text = p.inner_text("body", timeout=2000)
            clean_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
            body_snippet = "\\n".join(clean_lines[:40])
        except Exception:
            pass

        return {
            "url": url,
            "title": title,
            "open_tabs": open_tabs,
            "fields_count": len(fields_data),
            "fields": fields_data[:50],  # cap for LLM context
            "buttons": buttons_data[:30],
            "text_preview": body_snippet[:1500],
        }

    def _fill_single_locator(self, loc, val: str) -> bool:
        """Helper to fill text, check radio/checkbox, or select option safely without throwing."""
        try:
            input_type = (loc.get_attribute("type") or "").lower()
            tag_name = loc.evaluate("el => el.tagName.toLowerCase()")
            if input_type in ("radio", "checkbox"):
                str_val = str(val).strip().lower()
                el_val = (loc.get_attribute("value") or "").lower()
                if str_val in ("yes", "true", "1", "checked", "on") or str_val == el_val:
                    loc.check(timeout=3000)
                elif str_val in ("no", "false", "0", "unchecked"):
                    if input_type == "checkbox":
                        loc.uncheck(timeout=3000)
                else:
                    loc.click(timeout=3000)
                return True
            elif tag_name == "select":
                loc.select_option(str(val), timeout=3000)
                return True
            else:
                loc.fill(str(val), timeout=3000)
                return True
        except Exception as e:
            logger.debug("Failed filling locator: %s", e)
            return False

    def fill_form_fields(self, fields_to_fill: List[Dict[str, str]]) -> Dict[str, Any]:
        """Fill multiple fields matching by label, placeholder, name, id, or selector.

        Args:
            fields_to_fill: list of dicts like [{"label": "First Name", "value": "Jane"}]
        """
        filled = []
        errors = []
        p = self.page

        for item in fields_to_fill:
            val = str(item.get("value", ""))
            label = item.get("label", "")
            name = item.get("name", "")
            selector = item.get("selector", "")
            placeholder = item.get("placeholder", "")

            success = False

            # Try by selector first if provided
            if selector:
                try:
                    loc = p.locator(selector).first
                    if loc.count() > 0 and self._fill_single_locator(loc, val):
                        filled.append(f"selector:{selector}")
                        continue
                except Exception:
                    pass

            # Try by label
            if label:
                try:
                    loc = p.get_by_label(re.compile(re.escape(label), re.IGNORECASE)).first
                    if loc.count() > 0 and self._fill_single_locator(loc, val):
                        filled.append(f"label:{label}")
                        continue
                except Exception:
                    pass

            # Try by placeholder
            if placeholder or label:
                target_ph = placeholder or label
                try:
                    loc = p.get_by_placeholder(re.compile(re.escape(target_ph), re.IGNORECASE)).first
                    if loc.count() > 0 and self._fill_single_locator(loc, val):
                        filled.append(f"placeholder:{target_ph}")
                        continue
                except Exception:
                    pass

            # Try by name or id attribute
            target_name = name or label.lower().replace(" ", "_")
            for sel in [f"input[name*='{target_name}' i]", f"textarea[name*='{target_name}' i]", f"#{target_name}"]:
                try:
                    loc = p.locator(sel).first
                    if loc.count() > 0 and self._fill_single_locator(loc, val):
                        filled.append(sel)
                        success = True
                        break
                except Exception:
                    pass

            if not success:
                errors.append(f"Could not locate field for: {item}")

        return {"filled": filled, "unfilled": errors}

    def upload_file(self, file_path: str, selector: Optional[str] = None) -> bool:
        """Upload a file (e.g. resume PDF) to a file input on the page."""
        p = self.page
        resolved = Path(file_path).resolve()

        # If a .txt file is provided, auto-switch to or generate matching .pdf
        if resolved.suffix.lower() == ".txt":
            if resolved.with_suffix(".pdf").exists():
                resolved = resolved.with_suffix(".pdf")
            else:
                try:
                    from applypilot.scoring.pdf import convert_to_pdf
                    converted = convert_to_pdf(resolved)
                    if converted.exists():
                        resolved = converted
                except Exception:
                    pass

        if not resolved.exists():
            raise FileNotFoundError(f"File to upload does not exist: {file_path}")

        # If specific selector is given
        if selector:
            try:
                p.locator(selector).first.set_input_files(str(resolved))
                time.sleep(1)
                return True
            except Exception as e:
                logger.debug("Failed setting input files on selector %s: %s", selector, e)

        # Look for matching file inputs
        file_inputs = p.locator("input[type='file']")
        count = file_inputs.count()
        if count > 0:
            is_cover = "cover" in str(resolved.name).lower()
            # First pass: look for semantically matching file input
            for i in range(count):
                inp = file_inputs.nth(i)
                inp_meta = ""
                try:
                    inp_meta = (
                        (inp.get_attribute("name") or "") + " " +
                        (inp.get_attribute("id") or "") + " " +
                        (inp.get_attribute("aria-label") or "")
                    ).lower()
                except Exception:
                    pass

                if is_cover and "cover" not in inp_meta and count > 1:
                    continue
                if not is_cover and "cover" in inp_meta and count > 1:
                    continue

                try:
                    inp.set_input_files(str(resolved))
                    time.sleep(1.5)
                    logger.info("Successfully uploaded file %s to file input #%d", resolved.name, i)
                    return True
                except Exception as e:
                    logger.debug("Error uploading to input[type=file] #%d: %s", i, e)

            # Fallback pass: upload to first input that succeeds
            for i in range(count):
                try:
                    file_inputs.nth(i).set_input_files(str(resolved))
                    time.sleep(1.5)
                    logger.info("Uploaded file %s to input #%d", resolved.name, i)
                    return True
                except Exception:
                    pass

        return False

    def click_element(self, selector_or_text: str) -> bool:
        """Click a button, link, or element by text or selector."""
        p = self.page
        # Try direct selector
        try:
            loc = p.locator(selector_or_text).first
            if loc.is_visible():
                loc.click(timeout=5000)
                time.sleep(1.5)
                return True
        except Exception:
            pass

        # Try by button text
        try:
            loc = p.get_by_role("button", name=re.compile(re.escape(selector_or_text), re.IGNORECASE)).first
            if loc.is_visible():
                loc.click(timeout=5000)
                time.sleep(1.5)
                return True
        except Exception:
            pass

        # Try by link text
        try:
            loc = p.get_by_role("link", name=re.compile(re.escape(selector_or_text), re.IGNORECASE)).first
            if loc.is_visible():
                loc.click(timeout=5000)
                time.sleep(1.5)
                return True
        except Exception:
            pass

        # Try by text locator
        try:
            loc = p.get_by_text(re.compile(re.escape(selector_or_text), re.IGNORECASE)).first
            if loc.is_visible():
                loc.click(timeout=5000)
                time.sleep(1.5)
                return True
        except Exception:
            pass

        return False

    def select_option(self, selector_or_label: str, value: str) -> bool:
        """Select option from a <select> element."""
        p = self.page
        try:
            p.locator(selector_or_label).first.select_option(value)
            return True
        except Exception:
            pass
        try:
            p.get_by_label(re.compile(re.escape(selector_or_label), re.IGNORECASE)).first.select_option(label=value)
            return True
        except Exception:
            pass
        return False

    def evaluate(self, script: str) -> Any:
        """Execute JavaScript expression or function in the page."""
        return self.page.evaluate(script)

    def wait(self, seconds: float = 2.0) -> None:
        """Pause execution for specified seconds."""
        time.sleep(seconds)

    def verify_submission(self) -> Tuple[bool, str]:
        """Run submission verification on the current page."""
        return verify_page_submission(self.page)
