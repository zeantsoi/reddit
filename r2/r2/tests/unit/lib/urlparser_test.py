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

from r2.lib.utils import UrlParser
from r2.tests import RedditTestCase
from pylons import g


class TestIsRedditURL(RedditTestCase):

    @classmethod
    def setUpClass(cls):
        cls._old_offsite = g.offsite_subdomains
        g.offsite_subdomains = ["blog"]

    @classmethod
    def tearDownClass(cls):
        g.offsite_subdomains = cls._old_offsite

    def _is_reddit_url(self, url, subreddit=None):
        return UrlParser(url).is_reddit_url(subreddit)

    def assertIsRedditUrl(self, url, subreddit=None):
        self.assertTrue(self._is_reddit_url(url, subreddit))

    def assertIsNotRedditUrl(self, url, subreddit=None):
        self.assertFalse(self._is_reddit_url(url, subreddit))

    def test_normal_urls(self):
        self.assertIsRedditUrl("https://%s/" % g.domain)
        self.assertIsRedditUrl("https://en.%s/" % g.domain)
        self.assertIsRedditUrl("https://foobar.baz.%s/quux/?a" % g.domain)
        self.assertIsRedditUrl("#anchorage")
        self.assertIsRedditUrl("?path_relative_queries")
        self.assertIsRedditUrl("/")
        self.assertIsRedditUrl("/cats")
        self.assertIsRedditUrl("/cats/")
        self.assertIsRedditUrl("/cats/#maru")
        self.assertIsRedditUrl("//foobaz.%s/aa/baz#quux" % g.domain)
        # XXX: This is technically a legal relative URL, are there any UAs
        # stupid enough to treat this as absolute?
        self.assertIsRedditUrl("path_relative_subpath.com")
        # "blog.reddit.com" is not a reddit URL.
        self.assertIsNotRedditUrl("http://blog.%s/" % g.domain)
        self.assertIsNotRedditUrl("http://foo.blog.%s/" % g.domain)

    def test_incorrect_anchoring(self):
        self.assertIsNotRedditUrl("http://www.%s.whatever.com/" % g.domain)

    def test_protocol_relative(self):
        self.assertIsNotRedditUrl("//foobaz.quux.com/aa/baz#quux")

    def test_weird_protocols(self):
        self.assertIsNotRedditUrl("javascript://%s/%%0d%%0aalert(1)" % g.domain)
        self.assertIsNotRedditUrl("hackery:whatever")

    def test_http_auth(self):
        # There's no legitimate reason to include HTTP auth details in the URL,
        # they only serve to confuse everyone involved.
        # For example, this used to be the behaviour of `UrlParser`, oops!
        # > UrlParser("http://everyoneforgets:aboutthese@/baz.com/").unparse()
        # 'http:///baz.com/'
        self.assertIsNotRedditUrl("http://everyoneforgets:aboutthese@/baz.com/")

    def test_browser_quirks(self):
        # Some browsers try to be helpful and ignore characters in URLs that
        # they think might have been accidental (I guess due to things like:
        # `<a href=" http://badathtml.com/ ">`. We need to ignore those when
        # determining if a URL is local.
        self.assertIsNotRedditUrl("/\x00/somethingelse.com")
        self.assertIsNotRedditUrl("\x09//somethingelse.com")

        # This is makes sure we're not vulnerable to a bug in
        # urlparse / urlunparse.
        # urlunparse(urlparse("////foo.com")) == "//foo.com"! screwy!
        self.assertIsNotRedditUrl("////somethingelse.com/")
        # Webkit and co like to treat backslashes as equivalent to slashes in
        # different places, maybe to make OCD Windows users happy.
        self.assertIsNotRedditUrl(r"/\somethingelse.com/")
        # On chrome this goes to example.com, not a subdomain of reddit.com!
        self.assertIsNotRedditUrl(r"http://\\example.com\a.%s/foo" % g.domain)

        # Combo attacks!
        self.assertIsNotRedditUrl(r"///\somethingelse.com/")
        self.assertIsNotRedditUrl(r"\\somethingelse.com")
        self.assertIsNotRedditUrl("/\x00//\\somethingelse.com/")
        self.assertIsNotRedditUrl(
            "\x09javascript://%s/%%0d%%0aalert(1)" % g.domain
        )
        self.assertIsNotRedditUrl("http://\x09example.com\\%s/foo" % g.domain)
