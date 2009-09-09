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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.db.thing import Thing, Relation, NotFound
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import desc, lower
from r2.lib.db import queries
from r2.lib.memoize import memoize
from r2.models import Account
from pylons import c, g, request

class Award (Thing):
    @classmethod
    def all_awards(cls):
        return Award._query(limit=100,data=True)

    @staticmethod
    def _new(codename, title, imgurl):
#        print "Creating new award codename=%s title=%s imgurl=%s" % (
#            codename, title, imgurl)
        a = Award(codename=codename, title=title, imgurl=imgurl)
        a._commit()

    @classmethod
    def _by_codename(cls, codename):
        q = cls._query(lower(Award.c.codename) == codename.lower())
        q._limit = 1
        award = list(q)

        if award:
            return cls._byID(award[0]._id, True)
        else:
            raise NotFound, 'Award %s' % codename

class Trophy(Relation(Account, Award)):
    @staticmethod
    def _new(recipient, award, description = None,
             cup_expiration = None):

        # The "name" column of the relation can't be a constant or else a
        # given account would not be allowed to win a given award more than
        # once. So we're setting it to the string form of the timestamp.
        # Still, we won't have that date just yet, so for a moment we're
        # setting it to "trophy".

        t = Trophy(recipient, award, "trophy")

        t._name = str(t._date)

        if description:
            t.description = description

        if cup_expiration:
            recipient.extend_cup(cup_expiration)

        t._commit()

    @staticmethod
    def by_account(account):
        q = Trophy._query(Trophy.c._thing1_id == account._id,
                          eager_load = True, thing_data = True,
                          sort = desc('_date'))
        q._limit = 50
        return list(q)

    @staticmethod
    def by_award(award):
        q = Trophy._query(Trophy.c._thing2_id == award._id,
                          eager_load = True, thing_data = True,
                          sort = desc('_date'))
        q._limit = 500
        return list(q)
