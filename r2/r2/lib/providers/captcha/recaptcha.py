# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from pylons import app_globals as g

import json
import requests

from r2.lib.providers.captcha import CaptchaError, CaptchaProvider

VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
STATS_NAMESPACE = "providers.captcha.recaptcha"


def _captcha_event(fragment):
    """Log a simple event within this namespace."""
    return g.stats.simple_event('%s.%s' % (STATS_NAMESPACE, fragment))


class RecaptchaProvider(CaptchaProvider):
    """Verify a recaptcha value as valid."""

    @staticmethod
    def validate_captcha(captcha_value):
        """Validate and return the status of a captcha given request data.

        Returns True on valid, False on invalid, and raises CaptchaError if the
        captcha could not be validated for some reason or another (for example,
        network issues).
        """
        # guard against misconfiguration :/
        if not g.secrets.get('recaptcha_secret_key'):
            raise ValueError("No secret key provided to Recaptcha!")

        # For future thinking: Google also provides the ability to check
        # the source IP, but to minimize privacy impact we're skipping that
        # for now. If we end up needing better spam protection, we might
        # consider adding that.
        # See https://developers.google.com/recaptcha/docs/verify
        params = {
            "secret": g.secrets['recaptcha_secret_key'],
            "response": captcha_value,
        }

        timer = g.stats.get_timer('%s.validate_captcha' % STATS_NAMESPACE)
        timer.start()
        try:
            r = requests.post(
                VERIFY_URL,
                data=params,
                timeout=3,
            )
        except requests.exceptions.Timeout:
            _captcha_event('error.timeout')
            raise CaptchaError("Unable to verify CAPTCHA. Request timed out.")
        except requests.exceptions.SSLError:
            _captcha_event('error.ssl_error')
            raise CaptchaError("Unable to verify CAPTCHA. SSL Error.")
        else:
            if r.status_code != 200:
                _captcha_event('error.bad_status')
                raise CaptchaError("Unexpected status response code: %d" %
                                   r.status_code)

            try:
                response_data = json.loads(r.text)
            except ValueError:
                _captcha_event('error.bad_json')
                raise CaptchaError("Could not parse JSON response")

            if response_data.get("success"):
                _captcha_event('success')
                return True
            else:
                # Log error codes from the API. Current possible values at:
                # https://developers.google.com/recaptcha/docs/verify#error-code-reference
                for err in response_data.get("error-codes", []):
                    _captcha_event('failure.%s' % err.replace('-', '_'))
                return False

        finally:
            timer.stop()
