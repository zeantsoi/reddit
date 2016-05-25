#!/usr/bin/env python
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
from r2.tests import RedditTestCase
from r2.lib.filters import emailmarkdown


class TestFilters(RedditTestCase):
    def setUp(self):
        g.https_endpoint = 'https://reddit.com'

    def test_emailmarkdown(self):
        # test subreddit with leading slash (/r/)
        orig_message = 'Visit /r/test'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>Visit '\
                             '<a href="https://reddit.com/r/test">/r/test</a>'\
                             '</p>\n</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

        # test subreddit with no leading slash (r/)
        orig_message = 'Visit r/test'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>Visit '\
                             '<a href="https://reddit.com/r/test">r/test</a>'\
                             '</p>\n</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

        # test subreddit with punctuation
        orig_message = 'Visit r/test.'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>Visit '\
                             '<a href="https://reddit.com/r/test">r/test</a>'\
                             '.</p>\n</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

        # test user with leading slash
        orig_message = 'Visit /u/test'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>Visit '\
                             '<a href="https://reddit.com/u/test">/u/test</a>'\
                             '</p>\n</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

        # test user with no leading slash
        orig_message = 'Visit u/test'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>Visit '\
                             '<a href="https://reddit.com/u/test">u/test</a>'\
                             '</p>\n</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

        # test two links
        orig_message = 'hey u/sam you should visit r/test'
        body = emailmarkdown(orig_message)
        comparison_message = '<!-- SC_OFF --><div class="md"><p>hey '\
                             '<a href="https://reddit.com/u/sam">u/sam</a>'\
                             ' you should visit <a href='\
                             '"https://reddit.com/r/test">r/test</a></p>\n'\
                             '</div><!-- SC_ON -->'
        self.assertEquals(comparison_message, body)

