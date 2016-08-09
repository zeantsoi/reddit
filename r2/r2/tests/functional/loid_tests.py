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
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################
from r2.tests import RedditControllerTestCase


class LoidCookieIssueTest(RedditControllerTestCase):

    def assert_loid_cookie(self, response):
        for header, value in response.headers:
            if header == "set-cookie" and value.startswith("loid="):
                return

        raise AssertionError("No LoId issued")

    def test_me_json(self):
        res = self.app.get(
            "/api/me.json",
            extra_environ={"REMOTE_ADDR": "1.2.3.4"},
            headers={'User-Agent': self.user_agent},
        )
        self.assert_loid_cookie(res)
