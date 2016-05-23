# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an 'AS IS' basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################
import contextlib
import json
from mock import patch

from routes.util import url_for
from pylons import app_globals as g

from r2.tests import MockEventQueue, RedditControllerTestCase
from r2.lib.validator import VUser, VModhash, VVerifyPassword, VPasswordChange
from r2.lib.utils import query_string
from r2.models import Account, FakeAccount, bcrypt_password


CURRENT_PW = 'kindofsecret'
NEW_PW = 'supersecret'


class PasswordUpdateTests(RedditControllerTestCase):
    CONTROLLER = 'api'

    def setUp(self):
        super(PasswordUpdateTests, self).setUp()

        self.user = FakeAccount(name='fake',
                                password=bcrypt_password(CURRENT_PW))

    def do_update_password(self, curpass='', newpass='newpass',
                           verpass='newpass'):
        payload = {
            'curpass': curpass,
            'newpass': newpass,
            'verpass': verpass,
        }
        return self.do_post('update_password', payload)

    def mock_update_password(self):
        from r2.controllers.api import ApiController
        # 'g.auth_provider.get_authenticated_account' is used to get the
        # logged in user stored in the tmpl_context.  
        return contextlib.nested(
            patch.object(ApiController, 'login', return_value=None),
            patch.object(VModhash, 'run', side_effect=None),
            patch.object(Account, '_commit', side_effect=None),
            patch.object(Account, '_fullname', 'test'),
            patch.object(g.auth_provider, 'get_authenticated_account',
                         return_value=self.user)
           )

    def assert_success(self, rsp):
        """Test that is run when we expect the post to succeed."""
        rsp_json = json.loads(rsp.body)
        self.assertEqual(rsp_json['success'], True)

        self.assertEqual(rsp.status, 200)

    def assert_failure(self, rsp, code=200):
        """Test that is run when we expect the post to fail."""
        rsp_json = json.loads(rsp.body)
        self.assertEqual(rsp_json['success'], False)

        self.assertEqual(rsp.status, code)

    def assert_error(self, rsp_body, error):
        """Test that a given error is included in a response body."""
        error_str = '.error.%s' % (error)
        self.assertIn(error_str, rsp_body)

    def test_update_password(self):
        with self.mock_update_password():
            rsp = self.do_update_password(curpass=CURRENT_PW, newpass=NEW_PW,
                                          verpass=NEW_PW)

            self.assert_success(rsp)

    def test_wrong_password(self):
        with self.mock_update_password():
            rsp = self.do_update_password(curpass='incorrect', newpass=NEW_PW,
                                          verpass=NEW_PW)

            self.assert_failure(rsp)
            self.assert_error(rsp.body, 'WRONG_PASSWORD')

    def test_short_password(self):
        with self.mock_update_password():
            rsp = self.do_update_password(curpass=CURRENT_PW, newpass='short',
                                          verpass='short')

            self.assert_failure(rsp)
            self.assert_error(rsp.body, 'SHORT_PASSWORD')

    def test_bad_old_password_match(self):
        with self.mock_update_password():
            rsp = self.do_update_password(curpass=CURRENT_PW,
                                          newpass=CURRENT_PW,
                                          verpass=CURRENT_PW)

            self.assert_failure(rsp)
            self.assert_error(rsp.body, 'OLD_PASSWORD_MATCH')

    def test_bad_password_match(self):
        with self.mock_update_password():
            rsp = self.do_update_password(curpass=CURRENT_PW, newpass=NEW_PW,
                                          verpass='notamatch')

            self.assert_failure(rsp)
            self.assert_error(rsp.body, 'BAD_PASSWORD_MATCH')
