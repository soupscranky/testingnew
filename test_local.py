                      
"""
Generic form signup automation runner for GitHub Actions.
Uses DATA_CSV_B64 + NEXT_ROW (or single TEST_* envs).
"""

from seleniumbase import sb_cdp
import base64
import csv
import email as email_lib
import imaplib
import io
import os
import random
import re
import requests
import sys
import time


                                                                             
                     
                                                                             

TEST_EMAIL     = os.environ.get("TEST_EMAIL", "")
TEST_PASSWORD  = os.environ.get("TEST_PASSWORD", "")
TEST_FIRST     = os.environ.get("TEST_FIRST", "")
TEST_LAST      = os.environ.get("TEST_LAST", "")
TEST_COUNTRY   = os.environ.get("TEST_COUNTRY", "")
TEST_ZIP       = os.environ.get("TEST_ZIP", "")
FORM_URL       = os.environ.get("FORM_URL", "")


                                                                             
                     
                                                                             

def fetch_otp_from_gmail(
    target_email,
    imap_user,
    imap_pass,
    timeout=180,
    poll_interval=10,
):
    """
    Poll Gmail for the newest verification email forwarded from an
    Apple Hide My Email address and return its six-digit OTP.
    """
    otp_regex = re.compile(
        r"verification\s+code.*?\b(\d{6})\b",
        re.IGNORECASE | re.DOTALL,
    )

    target_email = target_email.lower()
    deadline = time.monotonic() + timeout
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        print(f"    [IMAP] Poll attempt {attempt} …")

        conn = None

        try:
            conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            conn.login(imap_user, imap_pass)
            conn.select("INBOX")

                                                                      
            status, data = conn.search(
                None,
                '(SUBJECT "Verification Code")',
            )

            if status != "OK":
                raise RuntimeError("IMAP search failed")

            for msg_id in reversed(data[0].split()):
                status, msg_data = conn.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue

                raw_email = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw_email)

                recipient_headers = " ".join([
                    msg.get("To", ""),
                    msg.get("X-ICLOUD-HME", ""),
                ]).lower()

                if target_email not in recipient_headers:
                    continue

                body = _extract_body(msg)
                if not body:
                    continue

                match = otp_regex.search(body)
                if not match:
                    continue

                otp = match.group(1)
                print(f"    [IMAP] ✓ OTP extracted: {mask(otp)}")

                conn.store(msg_id, "+FLAGS", "\\Seen")
                return otp

        except imaplib.IMAP4.error as exc:
            print(f"    [IMAP] Connection error: {exc}")
        except Exception as exc:
            print(f"    [IMAP] Unexpected error: {exc}")
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))

    print("    [IMAP] ✗ OTP extraction timed out.")
    return None


def _extract_body(msg):
    """Return the plain-text body of an email.Message, or None."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return None


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"[FATAL] Required environment variable is not set.")
        sys.exit(1)
    return val

def mask(value):
    if not value or len(value) <= 2:
        return "***"
    return value[:2] + "***"

def load_csv_from_env():
    raw_b64 = env("DATA_CSV_B64")
    try:
        decoded = base64.b64decode(raw_b64).decode("utf-8")
        reader = csv.DictReader(io.StringIO(decoded))
        return list(reader)
    except Exception as e:
        print(f"[FATAL] Failed to decode DATA_CSV_B64: {e}")
        sys.exit(1)

def get_row(rows, idx):
    if idx < 0 or idx >= len(rows):
        print(f"[FATAL] NEXT_ROW {idx} out of range (0..{len(rows)-1})")
        sys.exit(1)
    return rows[idx]

def increment_next_row(current_row):
    pat = env("PAT_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    new_val = str(current_row + 1)
    url = f"https://api.github.com/repos/{repo}/actions/variables/NEXT_ROW"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"token {pat}", "X-GitHub-Api-Version": "2022-11-28"}
    r = requests.patch(url, headers=headers, json={"name": "NEXT_ROW", "value": new_val})
    if r.status_code in (200, 204):
        print(f"    ✓ Row counter updated to {new_val}")
    else:
        print(f"    ✗ Failed to update row counter (HTTP {r.status_code})")

def discord_notify(msg):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url: return
    try: requests.post(url, json={"content": msg}, timeout=10)
    except Exception: pass


                                                                             
                
                                                                             

def wait_through_queue(sb, max_wait_minutes=90):
    """
    Wait through the queue page. Automatically clicks CONFIRM
    when the 'Don't lose your spot!' popup appears.
    Returns True once we've passed the queue.
    """
    print("[Queue] In queue. Waiting to pass through …")
    start = time.time()
    max_wait = max_wait_minutes * 60
    confirm_count = 0
    last_log_time = 0

    while time.time() - start < max_wait:
        elapsed = int(time.time() - start)

                                                          
        dismiss_cookie_banner(sb)

                                 
        try:
            current_url = sb.get_current_url()
        except Exception:
            time.sleep(5)
            continue

                               
        if "queue" not in current_url.lower():
                                                          
            if ("la28id" in current_url
                    or "login" in current_url
                    or "register" in current_url
                    or "mycustomerdata" in current_url):
                m, s = divmod(elapsed, 60)
                print(f"[Queue] ✓ Passed queue after {m}m {s}s ({confirm_count} confirms)")
                return True

                                                         
            try:
                if (sb.is_element_present('a[href*="../register/"]')
                        or sb.is_element_present('.gigya-input-fauxbutton')
                        or sb.is_element_present('#register-site-login')
                        or sb.is_element_present('#gigya-textbox-code')):
                    m, s = divmod(elapsed, 60)
                    print(f"[Queue] ✓ Passed queue after {m}m {s}s — on target page")
                    return True
            except Exception:
                pass

                                                                    
        try:
            if sb.is_element_visible('button.botdetect-button'):
                print("[Queue] 'JOIN THE QUEUE' button detected. Clicking it …")
                sb.click('button.botdetect-button')
                time.sleep(4)
                continue
        except Exception as e:
                         
            try:
                clicked = sb.evaluate("""
                    (function(){
                        var btn = document.querySelector('button.botdetect-button');
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        return false;
                    })()
                """)
                if clicked:
                    print("[Queue] Clicked 'JOIN THE QUEUE' via JS.")
                    time.sleep(4)
                    continue
            except Exception:
                pass

                                                                             
        try:
            if sb.is_element_visible('#buttonConfirmVisitorPresence'):
                sb.click('#buttonConfirmVisitorPresence')
                confirm_count += 1
                print(f"[Queue] ✓ Clicked CONFIRM (#{confirm_count}) at {elapsed}s")
                time.sleep(1)
                continue
        except Exception:
                         
            try:
                is_visible = sb.evaluate("""
                    (function(){
                        var btn = document.getElementById('buttonConfirmVisitorPresence');
                        if (!btn) return false;
                        var style = window.getComputedStyle(btn);
                        return style.display !== 'none' && style.visibility !== 'hidden' && btn.offsetWidth > 0 && btn.offsetHeight > 0;
                    })()
                """)
                if is_visible:
                    sb.evaluate("""
                        (function(){
                            var btn = document.getElementById('buttonConfirmVisitorPresence');
                            if (btn && !btn.disabled) btn.click();
                        })()
                    """)
                    confirm_count += 1
                    print(f"[Queue] ✓ Clicked CONFIRM via JS (#{confirm_count}) at {elapsed}s")
                    time.sleep(1)
                    continue
            except Exception:
                pass

                                               
        try:
            clicked = sb.evaluate("""
                (function(){
                    var buttons = document.querySelectorAll('button, a, input[type="submit"]');
                    for (var i = 0; i < buttons.length; i++) {
                        var el = buttons[i];
                        var text = (el.textContent || el.value || '').trim().toLowerCase();
                        if (text === 'continue' || text === 'weiter') {
                            var style = window.getComputedStyle(el);
                            if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetWidth > 0) {
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                })()
            """)
            if clicked:
                print(f"[Queue] ✓ Clicked 'Continue' button at {elapsed}s")
                time.sleep(4)
                continue
        except Exception:
            pass

        if elapsed - last_log_time >= 30:
            last_log_time = elapsed
            m, s = divmod(elapsed, 60)
            print(f"[Queue] Still waiting … {m}m {s}s elapsed")

        time.sleep(3)

    print(f"[Queue] ✗ Timed out after {max_wait_minutes} minutes")
    return False


                                                                             
                                          
                                                                             

def enter_otp_code(sb, otp):
    """Robustly enter the OTP code into #gigya-textbox-code."""
    selector = "#gigya-textbox-code"

                                
    for _ in range(15):
        if sb.is_element_present(selector):
            break
        time.sleep(1)

                                             
    try:
        sb.click(selector)
        time.sleep(0.3)
        sb.evaluate(f'document.querySelector("{selector}").value = ""')
        time.sleep(0.2)
        sb.type(selector, otp)
        time.sleep(0.5)
        actual = sb.evaluate(f'document.querySelector("{selector}").value')
        if str(actual).strip() == str(otp).strip():
            print(f"    ✓ OTP entered successfully (method 1: type)")
            return True
        print(f"    Method 1 value mismatch: got '{actual}'")
    except Exception as e:
        print(f"    Method 1 failed: {e}")

                                                                  
    try:
        sb.evaluate(f"""
            (function(){{
                var el = document.querySelector('{selector}');
                if (!el) return;
                el.focus();
                el.click();
                el.value = '';
                var code = '{otp}';
                for (var i = 0; i < code.length; i++) {{
                    el.value += code[i];
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new KeyboardEvent('keydown', {{key: code[i], bubbles: true}}));
                    el.dispatchEvent(new KeyboardEvent('keypress', {{key: code[i], bubbles: true}}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {{key: code[i], bubbles: true}}));
                }}
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }})()
        """)
        time.sleep(0.5)
        actual = sb.evaluate(f'document.querySelector("{selector}").value')
        if str(actual).strip() == str(otp).strip():
            print(f"    ✓ OTP entered successfully (method 2: JS char-by-char)")
            return True
        print(f"    Method 2 value mismatch: got '{actual}'")
    except Exception as e:
        print(f"    Method 2 failed: {e}")

                                      
    try:
        sb.evaluate(f"""
            (function(){{
                var el = document.querySelector('{selector}');
                if (!el) return;
                el.focus();
                el.value = '{otp}';
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true}}));
            }})()
        """)
        time.sleep(0.5)
        actual = sb.evaluate(f'document.querySelector("{selector}").value')
        if str(actual).strip() == str(otp).strip():
            print(f"    ✓ OTP entered successfully (method 3: JS direct)")
            return True
    except Exception as e:
        print(f"    Method 3 failed: {e}")

    print("    ✗ All OTP input methods failed")
    return False


                                                                             
                    
                                                                             

def human_pause(min_s=0.6, max_s=1.8):
    time.sleep(random.uniform(min_s, max_s))


def human_type(sb, selector, text, min_delay=0.08, max_delay=0.18):
    sb.type(selector, text)
    human_pause(0.3, 0.7)


                                                                             
              
                                                                             

def dismiss_cookie_banner(sb):
    """Dismiss the cookie consent banner if present (handles CMP and OneTrust)."""
    try:
        if sb.is_element_visible('#cmpwelcomebtnno > a'):
            sb.click('#cmpwelcomebtnno > a')
            time.sleep(1)
            print("[Browser] Cookie banner dismissed (CMP)")
    except Exception:
        pass

    try:
        if sb.is_element_visible('#onetrust-reject-all-handler'):
            sb.click('#onetrust-reject-all-handler')
            time.sleep(1)
            print("[Browser] Cookie banner dismissed (OneTrust Reject)")
    except Exception:
        pass

    try:
        if sb.is_element_visible('#onetrust-accept-btn-handler'):
            sb.click('#onetrust-accept-btn-handler')
            time.sleep(1)
            print("[Browser] Cookie banner dismissed (OneTrust Accept)")
    except Exception:
        pass


def wait_for_profile_page(sb, timeout=30):
    for _ in range(timeout):
        if (sb.is_element_present('select[name^="additionalCustomerAttributes-1_"]')
                or sb.is_element_present('ev-pl-button[data-qa="save-data-button"]')):
            return True
        sb.sleep(1)
    return False


                                                                             
      
                                                                             

def main():
    global TEST_EMAIL, TEST_PASSWORD, TEST_FIRST, TEST_LAST, TEST_COUNTRY, TEST_ZIP
    imap_user = env("IMAP_USER")
    imap_pass = env("IMAP_PASS")
    next_row = int(env("NEXT_ROW", default="0"))
    if os.environ.get("DATA_CSV_B64"):
        rows = load_csv_from_env()
        row = get_row(rows, next_row)
        TEST_EMAIL = row.get("email", "")
        TEST_PASSWORD = row.get("password", "")
        TEST_FIRST = row.get("first_name", "")
        TEST_LAST = row.get("last_name", "")
        TEST_COUNTRY = row.get("country", "")
        TEST_ZIP = row.get("zip_code", "")
    if not TEST_EMAIL or not TEST_PASSWORD:
        print("[FATAL] No account data.")
        sys.exit(1)

    print("=" * 50)
    print("  LOCAL TEST — Visible Browser")
    print("=" * 50)
    print(f"  Row     : {next_row}")
    print(f"  Email   : {mask(TEST_EMAIL)}")
    print(f"  Name    : {mask(TEST_FIRST)} {mask(TEST_LAST)}")
    print(f"  Country : {TEST_COUNTRY}")
    print()

    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    print(f"[Browser] Launching Chrome (headless={headless}) …")
    sb = sb_cdp.Chrome(headless=headless)
    try:

        print(f"[Browser] Navigating to form URL …")
        sb.open(FORM_URL)
        time.sleep(4)


        dismiss_cookie_banner(sb)


        current_url = sb.get_current_url()
        if "queue" in current_url.lower() or "enqueuetoken" in current_url.lower():
            passed = wait_through_queue(sb, max_wait_minutes=90)
            if not passed:
                print("[FATAL] Queue timed out. Exiting.")
                sys.exit(1)
            time.sleep(5)                                      
        else:
            print("[Queue] No queue detected, proceeding directly.")


        dismiss_cookie_banner(sb)


        print("[Browser] Waiting for login page …")
        for _ in range(30):
            if (sb.is_element_present('a[href*="../register/"]')
                    or sb.is_element_present('.gigya-input-fauxbutton')
                    or sb.is_element_present('#register-site-login')):
                break
            time.sleep(2)


        print("[Browser] Clicking register …")
        try:
            sb.click('a[href*="../register/"]')
        except Exception:
            try:
                sb.click('.gigya-input-fauxbutton')
            except Exception:
                print("[Browser] Could not find register button — may already be on form.")
        time.sleep(5)


        print("[Browser] Filling registration form …")
        sb.wait_for_element('#register-site-login', timeout=30)
        time.sleep(2)


        human_type(sb, '#register-site-login > div:nth-child(1) > div.gigya-layout-row > div > input', TEST_EMAIL)
        human_pause(0.8, 1.6)


        human_type(sb, '#register-site-login > div:nth-child(2) > div:nth-child(1) > div > input', TEST_FIRST)
        human_pause(0.6, 1.3)


        human_type(sb, '#register-site-login > div:nth-child(2) > div:nth-child(2) > div > input', TEST_LAST)
        human_pause(0.7, 1.5)


        human_type(sb, '#register-site-login > div.gigya-composite-control.gigya-composite-control-password.gigya-composite-control-password-peek.gigya-reset > div > input', TEST_PASSWORD)
        human_pause(0.9, 1.8)


        human_pause(1.0, 2.0)
        country_clean = TEST_COUNTRY.strip()
        if country_clean.upper() == "DE":
            country_clean = "Germany"

        try:
            sb.select_option_by_value('#gigya-dropdown-102412737448402420', TEST_COUNTRY)
        except Exception:
            try:
                sb.select_option_by_text('#gigya-dropdown-102412737448402420', country_clean)
            except Exception:
                sb.evaluate(f"""
                    (function(){{
                        const sel = document.querySelector('#gigya-dropdown-102412737448402420');
                        if (sel) {{
                            const countryVal = '{TEST_COUNTRY}'.trim().toUpperCase();
                            let opt = Array.from(sel.options).find(o => o.value.toUpperCase() === countryVal);
                            if (!opt) {{
                                opt = Array.from(sel.options).find(o => o.textContent.trim().toUpperCase() === countryVal);
                            }}
                            if (!opt && countryVal === "DE") {{
                                opt = Array.from(sel.options).find(o => o.textContent.trim().toUpperCase() === "GERMANY");
                            }}
                            if (opt) {{
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change', {{bubbles:true}}));
                            }}
                        }}
                    }})()
                """)
        human_pause(1.2, 2.0)


        try:
            sb.select_option_by_text('select[name="data.personalization.siteLanguage"]', "English")
        except Exception:
            pass
        human_pause(0.8, 1.6)


        print("[Browser] Setting checkboxes …")
        human_pause(1.5, 2.5)
        sb.evaluate("""
            (function(){
                const age = document.getElementById('gigya-checkbox-145180641846438850');
                if (age && !age.checked) age.click();
                const terms = document.getElementById('gigya-checkbox-terms');
                if (terms && !terms.checked) terms.click();
            })()
        """)
        human_pause(0.8, 1.4)


        print("[Browser] Submitting registration form …")
        human_pause(1.8, 3.0)
        try:
            sb.click('input[type="submit"][value="Submit and Continue"]')
        except Exception:
            sb.click('input[type="submit"]')
        human_pause(4.0, 7.0)


        print("[Browser] Waiting for OTP input …")
        for _ in range(20):
            if sb.is_element_present('#gigya-textbox-code'):
                break
            time.sleep(1)

        if not sb.is_element_present('#gigya-textbox-code'):
            print("[FATAL] OTP input not found. Check the browser window.")
            sys.exit(1)

        print("[IMAP] Fetching OTP from Gmail …")
        otp = fetch_otp_from_gmail(TEST_EMAIL, imap_user, imap_pass)
        if not otp:
            print("[FATAL] Could not retrieve OTP. Check Gmail.")
            sys.exit(1)


        print(f"[OTP] Entering code: {mask(otp)}")
        ok = enter_otp_code(sb, otp)
        if not ok:
            print("[FATAL] Could not enter OTP code.")
            sys.exit(1)

        time.sleep(1)


        print("[Browser] Clicking Verify …")
        try:
            sb.click('#gigya-otp-update-form > div:nth-child(3) > div.gigya-composite-control.gigya-composite-control-submit > input')
        except Exception:
            sb.evaluate("""
                (function(){
                    const btn = document.querySelector('#gigya-otp-update-form input[type="submit"]');
                    if (btn) btn.click();
                })()
            """)

        time.sleep(6)


        print("[Browser] Waiting for profile page …")
        if not wait_for_profile_page(sb, timeout=40):
            print("[WARNING] Profile page did not load in time.")

        dismiss_cookie_banner(sb)


        print("[Browser] Checking presale checkbox …")
        try:
            sb.evaluate("""
                (function(){
                    const label = document.querySelector('label[for="lottery-55"]');
                    if (label) {
                        const input = document.getElementById('lottery-55');
                        if (input && !input.checked) label.click();
                    }
                })()
            """)
        except Exception:
            pass
        time.sleep(1)


        chosen_year = str(random.choice(range(1956, 2006)))
        print(f"[Browser] Selecting birth year: {chosen_year}")
        try:
            sb.evaluate(f"""
                (function(){{
                    const selects = Array.from(document.querySelectorAll('select[name^="additionalCustomerAttributes-1_"]'));
                    if (selects.length > 0) {{
                        const sel = selects[0];
                        const opt = Array.from(sel.options).find(o => o.textContent.trim() === '{chosen_year}');
                        if (opt) {{
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {{bubbles:true}}));
                        }}
                    }}
                }})()
            """)
        except Exception as e:
            print(f"    Birth year selection failed: {e}")
        time.sleep(2)


        print("[Browser] Clicking final submit …")
        try:
            sb.click('ev-pl-button[data-qa="save-data-button"] button')
        except Exception:
            try:
                sb.click('#main > div > app-root > app-customer-data-page > app-sports-profile > app-sports-profile-save-section > section > div > div > div > ev-pl-button button')
            except Exception:
                sb.evaluate("""
                    (function(){
                        const btn = document.querySelector('ev-pl-button[data-qa="save-data-button"] button');
                        if (btn) btn.click();
                    })()
                """)

        time.sleep(8)


        success = sb.is_element_present('h2[data-qa="page-headline"]')
        if success:
            print("\n✅ SUCCESS — registration completed!")
            discord_notify(f"✅ Registration complete (row {next_row})")
            if os.environ.get("DATA_CSV_B64"):
                increment_next_row(next_row)
        else:
            print("\n⚠️  Registration may have completed (success element not detected).")

        print("\nTest finished.")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

    try:
        sb.quit()
    except Exception:
        pass


if __name__ == "__main__":
    main()
