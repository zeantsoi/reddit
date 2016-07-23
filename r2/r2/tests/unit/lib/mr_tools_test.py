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
import time
from StringIO import StringIO

from r2.tests import RedditTestCase
from r2.lib.utils import Storage
from r2.lib.mr_tools._mr_tools import keyiter, mr_map, mr_reduce
from r2.lib import mr_tools


def make_thing_dump(*links):
    """Generate thing-table like dump for testing.

    :param tuple links: list of Link-like objects (generally Storages) to
        be represented in the dump

    :return: Tab separated row which _looks_ like it came from
        dumping the thing table
    :rtype: str
    """
    res = []
    for link in links:
        v = (
            "{thing_id} thing link {ups} {downs} "
            "{spam} {deleted} {timestamp}"
        ).format(
            thing_id=link.thing_id,
            ups=link.ups,
            downs=link.downs,
            spam=str(link.spam).lower()[0],
            deleted=str(link.deleted).lower()[0],
            timestamp=link.timestamp,
        ).replace(" ", "\t")
        res.append(v)
    return "\n".join(res)


def make_data_dump(fields, *links):
    """Generate data-table like dump for testing.

    :param list fields: List "keys" that have been pulled from the "data"
        table which we are trying to replicate
    :param tuple links: list of Link-like objects (generally Storages) to
        be represented in the dump

    :return: Tab separated row which _looks_ like it came from
        dumping the thing data, with one row per link and field (cartesian
        product).
    :rtype: str
    """
    res = []
    for l in links:
        for f in fields:
            res.append(
                "{thing_id} data link {key} {value}".format(
                    thing_id=l.thing_id, key=f, value=l[f],
                ).replace(" ", "\t")
            )
        return "\n".join(res)


def make_pg_dump(fields, *links):
    """Generate a fake dump of all thing and data for links.

    :param list fields: List "keys" that have been pulled from the "data"
        table which we are trying to replicate
    :param tuple links: list of Link-like objects (generally Storages) to
        be represented in the dump

    :return: Tab separated row which _looks_ like it came from
        dumping the thing table followed by the data table for the provided
        fields
    :rtype: str
    """
    return "\n".join([
        make_thing_dump(*links),
        make_data_dump(fields, *links),
    ])


def make_link(
    thing_id, ups=1, downs=0,
    spam=False, deleted=False, timestamp=None, **kw
):
    """Make a mocked Link with the provided data.

    :returns: A fake but plausible Link
    :rtype: :py:class:`r2.lib.utils.Storage`
    """
    if timestamp is None:
        timestamp = time.time()
    return Storage(
        thing_id=thing_id,
        ups=ups,
        downs=downs,
        spam=spam,
        deleted=deleted,
        timestamp=timestamp,
        **kw
    )


def make_thing_row(fields, *links):
    """Generate a final processed thing row.

    :param list fields: Optional list of fields to include at the end of the
        row to replicate the result of the MR job after join.
    :param tuple links: list of Link-like objects (generally Storages) to
        be represented in the dump

    :return: Tab separated row which _looks_ like it came from
        dumping the thing table
    :rtype: str
    """
    res = []
    for link in links:
        v = (
            "{thing_id} link {ups} {downs} "
            "{spam} {deleted} {timestamp}"
        ).format(
            thing_id=link.thing_id,
            ups=link.ups,
            downs=link.downs,
            spam=str(link.spam).lower()[0],
            deleted=str(link.deleted).lower()[0],
            timestamp=link.timestamp,
        ).replace(" ", "\t")
        for f in fields or []:
            v += "\t" + str(link[f])
        res.append(v)
    return "\n".join(res)


class MrTests(RedditTestCase):

    def test_keyiter(self):
        stdin = StringIO("\n".join([
            "foo\tbar\tbar1",
            "baz\tbad\tbad1",
        ]))
        d = {k: list(v) for k, v in keyiter(stream=stdin)}
        self.assertEqual(d, {
            "foo": [["bar", "bar1"]],
            "baz": [["bad", "bad1"]],
        })

    def test_mr_map(self):
        stdin = StringIO("\n".join([
            "foo\tbar\tbar1",
            "baz\tbad\tbad1",
        ]))
        stdout = StringIO()

        mr_map(lambda x: [x[:1]], fd=stdin, out=stdout)

        self.assertEqual(stdout.getvalue(), "foo\nbaz\n")

    def test_mr_reduce(self):
        stdin = StringIO("\n".join([
            "foo\tbar\tbar1",
            "baz\tbad\tbad1\tbad2",
        ]))
        stdout = StringIO()

        def process(key, vals):
            return [[key, len(list(vals)[0])]]

        mr_reduce(process, fd=stdin, out=stdout)
        self.assertEqual(stdout.getvalue(), "foo\t2\nbaz\t3\n")

    def test_dump_mocking(self):
        # sometimes it's good to test mocking is working
        expected = [
            "1 thing link 1 0 f f 100.01",
            "1 data link url foo",
            "1 data link sr_id 10",
        ]
        expected = "\n".join(expected).replace(" ", "\t")
        link = make_link(
            thing_id=1, timestamp=100.01, url="foo", sr_id=10
        )
        self.assertEqual(
            make_pg_dump(['url', 'sr_id'], link).strip(),
            expected
        )

    def test_join_things(self):
        fields = ['url', 'sr_id']
        link = make_link(
            thing_id=1, timestamp=100.01, url="foo", sr_id=10
        )
        dump = make_pg_dump(fields, link)
        stdin = StringIO(dump)
        stdout = StringIO()
        mr_tools.join_things(fields, fd=stdin, out=stdout, err=StringIO())

        self.assertEqual(
            stdout.getvalue().strip(),
            "1 link 1 0 f f 100.01 foo 10".replace(" ", "\t")
        )
