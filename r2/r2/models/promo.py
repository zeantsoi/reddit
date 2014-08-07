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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

from datetime import datetime, timedelta
from uuid import uuid1

from pycassa.types import CompositeType
from pylons import g, c
from pylons.i18n import _, N_

from r2.lib import filters
from r2.lib.cache import sgm
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import Thing, NotFound
from r2.lib.memoize import memoize
from r2.lib.utils import Enum, to_datetime, to_date
from r2.models.subreddit import Subreddit, Frontpage


PROMOTE_STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
                      "pending", "promoted", "finished")

class PriorityLevel(object):
    name = ''
    _text = N_('')
    _description = N_('')
    value = 1   # Values are from 1 (highest) to 100 (lowest)
    default = False
    inventory_override = False
    cpm = True  # Non-cpm is percentage, will fill unsold impressions

    def __repr__(self):
        return "<PriorityLevel %s: %s>" % (self.name, self.value)

    @property
    def text(self):
        return _(self._text) if self._text else ''

    @property
    def description(self):
        return _(self._description) if self._description else ''


class HighPriority(PriorityLevel):
    name = 'high'
    _text = N_('highest')
    value = 5


class MediumPriority(PriorityLevel):
    name = 'standard'
    _text = N_('standard')
    value = 10
    default = True


class RemnantPriority(PriorityLevel):
    name = 'remnant'
    _text = N_('remnant')
    _description = N_('lower priority, impressions are not guaranteed')
    value = 20
    inventory_override = True


class HousePriority(PriorityLevel):
    name = 'house'
    _text = N_('house')
    _description = N_('non-CPM, displays in all unsold impressions')
    value = 30
    inventory_override = True
    cpm = False


HIGH, MEDIUM, REMNANT, HOUSE = HighPriority(), MediumPriority(), RemnantPriority(), HousePriority()
PROMOTE_PRIORITIES = {p.name: p for p in (HIGH, MEDIUM, REMNANT, HOUSE)}
PROMOTE_DEFAULT_PRIORITY = MEDIUM


class Location(object):
    DELIMITER = '-'
    def __init__(self, country, region=None, metro=None):
        self.country = country or None
        self.region = region or None
        self.metro = metro or None

    def __repr__(self):
        return '<%s (%s/%s/%s)>' % (self.__class__.__name__, self.country,
                                    self.region, self.metro)

    def to_code(self):
        fields = [self.country, self.region, self.metro]
        return self.DELIMITER.join(i or '' for i in fields)

    @classmethod
    def from_code(cls, code):
        country, region, metro = [i or None for i in code.split(cls.DELIMITER)]
        return cls(country, region, metro)

    def contains(self, other):
        if not self.country:
            # self is set of all countries, it includes all possible
            # values of other.country
            return True
        elif not other or not other.country:
            # self is more specific than other
            return False
        else:
            # both self and other specify a country
            if self.country != other.country:
                # countries don't match
                return False
            else:
                # countries match
                if not self.metro:
                    # self.metro is set of all metros within country, it
                    # includes all possible values of other.metro
                    return True
                elif not other.metro:
                    # self is more specific than other
                    return False
                else:
                    return self.metro == other.metro

    def __eq__(self, other):
        if not isinstance(other, Location):
            return False

        return (self.country == other.country and
                self.region == other.region and
                self.metro == other.metro)


def calc_impressions(bid, cpm_pennies):
    # bid is in dollars, cpm_pennies is pennies
    # CPM is cost per 1000 impressions
    return int(bid / cpm_pennies * 1000 * 100)


NO_TRANSACTION = 0


class Collection(object):
    def __init__(self, name, sr_names, description=None):
        self.name = name
        self.sr_names = sr_names
        self.description = description

    @classmethod
    def by_name(cls, name):
        return CollectionStorage.get_collection(name)

    @classmethod
    def get_all(cls):
        return CollectionStorage.get_all()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)


class CollectionStorage(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_name_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
    }
    _compare_with = tdb_cassandra.UTF8_TYPE
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    SR_NAMES_DELIM = '|'

    @classmethod
    def set(cls, name, description, srs):
        rowkey = name
        columns = {
            'description': description,
            'sr_names': cls.SR_NAMES_DELIM.join(sr.name for sr in srs),
        }
        cls._set_values(rowkey, columns)

    @classmethod
    def get_collection(cls, name):
        if not name:
            return None

        rowkey = name
        try:
            columns = cls._cf.get(rowkey)
        except tdb_cassandra.NotFoundException:
            return None

        description = columns['description']
        sr_names = columns['sr_names'].split(cls.SR_NAMES_DELIM)
        return Collection(name, sr_names, description=description)

    @classmethod
    def get_all(cls):
        ret = []
        for name, columns in cls._cf.get_range():
            description = columns['description']
            sr_names = columns['sr_names'].split(cls.SR_NAMES_DELIM)
            ret.append(Collection(name, sr_names, description=description))
        return ret

    def delete(cls, name):
        rowkey = name
        cls._cf.remove(rowkey)


class Target(object):
    """Wrapper around either a Collection or a Subreddit name"""
    def __init__(self, target):
        if isinstance(target, Collection):
            self.collection = target
            self.is_collection = True
        elif isinstance(target, basestring):
            self.subreddit_name = target
            self.is_collection = False
        else:
            raise ValueError("target must be a Collection or Subreddit name")

        # defer looking up subreddits, we might only need their names
        self._subreddits = None

    @property
    def subreddit_names(self):
        if self.is_collection:
            return self.collection.sr_names
        else:
            return [self.subreddit_name]

    @property
    def subreddits_slow(self):
        if self._subreddits is not None:
            return self._subreddits

        sr_names = self.subreddit_names
        srs = Subreddit._by_name(sr_names).values()
        self._subreddits = srs
        return srs

    def __eq__(self, other):
        if self.is_collection != other.is_collection:
            return False

        return set(self.subreddit_names) == set(other.subreddit_names)

    @property
    def pretty_name(self):
        if self.is_collection:
            return _("collection: %(name)s") % {'name': self.collection.name}
        elif self.subreddit_name == Frontpage.name:
            return _("frontpage")
        else:
            return "/r/%s" % self.subreddit_name

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.pretty_name)

class PromoCampaign(Thing):
    _defaults = dict(
        priority_name=PROMOTE_DEFAULT_PRIORITY.name,
        trans_id=NO_TRANSACTION,
        location_code=None,
    )

    # special attributes that shouldn't set Thing data attributes because they
    # have special setters that set other data attributes
    _derived_attrs = (
        "location",
        "priority",
        "target",
    )

    SR_NAMES_DELIM = '|'
    SUBREDDIT_TARGET = "subreddit"

    def __getattr__(self, attr):
        val = Thing.__getattr__(self, attr)
        if attr in ('start_date', 'end_date'):
            val = to_datetime(val)
            if not val.tzinfo:
                val = val.replace(tzinfo=g.tz)
        return val

    def __setattr__(self, attr, val, make_dirty=True):
        if attr in self._derived_attrs:
            object.__setattr__(self, attr, val)
        else:
            Thing.__setattr__(self, attr, val, make_dirty=make_dirty)

    def __getstate__(self):
        """
        Remove _target before returning object state for pickling.

        Thing objects are pickled for caching. The state of the object is
        obtained by calling the __getstate__ method. Remove the _target
        attribute because it may contain Subreddits or other non-trivial objects
        that shouldn't be included.

        """

        state = self.__dict__
        if "_target" in state:
            state = {k: v for k, v in state.iteritems() if k != "_target"}
        return state

    @classmethod
    def priority_name_from_priority(cls, priority):
        if not priority in PROMOTE_PRIORITIES.values():
            raise ValueError("%s is not a valid priority" % val)
        return priority.name

    @classmethod
    def location_code_from_location(cls, location):
        return location.to_code() if location else None

    @classmethod
    def unpack_target(cls, target):
        """Convert a Target into attributes suitable for storage."""
        sr_names = target.subreddit_names
        target_sr_names = cls.SR_NAMES_DELIM.join(sr_names)
        target_name = (target.collection.name if target.is_collection
                                              else cls.SUBREDDIT_TARGET)
        return target_sr_names, target_name

    @classmethod
    def create(cls, link, target, bid, cpm, start_date, end_date, priority,
             location):
        pc = PromoCampaign(
            link_id=link._id,
            bid=bid,
            cpm=cpm,
            start_date=start_date,
            end_date=end_date,
            trans_id=NO_TRANSACTION,
            owner_id=link.author_id,
        )
        pc.priority = priority
        pc.location = location
        pc.target = target
        pc._commit()
        return pc

    @classmethod
    def _by_link(cls, link_id):
        '''
        Returns an iterable of campaigns associated with link_id or an empty
        list if there are none.
        '''
        return cls._query(PromoCampaign.c.link_id == link_id, data=True)

    @classmethod
    def _by_user(cls, account_id):
        '''
        Returns an iterable of all campaigns owned by account_id or an empty 
        list if there are none.
        '''
        return cls._query(PromoCampaign.c.owner_id == account_id, data=True)

    @property
    def ndays(self):
        return (self.end_date - self.start_date).days

    @property
    def impressions(self):
        # deal with pre-CPM PromoCampaigns
        if not hasattr(self, 'cpm'):
            return -1
        elif not self.priority.cpm:
            return -1
        return calc_impressions(self.bid, self.cpm)

    @property
    def priority(self):
        return PROMOTE_PRIORITIES[self.priority_name]

    @priority.setter
    def priority(self, priority):
        self.priority_name = self.priority_name_from_priority(priority)

    @property
    def location(self):
        if self.location_code is not None:
            return Location.from_code(self.location_code)
        else:
            return None

    @location.setter
    def location(self, location):
        self.location_code = self.location_code_from_location(location)

    @property
    def target(self):
        if hasattr(self, "_target"):
            return self._target

        sr_names = self.target_sr_names.split(self.SR_NAMES_DELIM)
        if self.target_name == self.SUBREDDIT_TARGET:
            sr_name = sr_names[0]
            target = Target(sr_name)
        else:
            collection = Collection(self.target_name, sr_names)
            target = Target(collection)

        self._target = target
        return target

    @target.setter
    def target(self, target):
        self.target_sr_names, self.target_name = self.unpack_target(target)

        # set _target so we don't need to lookup on subsequent access
        self._target = target

    @property
    def location_str(self):
        if not self.location:
            return ''
        elif self.location.metro:
            country = self.location.country
            region = self.location.region
            metro_str = (g.locations[country]['regions'][region]
                         ['metros'][self.location.metro]['name'])
            return '/'.join([country, region, metro_str])
        else:
            return g.locations[self.location.country]['name']

    def is_freebie(self):
        return self.trans_id < 0

    def is_live_now(self):
        now = datetime.now(g.tz)
        return self.start_date < now and self.end_date > now

    def delete(self):
        self._deleted = True
        self._commit()


def backfill_campaign_targets():
    from r2.lib.db.operators import desc
    from r2.lib.utils import fetch_things2

    q = PromoCampaign._query(sort=desc("_date"), data=True)
    for campaign in fetch_things2(q):
        sr_name = campaign.sr_name or Frontpage.name
        campaign.target = Target(sr_name)
        campaign._commit()

class PromotionLog(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = tdb_cassandra.TIME_UUID_TYPE

    @classmethod
    def _rowkey(cls, link):
        return link._fullname

    @classmethod
    def add(cls, link, text):
        name = c.user.name if c.user_is_loggedin else "<AUTOMATED>"
        now = datetime.now(g.tz).strftime("%Y-%m-%d %H:%M:%S")
        text = "[%s: %s] %s" % (name, now, text)
        rowkey = cls._rowkey(link)
        column = {uuid1(): filters._force_utf8(text)}
        cls._set_values(rowkey, column)
        return text

    @classmethod
    def get(cls, link):
        rowkey = cls._rowkey(link)
        try:
            row = cls._byID(rowkey)
        except tdb_cassandra.NotFound:
            return []
        tuples = sorted(row._values().items(), key=lambda t: t[0].time)
        return [t[1] for t in tuples]


class PromotedLinkRoadblock(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    _compare_with = CompositeType(
        tdb_cassandra.DateType(),
        tdb_cassandra.DateType(),
    )

    @classmethod
    def _column(cls, start, end):
        start, end = map(to_datetime, [start, end])
        return {(start, end): ''}

    @classmethod
    def _dates_from_key(cls, key):
        start, end = map(to_date, key)
        return start, end

    @classmethod
    def add(cls, sr, start, end):
        rowkey = sr._id36
        column = cls._column(start, end)
        now = datetime.now(g.tz).date()
        ndays = (to_date(end) - now).days + 7
        ttl = timedelta(days=ndays).total_seconds()
        cls._set_values(rowkey, column, ttl=ttl)

    @classmethod
    def remove(cls, sr, start, end):
        rowkey = sr._id36
        column = cls._column(start, end)
        cls._remove(rowkey, column)

    @classmethod
    def is_roadblocked(cls, sr, start, end):
        rowkey = sr._id36
        start, end = map(to_date, [start, end])

        # retrieve columns for roadblocks starting before end
        try:
            columns = cls._cf.get(rowkey, column_finish=(to_datetime(end),),
                                  column_count=tdb_cassandra.max_column_count)
        except tdb_cassandra.NotFoundException:
            return False

        for key in columns.iterkeys():
            rb_start, rb_end = cls._dates_from_key(key)

            # check for overlap, end dates not inclusive
            if (start < rb_end) and (rb_start < end):
                return (rb_start, rb_end)
        return False

    @classmethod
    def get_roadblocks(cls):
        ret = []
        q = cls._cf.get_range()
        rows = list(q)
        srs = Subreddit._byID36([id36 for id36, columns in rows], data=True)
        for id36, columns in rows:
            sr = srs[id36]
            for key in columns.iterkeys():
                start, end = cls._dates_from_key(key)
                ret.append((sr.name, start, end))
        return ret
