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
from StringIO import StringIO
from mock import MagicMock
import time

from r2.tests import RedditTestCase
from r2.lib import jsontemplates
from r2.lib.mr_top import join_things, time_listings, write_permacache
from r2.lib import mr_top
from . mr_tools_test import make_thing_row, make_pg_dump, make_link


class MrTopTests(RedditTestCase):
    def setUp(self):
        super(RedditTestCase, self).setUp()
        self.autopatch(jsontemplates, "make_typename", return_value="t3")
        self.queries = self.autopatch(mr_top, "queries")

    def test_join_things(self):
        fields = ['author_id', 'sr_id', 'url']
        link = make_link(
            thing_id=1, timestamp=100.01, url="foo", sr_id=10, author_id=2
        )
        dump = make_pg_dump(fields, link)
        stdin = StringIO(dump)
        stdout = StringIO()
        join_things("link", fd=stdin, out=stdout, err=StringIO())

        self.assertEqual(
            stdout.getvalue().strip(),
            "1 link 1 0 f f 100.01 2 10 foo".replace(" ", "\t")
        )

    def test_join_things_missing_field(self):
        fields = ['sr_id', 'url']
        link = make_link(
            thing_id=1, timestamp=100.01, url="foo", sr_id=10,
        )
        dump = make_pg_dump(fields, link)
        stdin = StringIO(dump)
        stdout = StringIO()
        join_things("link", fd=stdin, out=stdout, err=StringIO())

        # XXX: as built, the join fails if there are missing fields.
        # This is not necessarily a feature.
        self.assertEqual(stdout.getvalue().strip(), "")

    def test_time_listings(self):
        link = make_link(
            thing_id=1,
            # strip decimals to avoid string formatting issues
            timestamp=int(time.time()),
            author_id=2,
            url="https://www.foo.com/",
            sr_id=10,
        )

        l = make_thing_row(["author_id", "sr_id", "url"], link)
        stdin = StringIO(l)
        stdout = StringIO()
        time_listings(["hour"], "link", fd=stdin, out=stdout)

        # order is not important for the response:
        res = dict(x.split("\t", 1) for x in stdout.getvalue().splitlines())
        # all of the values end with the created date and the thing fullname
        for sort in ("top", "controversial"):
            value = "{score}\t{timestamp:.1f}\tt3_{thing_id}".format(
                score="1" if sort == "top" else "0.0",
                timestamp=link.timestamp,
                thing_id=link.thing_id
            )
            for k in (
                "domain/link/{sort}/hour/foo.com",
                "domain/link/{sort}/hour/www.foo.com",
                "user/link/{sort}/hour/{author_id}",
                "sr/link/{sort}/hour/{sr_id}",
            ):
                key = k.format(sort=sort, **link)
                self.assertEqual(res.pop(key), value)
        self.assertEqual(res, {})

    def test_time_listings_too_old(self):
        link = make_link(
            thing_id=1,
            timestamp=100.,
            author_id=2,
            url="https://www.foo.com/",
            sr_id=10,
        )

        l = make_thing_row(["author_id", "sr_id", "url"], link)
        stdin = StringIO(l)
        stdout = StringIO()
        time_listings(["hour"], "link", fd=stdin, out=stdout)

        # the item is too old and should be dropped
        res = dict(x.split("\t", 1) for x in stdout.getvalue().splitlines())
        self.assertEqual(res, {})

    def test_write_permacache_domain(self):
        stdin = StringIO("\t".join([
            "domain/link/top/hour/foo.com",
            "1",
            "100.0",
            "t3_1",
        ]))
        stdout = StringIO()
        write_permacache(fd=stdin, out=stdout)
        self.queries.get_domain_links.assert_called_once_with(
            "foo.com", "top", "hour"
        )

    def test_write_permacache_user(self):
        stdin = StringIO("\t".join([
            "user/link/top/hour/1",
            "1",
            "100.0",
            "t3_1",
        ]))
        stdout = StringIO()
        write_permacache(fd=stdin, out=stdout)
        self.queries._get_submitted.assert_called_once_with(1, "top", "hour")

    def test_write_permacache_sr(self):
        stdin = StringIO("\t".join([
            "sr/link/top/hour/1",
            "1",
            "100.0",
            "t3_1",
        ]))
        stdout = StringIO()
        write_permacache(fd=stdin, out=stdout)
        self.queries._get_links.assert_called_once_with(1, "top", "hour")

    def test_write_permacache_unknown(self):
        stdin = StringIO("\t".join([
            "something/link/top/hour/1",
            "1",
            "100.0",
            "t3_1",
        ]))
        stdout = StringIO()
        self.assertRaises(
            AssertionError,
            lambda: write_permacache(fd=stdin, out=stdout),
        )

    def test_write_no_limiting(self):
        stdin = StringIO("\n".join([
            "\t".join([
                "sr/link/top/hour/1",
                "1",
                "100.0",
                "t3_1",
            ]),
            "\t".join([
                "sr/link/top/hour/1",
                "1",
                "100.0",
                "t3_2",
            ]),
        ]))
        stdout = StringIO()

        query = self.queries._get_links.return_value = MagicMock()

        write_permacache(fd=stdin, out=stdout)
        self.assertEqual(len(query._replace.call_args[0][0]), 2)

    def test_write_limiting(self):
        stdin = StringIO("\n".join([
            "\t".join([
                "sr/link/top/hour/1",
                "1",
                "100.0",
                "t3_1",
            ]),
            "\t".join([
                "sr/link/top/hour/1",
                "1",
                "100.0",
                "t3_2",
            ]),
        ]))
        stdout = StringIO()

        query = self.queries._get_links.return_value = MagicMock()

        # the limit should be reflected in the call to _replace
        write_permacache(fd=stdin, out=stdout, num=1)
        self.assertEqual(len(query._replace.call_args[0][0]), 1)
