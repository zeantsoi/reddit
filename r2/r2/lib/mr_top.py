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

# Known bug: if a given listing hasn't had a submission in the
# allotted time (e.g. the year listing in a subreddit that hasn't had
# a submission in the last year), we won't write out an empty
# list. I'll call it a feature.

import sys
from collections import OrderedDict, namedtuple

from r2.models import Link, Comment
from r2.lib.db.sorts import epoch_seconds, score, controversy
from r2.lib.db import queries
from r2.lib import mr_tools
from r2.lib.utils import timeago, UrlParser
# what a strange place for this function
from r2.lib.jsontemplates import make_fullname


THING_TEMPLATE_SQL = """
SELECT thing_id
    , 'thing'
    , '{thing_cls}'
    , ups
    , downs
    , deleted
    , spam
    , extract(epoch from date)
FROM reddit_thing_{thing_cls}
WHERE not deleted AND thing_id >= {min_id:d}"""

DATA_TEMPLATE_SQL = """
SELECT thing_id
     , 'data'
     , '{thing_cls}'
     , key
     , value
FROM reddit_data_{thing_cls}
WHERE key IN ({keys}) AND thing_id >= {min_id:d}"""

STDIN = sys.stdin
STDOUT = sys.stdout
STDERR = sys.stderr


def top_score(thing):
    return score(thing.ups, thing.downs)


def controversy_score(thing):
    return controversy(thing.ups, thing.downs)


class MrTop(object):

    # supported types, with their export requirements
    SUPPORTED_TYPES = {
        Link: OrderedDict((
            ("author_id", int),
            ("sr_id", int),
            ("url", str),
        )),
        Comment: OrderedDict((
            ("author_id", int),
            ("sr_id", int),
        )),
    }

    # the supported listings and their score functions
    LISTING_SORTS = {
        "top": top_score,
        "controversial": controversy_score,
    }

    def __init__(
        self, thing_type, min_id=None, fd=STDIN, out=STDOUT, err=STDERR
    ):
        self.thing_type = thing_type
        self.fields = None
        self.thing_cls = None
        # since there are a handfull of types, no point making a dict for this
        for thing_cls, fields in self.SUPPORTED_TYPES.iteritems():
            if thing_cls.__name__.lower() == thing_type:
                self.fields = fields
                self.thing_cls = thing_cls

        assert self.fields is not None, \
            "Don't know how to process {!r}".format(thing_type)

        self.fd = fd
        self.out = out
        self.err = err
        self.min_id = None
        if min_id is not None:
            try:
                self.min_id = int(min_id)
            except (TypeError, ValueError):
                raise AssertionError("Invalid min_id: {0!r}".format(min_id))

    def join_things(self):
        fields = []
        defaults = {}
        for k, typ in self.fields.iteritems():
            fields.append(k)
            if typ is int:
                defaults[k] = 0
            elif typ is str:
                defaults[k] = ""
        mr_tools.join_things(
            fields, fd=self.fd, out=self.out, err=self.err, defaults=defaults
        )

    @staticmethod
    def _get_cutoffs(intervals):
        cutoffs = {}
        for interval in intervals:
            if interval == "all":
                cutoffs["all"] = 0.0
            else:
                cutoffs[interval] = epoch_seconds(timeago("1 %s" % interval))

        return cutoffs

    def make_key(self, category, sort, interval, uid):
        return "{category}/{thing_type}/{sort}/{interval}/{uid}".format(
            category=category,
            thing_type=self.thing_type,
            sort=sort,
            interval=interval,
            uid=uid
        )

    @staticmethod
    def split_key(key):
        return key.split("/")

    def time_listings(self, intervals):
        cutoff_by_interval = self._get_cutoffs(intervals)
        spec = self.fields.items()

        @mr_tools.dataspec_m_thing(*spec)
        def process(thing):
            return self.time_listing_iter(thing, cutoff_by_interval)

        mr_tools.mr_map(process, fd=self.fd, out=self.out)

    def time_listing_iter(self, thing, cutoff_by_interval):
        if thing.deleted:
            return

        thing_cls = self.thing_cls
        fname = make_fullname(thing_cls, thing.thing_id)
        scores = {k: func(thing) for k, func in self.LISTING_SORTS.iteritems()}

        for interval, cutoff in cutoff_by_interval.iteritems():
            if thing.timestamp < cutoff:
                continue

            for sort, value in scores.iteritems():
                aid = thing.author_id
                key = self.make_key("user", sort, interval, aid)
                yield (key, value, thing.timestamp, fname)

            if thing.spam:
                continue

            if thing.thing_type == "link":
                for sort, value in scores.iteritems():
                    sr_id = thing.sr_id
                    key = self.make_key("sr", sort, interval, sr_id)
                    yield (key, value, thing.timestamp, fname)

                if not thing.url:
                    continue
                try:
                    parsed = UrlParser(thing.url)
                except ValueError:
                    continue

                for d in parsed.domain_permutations():
                    for sort, value in scores.iteritems():
                        key = self.make_key("domain", sort, interval, d)
                        yield (key, value, thing.timestamp, fname)

    def emit_thing_query(self, stream=STDOUT):
        assert self.min_id is not None
        stream.write(THING_TEMPLATE_SQL.format(
            thing_cls=self.thing_type,
            min_id=self.min_id,
        ))

    def emit_data_query(self, stream=STDOUT):
        assert self.min_id is not None
        keys = ", ".join("'{}'".format(x) for x in self.fields)
        stream.write(DATA_TEMPLATE_SQL.format(
            thing_cls=self.thing_type,
            min_id=self.min_id,
            keys=keys,
        ))

    @classmethod
    def store_keys(cls, key, listing):
        """Look up query based on key, and update with provided listing.

        :param str key: key generated by :py:method:`make_key`
        :param list listing: sorted listing generated by
            `mr_reduce_max_per_key`, generally by :py:method:`write_permacache`
        """
        category, thing_cls, sort, time, uid = cls.split_key(key)

        query = None
        if category == "user":
            if thing_cls == "link":
                query = queries._get_submitted(int(uid), sort, time)
            elif thing_cls == "comment":
                query = queries._get_comments(int(uid), sort, time)
        elif category == "sr":
            if thing_cls == "link":
                query = queries._get_links(int(uid), sort, time)
        elif category == "domain":
            if thing_cls == "link":
                query = queries.get_domain_links(uid, sort, time)

        assert query, 'unknown query type for {}'.format(key)

        item_tuples = [
            (thing_fullname, float(value), float(timestamp))
            for value, timestamp, thing_fullname in listing
        ]
        # we only need locking updates for non-time-based listings, since for
        # time- based ones we're the only ones that ever update it
        lock = time == 'all'

        query._replace(item_tuples, lock=lock)

    @staticmethod
    def _sorting_key(x):
        """Cast iterable to a float."""
        return [float(y) for y in x[:-1]]

    @classmethod
    def write_permacache(cls, fd=STDIN, out=STDOUT, num=1000):
        """Write computed listings (from fd) to permacache.

        :param int num: maximum listing size
        :param file fd: input stream
        """
        mr_tools.mr_reduce_max_per_key(
            cls._sorting_key, num=num, post=cls.store_keys, fd=fd, out=out
        )

    @classmethod
    def reduce_listings(cls, fd=STDIN, out=STDOUT, num=1000):
        """Debugging reducer.

        Like write_permacache, but just sends the reduced version of the
        listing to stdout instead of to the permacache. It's handy for
        debugging to see the final result before it's written out

        :param int num: maximum listing size
        :param file fd: input stream
        """
        mr_tools.mr_reduce_max_per_key(
            cls._sorting_key, num=num, fd=fd, out=out
        )
