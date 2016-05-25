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

from r2.models import Account, Award, bcrypt_password, valid_password
from r2.models.token import PasswordResetToken
from r2.tests import RedditControllerTestCase


CURRENT_PASSWORD = "oldsecret"
NEW_PASSWORD = "secret"

CURRENT_PW_BCRYPT = bcrypt_password(CURRENT_PASSWORD)


class ResetPasswordTest(RedditControllerTestCase):
    CONTROLLER = "api"

    def setUp(self):
        super(ResetPasswordTest, self).setUp()

        self.user = MagicMock(name="user")
        self.user._fullname = "test_user"
        self.user.email = "test@test.com"
        self.user._banned = False
        self.user.password = CURRENT_PW_BCRYPT

        self.token = PasswordResetToken._new(self.user)

    def test_resetpassword_success_with_normal_user(self):
        """Resetpassword succeeds: Returns 200 and sets new password."""
        with self.mock_resetpassword():
            res = self.do_resetpassword(id=self.token._id)

            self.assertEqual(res.status, 200)
            self.assertTrue(valid_password(self.user, NEW_PASSWORD))

    def test_resetpassword_success_with_ato_user(self):
        """Resetpassword succeeds:

        Returns 200, sets new password, and clear ATO.
        """
        self.user.force_password_reset = True
        with self.mock_resetpassword():
            res = self.do_resetpassword(id=self.token._id)

            self.assertEqual(res.status, 200)
            self.assertTrue(valid_password(self.user, NEW_PASSWORD))
            self.assertFalse(self.user.force_password_reset)

    def test_resetpassword_failure_with_expired_token(self):
        """Resetpassword fails: Returns 200 and does not set new password."""
        with self.mock_resetpassword():
            res = self.do_resetpassword()

            self.assertEqual(res.status, 200)
            self.assertFalse(valid_password(self.user, NEW_PASSWORD))

    def mock_resetpassword(self):
        """Context manager for mocking resetpassword."""
        return contextlib.nested(
            patch.object(Account, "_by_fullname", return_value=self.user),
            patch.object(Award, "give_if_needed", side_effect=None),
        )

    def do_resetpassword(self, id=None, **kw):
        return self.do_post("resetpassword", {
            "key": id,
            "passwd": NEW_PASSWORD,
            "passwd2": NEW_PASSWORD,
        }, **kw)
