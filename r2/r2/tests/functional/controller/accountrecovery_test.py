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

from mock import patch, MagicMock
from pylons import app_globals as g

from r2.models import Account, Award, bcrypt_password, valid_password
from r2.models.token import (
    AccountRecoveryToken,
    OAuth2AccessToken,
    OAuth2RefreshToken,
)
from r2.tests import RedditControllerTestCase


CURRENT_PASSWORD = "oldsecret"
NEW_PASSWORD = "secret"
HACKER_PASSWORD = "hacker"

CURRENT_PW_BCRYPT = bcrypt_password(CURRENT_PASSWORD)
HACKER_PW_BCRYPT = bcrypt_password(HACKER_PASSWORD)

USER_EMAIL = "user_email@test.com"
HACKER_EMAIL = "hacker_email@test.com"


class AccountRecoveryTest(RedditControllerTestCase):
    CONTROLLER = "api"

    def setUp(self):
        super(AccountRecoveryTest, self).setUp()

        self.user = MagicMock(name="user")
        self.user._fullname = "test"
        self.user.email = USER_EMAIL
        self.user.password = CURRENT_PW_BCRYPT

        # accountrecoverytoken is generated if email address was changed
        self.token = AccountRecoveryToken._new(self.user)

        # now assume hacker updates email & password
        self.user.email = HACKER_EMAIL
        self.user.password = HACKER_PW_BCRYPT

    def test_accountrecovery_success(self):
        with self.mock_accountrecovery():
            res = self.do_accountrecovery(id=self.token._id, email=USER_EMAIL,
                                          curpass=CURRENT_PASSWORD)

            self.assertEqual(res.status, 200)
            self.assertTrue(valid_password(self.user, NEW_PASSWORD))
            self.assertEqual(self.user.email, USER_EMAIL)

    def test_accountrecovery_failure_with_wrong_original_email(self):
        with self.mock_accountrecovery():
            res = self.do_accountrecovery(id=self.token._id,
                                          curpass=CURRENT_PASSWORD)

            self.assertEqual(res.status, 200)
            self.assertFalse(valid_password(self.user, NEW_PASSWORD))
            self.assertNotEqual(self.user.email, USER_EMAIL)

    def test_accountrecovery_failure_with_wrong_old_password(self):
        with self.mock_accountrecovery():
            res = self.do_accountrecovery(id=self.token._id,
                                          email=USER_EMAIL)

            self.assertEqual(res.status, 200)
            self.assertFalse(valid_password(self.user, NEW_PASSWORD))
            self.assertNotEqual(self.user.email, USER_EMAIL)

    def test_accountrecovery_failure_with_wrong_token(self):
        with self.mock_accountrecovery():
            res = self.do_accountrecovery(curpass=CURRENT_PASSWORD,
                                          email=USER_EMAIL)

            self.assertEqual(res.status, 200)
            self.assertFalse(valid_password(self.user, NEW_PASSWORD))
            self.assertNotEqual(self.user.email, USER_EMAIL)

    def mock_accountrecovery(self):
        """Context manager for mocking accountrecovery."""
        def set_email_side_effect(*args, **kwargs):
            self.user.email = USER_EMAIL

        return contextlib.nested(
            patch.object(Account, "_by_fullname", return_value=self.user),
            patch.object(Award, "give_if_needed", side_effect=None),
            patch.object(g.events, "account_recovery_event", side_effect=None),
            patch.object(g.events, "login_event", side_effect=None),
            patch.object(self.user, "set_email",
                         side_effect=set_email_side_effect),
            patch.object(OAuth2RefreshToken, "revoke_all_by_user",
                         side_effect=None),
            patch.object(OAuth2AccessToken, "revoke_all_by_user",
                         side_effect=None),
        )

    def do_accountrecovery(self, id=None, email=None, curpass=None, **kw):
        return self.do_post("accountrecovery", {
            "key": id,
            "curpass": curpass,
            "newpass": NEW_PASSWORD,
            "verpass": NEW_PASSWORD,
            "email": email,
        }, **kw)
