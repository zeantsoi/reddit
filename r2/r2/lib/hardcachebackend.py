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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

from pylons import g
from datetime import timedelta as timedelta
from datetime import datetime
import sqlalchemy as sa
from r2.lib.db.tdb_lite import tdb_lite
import pytz

COUNT_CATEGORY = 'hc_count'
ELAPSED_CATEGORY = 'hc_elapsed'
TZ = pytz.timezone("UTC")

def expiration_from_time(time):
    if time <= 0:
        raise ValueError ("HardCache items *must* have an expiration time")
    return datetime.now(TZ) + timedelta(0, time)

class HardCacheBackend(object):
    def __init__(self, gc):
        self.tdb = tdb_lite(gc)
        self.profiling = gc.hardcache_profiling
        TZ = gc.display_tz

        def _table(metadata): 
            return sa.Table(gc.db_app_name + '_hardcache', metadata,
                            sa.Column('category', sa.String, nullable = False,
                                      primary_key = True),
                            sa.Column('ids', sa.String, nullable = False,
                                      primary_key = True),
                            sa.Column('value', sa.String, nullable = False),
                            sa.Column('kind', sa.String, nullable = False),
                            sa.Column('expiration',
                                      sa.DateTime(timezone = True),
                                      nullable = False)
                            )
        self.w_table = _table(self.tdb.make_metadata(gc.dbm.hardcache_db))
        self.r_table = _table(self.tdb.make_metadata(gc.dbm.hardcache_rdb))

        indstr = self.tdb.index_str(self.w_table, 'expiration', 'expiration')
        self.tdb.create_table(self.w_table, [ indstr ])
        self.tdb.create_table(self.r_table, [ indstr ])

    def profile_start(self, operation, category):
        if category == COUNT_CATEGORY:
            return None

        if category == ELAPSED_CATEGORY:
            return None

        if not self.profiling:
            return None

        return (datetime.now(TZ), operation, category)

    def profile_stop(self, t):
        if t is None:
            return

        start_time, operation, category = t

        end_time = datetime.now(TZ)

        period = end_time.strftime("%Y/%m/%d_H:%M")[:-1] + 'x'

        elapsed = end_time - start_time
        msec = elapsed.seconds * 1000 + elapsed.microseconds / 1000

        ids = "-".join((operation, category, period))

        self.add(COUNT_CATEGORY, ids, 0, time=86400)
        self.add(ELAPSED_CATEGORY, ids, 0, time=86400)

        self.incr(COUNT_CATEGORY, ids, time=86400)
        self.incr(ELAPSED_CATEGORY, ids, time=86400, delta=msec)


    def set(self, category, ids, val, time):

        self.delete(category, ids) # delete it if it already exists

        value, kind = self.tdb.py2db(val, True)

        expiration = expiration_from_time(time)

        prof = self.profile_start('set', category)

        self.w_table.insert().execute(
            category=category,
            ids=ids,
            value=value,
            kind=kind,
            expiration=expiration
            )

        self.profile_stop(prof)

    def add(self, category, ids, val, time=0):
        self.delete_if_expired(category, ids)

        expiration = expiration_from_time(time)

        value, kind = self.tdb.py2db(val, True)

        prof = self.profile_start('add', category)

        try:
            rp = self.w_table.insert().execute(
                category=category,
                ids=ids,
                value=value,
                kind=kind,
                expiration=expiration
                )
            self.profile_stop(prof)
            return value

        except sa.exceptions.IntegrityError, e:
            self.profile_stop(prof)
            return self.get(category, ids, force_write_table=True)

    def incr(self, category, ids, time=0, delta=1):
        self.delete_if_expired(category, ids)

        expiration = expiration_from_time(time)

        prof = self.profile_start('incr', category)

        rp = self.w_table.update(sa.and_(self.w_table.c.category==category,
                                         self.w_table.c.ids==ids,
                                         self.w_table.c.kind=='num'),
                               values = {
                                         self.w_table.c.value:
                                         sa.cast(
                                                 sa.cast(self.w_table.c.value,
                                                          sa.Integer) + delta,
                                                 sa.String),
                                         self.w_table.c.expiration: expiration
                                         }
                               ).execute()

        self.profile_stop(prof)

        if rp.rowcount == 1:
            return self.get(category, ids, force_write_table=True)
        elif rp.rowcount == 0:
            existing_value = self.get(category, ids, force_write_table=True)
            if existing_value is None:
                raise ValueError("[%s][%s] can't be incr()ed -- it's not set" %
                                 (category, ids))
            else:
                raise ValueError("[%s][%s] has non-integer value %r" %
                                 (category, ids, existing_value))
        else:
            raise ValueError("Somehow %d rows got updated" % rp.rowcount)

    def get(self, category, ids, force_write_table=False):
        if force_write_table:
            table = self.w_table
        else:
            table = self.r_table

        prof = self.profile_start('get', category)

        s = sa.select([table.c.value,
                       table.c.kind,
                       table.c.expiration],
                      sa.and_(table.c.category==category,
                              table.c.ids==ids),
                      limit = 1)
        rows = s.execute().fetchall()

        self.profile_stop(prof)

        if len(rows) < 1:
            return None
        elif rows[0].expiration < datetime.now(TZ):
            return None
        else:
            return self.tdb.db2py(rows[0].value, rows[0].kind)

    def get_multi(self, category, idses):
        prof = self.profile_start('get_multi', category)

        s = sa.select([self.r_table.c.ids,
                       self.r_table.c.value,
                       self.r_table.c.kind,
                       self.r_table.c.expiration],
                      sa.and_(self.r_table.c.category==category,
                              sa.or_(*[self.r_table.c.ids==ids
                                       for ids in idses])))
        rows = s.execute().fetchall()

        self.profile_stop(prof)

        results = {}

        for row in rows:
          if row.expiration >= datetime.now(TZ):
              k = "%s-%s" % (category, row.ids)
              results[k] = self.tdb.db2py(row.value, row.kind)

        return results

    def delete(self, category, ids):
        prof = self.profile_start('delete', category)
        self.w_table.delete(
            sa.and_(self.w_table.c.category==category,
                    self.w_table.c.ids==ids)).execute()
        self.profile_stop(prof)

    def ids_by_category(self, category, limit=1000):
        prof = self.profile_start('ids_by_category', category)
        s = sa.select([self.r_table.c.ids],
                      sa.and_(self.r_table.c.category==category,
                              self.r_table.c.expiration > datetime.now(TZ)),
                      limit = limit)
        rows = s.execute().fetchall()
        self.profile_stop(prof)
        return [ r.ids for r in rows ]

    def clause_from_expiration(self, expiration):
        if expiration is None:
            return True
        elif expiration == "now":
            return self.w_table.c.expiration < datetime.now(TZ)
        else:
            return self.w_table.c.expiration < expiration

    def expired(self, expiration_clause, limit=1000):
        s = sa.select([self.w_table.c.category,
                       self.w_table.c.ids,
                       self.w_table.c.expiration],
                      expiration_clause,
                      limit = limit,
                      order_by = self.w_table.c.expiration
                      )
        rows = s.execute().fetchall()
        return [ (r.expiration, r.category, r.ids) for r in rows ]

    def delete_if_expired(self, category, ids, expiration="now"):
        prof = self.profile_start('delete_if_expired', category)
        expiration_clause = self.clause_from_expiration(expiration)
        self.w_table.delete(sa.and_(self.w_table.c.category==category,
                                    self.w_table.c.ids==ids,
                                    expiration_clause)).execute()
        self.profile_stop(prof)


def delete_expired(expiration="now", limit=5000):
    hcb = HardCacheBackend(g)

    expiration_clause = hcb.clause_from_expiration(expiration)

    # Get all the expired keys
    rows = hcb.expired(expiration_clause, limit)

    if len(rows) == 0:
        return

    # Delete them from memcache
    mc_keys = [ "%s-%s" % (c, i) for e, c, i in rows ]
    g.memcache.delete_multi(mc_keys)

    # Now delete them from the backend.
    hcb.w_table.delete(expiration_clause).execute()

    # Note: In between the previous two steps, a key with a
    # near-instantaneous expiration could have been added and expired, and
    # thus it'll be deleted from the backend but not memcache. But that's
    # okay, because it should be expired from memcache anyway by now.
