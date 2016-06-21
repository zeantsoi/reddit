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
import contextlib
import json
import time
from mock import patch, MagicMock

from r2.lib import signing
from r2.tests import RedditControllerTestCase
from r2.lib.validator import VThrottledLogin, VUname
from common import LoginRegBase


class APIV1LoginTests(LoginRegBase, RedditControllerTestCase):
    CONTROLLER = "apiv1login"

    def setUp(self):
        super(APIV1LoginTests, self).setUp()
        self.device_id = "dead-beef"
        self.epoch = None
        self.platform = "test"
        self.version = 1

    def make_ua_signature(self):
        payload = "User-Agent:{}|Client-Vendor-ID:{}".format(
            self.user_agent, self.device_id,
        )
        return self.sign(payload)

    def sign(self, payload):
        return signing.sign_v1_message(
            payload, self.platform, self.version, epoch=self.epoch
        )

    def additional_headers(self, headers, body):
        return {
            signing.SIGNATURE_UA_HEADER: self.make_ua_signature(),
            signing.SIGNATURE_BODY_HEADER: self.sign("Body:" + body),
        }

    def assert_success(self, res):
        self.assertEqual(res.status, 200)
        body = res.body
        body = json.loads(body)
        self.assertTrue("json" in body)
        errors = body['json'].get("errors")
        self.assertEqual(len(errors), 0)
        data = body['json'].get("data")
        self.assertTrue(bool(data))
        self.assertTrue("modhash" in data)
        self.assertTrue("cookie" in data)

    def assert_failure(self, res, code=None):
        self.assertEqual(res.status, 200)
        body = res.body
        body = json.loads(body)
        self.assertTrue("json" in body)
        errors = body['json'].get("errors")
        self.assertTrue(code in [x[0] for x in errors])
        data = body['json'].get("data")
        self.assertFalse(bool(data))

    def assert_403_response(self, res, calling):
        self.assertEqual(res.status, 403)
        self.simple_event.assert_any_call(calling)
        self.assert_headers(
            res,
            "content-type",
            "application/json; charset=UTF-8",
        )

    def test_nosigning_login(self):
        res = self.do_login(
            headers={
                signing.SIGNATURE_UA_HEADER: None,
                signing.SIGNATURE_BODY_HEADER: None,
            },
            expect_errors=True,
        )
        self.assert_403_response(res, "signing.ua.invalid.invalid_format")

    def test_no_body_signing_login(self):
        res = self.do_login(
            headers={
                signing.SIGNATURE_BODY_HEADER: None,
            },
            expect_errors=True,
        )
        self.assert_403_response(res, "signing.body.invalid.invalid_format")

    def test_nosigning_register(self):
        res = self.do_register(
            headers={
                signing.SIGNATURE_UA_HEADER: None,
                signing.SIGNATURE_BODY_HEADER: None,
            },
            expect_errors=True,
        )
        self.assert_403_response(res, "signing.ua.invalid.invalid_format")

    def test_no_body_signing_register(self):
        res = self.do_login(
            headers={
                signing.SIGNATURE_BODY_HEADER: None,
            },
            expect_errors=True,
        )
        self.assert_403_response(res, "signing.body.invalid.invalid_format")

    def test_captcha_register_blocking(self):
        # when the request is signed, the captcha shouldn't have any teeth
        with contextlib.nested(
            self.mock_register(),
            self.failed_captcha()
        ):
            res = self.do_register()
            self.assert_success(res)

    def test_epoch_check(self):
        with self.mock_login():
            self.epoch = time.time() - 86400 * 30
            res = self.do_login(expect_errors=True)
            self.assert_403_response(
                res, "signing.body.invalid.expired_token",
            )

    def test_epoch_bypass_android(self):
        with self.mock_login():
            self.epoch = time.time() - 86400 * 30
            self.platform = "android"
            self.version = 1
            res = self.do_login()
            self.assert_success(res)

    def test_captcha_login_blocking(self):
        # when the request is signed, the captcha shouldn't have any teeth
        with contextlib.nested(
            self.mock_login(),
            self.failed_captcha()
        ):
            res = self.do_login()
            self.assert_success(res)
