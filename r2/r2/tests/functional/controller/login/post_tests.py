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
from r2.tests import RedditControllerTestCase
from common import LoginRegBase


class PostLoginRegTests(LoginRegBase, RedditControllerTestCase):
    CONTROLLER = "post"
    ACTIONS = {
        "login": "login",
        "register": "reg",
    }

    def setUp(self):
        RedditControllerTestCase.setUp(self)
        LoginRegBase.setUp(self)
        self.dest = "/foo"

    def find_headers(self, res, name):
        for k, v in res.headers:
            if k == name.lower():
                yield v

    def assert_headers(self, res, name, test):
        for value in self.find_headers(res, name):
            if callable(test) and test(value):
                return
            elif value == test:
                return
        raise AssertionError("No matching %s header found" % name)

    def assert_success(self, res):
        self.assertEqual(res.status, 302)
        self.assert_headers(
            res,
            "Location",
            lambda value: value.endswith(self.dest)
        )
        self.assert_headers(
            res,
            "Set-Cookie",
            lambda value: value.startswith("reddit_session=")
        )

    def assert_failure(self, res, code=None):
        # counterintuitively, failure to login will return a 200
        # (compared to a redirect).
        self.assertEqual(res.status, 200)

    def make_qs(self, **kw):
        kw['dest'] = self.dest
        return super(PostLoginRegTests, self).make_qs(**kw)
