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
from __future__ import with_statement

from pylons import c, g
from pylons.i18n import _

from r2.lib.db.thing import Thing, Relation, NotFound
from account import Account
from printable import Printable
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import lower, or_, and_, desc, asc
from r2.lib.memoize import memoize
from r2.lib.utils import tup, interleave_lists, last_modified_multi, flatten
from r2.lib.utils import timeago
from r2.lib.cache import sgm
from r2.lib.strings import strings, Score
from r2.lib.filters import _force_unicode
from r2.lib.db import tdb_cassandra
from r2.lib.cache import CL_ONE


import os.path
import random

class SubredditExists(Exception): pass

class Subreddit(Thing, Printable):
    # Note: As of 2010/03/18, nothing actually overrides the static_path
    # attribute, even on a cname. So c.site.static_path should always be
    # the same as g.static_path.
    _defaults = dict(static_path = g.static_path,
                     stylesheet = None,
                     stylesheet_rtl = None,
                     stylesheet_contents = '',
                     stylesheet_hash     = '0',
                     firsttext = strings.firsttext,
                     header = None,
                     header_title = "",
                     allow_top = False, # overridden in "_new"
                     description = '',
                     images = {},
                     reported = 0,
                     valid_votes = 0,
                     show_media = False,
                     css_on_cname = True,
                     domain = None,
                     over_18 = False,
                     mod_actions = 0,
                     sponsorship_text = "this reddit is sponsored by",
                     sponsorship_url = None,
                     sponsorship_img = None,
                     sponsorship_name = None,
                     # do we allow self-posts, links only, or any?
                     link_type = 'any', # one of ('link', 'self', 'any')
                     flair_enabled = True,
                     flair_position = 'right', # one of ('left', 'right')
                     )
    _essentials = ('type', 'name', 'lang')
    _data_int_props = Thing._data_int_props + ('mod_actions', 'reported')

    sr_limit = 50

    # note: for purposely unrenderable reddits (like promos) set author_id = -1
    @classmethod
    def _new(cls, name, title, author_id, ip, lang = g.lang, type = 'public',
             over_18 = False, **kw):
        with g.make_lock('create_sr_' + name.lower()):
            try:
                sr = Subreddit._by_name(name)
                raise SubredditExists
            except NotFound:
                if "allow_top" not in kw:
                    kw['allow_top'] = True
                sr = Subreddit(name = name,
                               title = title,
                               lang = lang,
                               type = type,
                               over_18 = over_18,
                               author_id = author_id,
                               ip = ip,
                               **kw)
                sr._commit()

                #clear cache
                Subreddit._by_name(name, _update = True)
                return sr


    _specials = {}

    @classmethod
    def _by_name(cls, names, stale=False, _update = False):
        #lower name here so there is only one cache
        names, single = tup(names, True)

        to_fetch = {}
        ret = {}

        for name in names:
            lname = name.lower()

            if lname in cls._specials:
                ret[name] = cls._specials[lname]
            else:
                to_fetch[lname] = name

        if to_fetch:
            def _fetch(lnames):
                q = cls._query(lower(cls.c.name) == lnames,
                               cls.c._spam == (True, False),
                               limit = len(lnames),
                               data=True)
                try:
                    srs = list(q)
                except UnicodeEncodeError:
                    print "Error looking up SRs %r" % (lnames,)
                    raise

                return dict((sr.name.lower(), sr._id)
                            for sr in srs)

            srs = {}
            srids = sgm(g.cache, to_fetch.keys(), _fetch, prefix='subreddit.byname', stale=stale)
            if srids:
                srs = cls._byID(srids.values(), data=True, return_dict=False, stale=stale)

            for sr in srs:
                ret[to_fetch[sr.name.lower()]] = sr

        if ret and single:
            return ret.values()[0]
        elif not ret and single:
            raise NotFound, 'Subreddit %s' % name
        else:
            return ret

    @classmethod
    @memoize('subreddit._by_domain')
    def _by_domain_cache(cls, name):
        q = cls._query(cls.c.domain == name,
                       limit = 1)
        l = list(q)
        if l:
            return l[0]._id

    @classmethod
    def _by_domain(cls, domain, _update = False):
        sr_id = cls._by_domain_cache(_force_unicode(domain).lower(),
                                     _update = _update)
        if sr_id:
            return cls._byID(sr_id, True)
        else:
            return None

    @property
    def moderators(self):
        return self.moderator_ids()

    @property
    def contributors(self):
        return self.contributor_ids()

    @property
    def banned(self):
        return self.banned_ids()

    @property
    def subscribers(self):
        return self.subscriber_ids()

    @property
    def flair(self):
        return self.flair_ids()

    def flair_id_query(self, limit, after, reverse=False):
        extra_rules = [
            Flair.c._thing1_id == self._id,
            Flair.c._name == 'flair',
          ]
        if after:
            if reverse:
                extra_rules.append(Flair.c._thing2_id < after._id)
            else:
                extra_rules.append(Flair.c._thing2_id > after._id)
        sort = (desc if reverse else asc)('_thing2_id')
        return Flair._query(*extra_rules, sort=sort, limit=limit)

    def spammy(self):
        return self._spam

    def can_comment(self, user):
        if c.user_is_admin:
            return True
        elif self.is_banned(user):
            return False
        elif self.type in ('public','restricted'):
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #private requires contributorship
            return True
        else:
            return False

    def can_submit(self, user):
        if c.user_is_admin:
            return True
        elif self.is_banned(user):
            return False
        elif self.type == 'public':
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #restricted/private require contributorship
            return True
        else:
            return False

    def can_ban(self,user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)))

    def can_distinguish(self,user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)))

    def can_change_stylesheet(self, user):
        if c.user_is_loggedin:
            return c.user_is_admin or self.is_moderator(user)
        else:
            return False

    def is_special(self, user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)
                     or self.is_contributor(user)))

    def can_give_karma(self, user):
        return self.is_special(user)

    def should_ratelimit(self, user, kind):
        if c.user_is_admin or self.is_special(user):
            return False

        if kind == 'comment':
            rl_karma = g.MIN_RATE_LIMIT_COMMENT_KARMA
        else:
            rl_karma = g.MIN_RATE_LIMIT_KARMA

        return user.karma(kind, self) < rl_karma

    def can_view(self, user):
        if c.user_is_admin:
            return True

        if self.type in ('public', 'restricted'):
            return True
        elif c.user_is_loggedin:
            #private requires contributorship
            return self.is_contributor(user) or self.is_moderator(user)

    def can_demod(self, bully, victim):
        # This works because the is_*() functions return the relation
        # when True. So we can compare the dates on the relations.
        bully_rel = self.is_moderator(bully)
        victim_rel = self.is_moderator(victim)
        if bully_rel is None or victim_rel is None:
            return False
        return bully_rel._date <= victim_rel._date

    @classmethod
    def load_subreddits(cls, links, return_dict = True, stale=False):
        """returns the subreddits for a list of links. it also preloads the
        permissions for the current user."""
        srids = set(l.sr_id for l in links
                    if getattr(l, "sr_id", None) is not None)
        subreddits = {}
        if srids:
            subreddits = cls._byID(srids, data=True, stale=stale)

        if subreddits and c.user_is_loggedin:
            # dict( {Subreddit,Account,name} -> Relationship )
            SRMember._fast_query(subreddits.values(), (c.user,),
                                 ('subscriber','contributor','moderator'),
                                 data=True, eager_load=True, thing_data=True)

        return subreddits if return_dict else subreddits.values()

    #rising uses this to know which subreddits to include, doesn't
    #work for all/friends atm
    def rising_srs(self):
        if c.default_sr or not hasattr(self, '_id'):
            user = c.user if c.user_is_loggedin else None
            sr_ids = self.user_subreddits(user)
        else:
            sr_ids = (self._id,)
        return sr_ids

    def get_links(self, sort, time):
        from r2.lib.db import queries
        return queries.get_links(self, sort, time)

    def get_spam(self):
        from r2.lib.db import queries
        return queries.get_spam(self)

    def get_reported(self):
        from r2.lib.db import queries
        return queries.get_reported(self)

    def get_trials(self):
        from r2.lib.db import queries
        return queries.get_trials(self)

    def get_modqueue(self):
        from r2.lib.db import queries
        return queries.get_modqueue(self)

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_sr_comments(self)


    @classmethod
    def add_props(cls, user, wrapped):
        names = ('subscriber', 'moderator', 'contributor')
        rels = (SRMember._fast_query(wrapped, [user], names) if c.user_is_loggedin else {})
        defaults = Subreddit.default_subreddits()
        for item in wrapped:
            if not user or not user.has_subscribed:
                item.subscriber = item._id in defaults
            else:
                item.subscriber = bool(rels.get((item, user, 'subscriber')))
            item.moderator = bool(rels.get((item, user, 'moderator')))
            item.contributor = bool(item.type != 'public' and
                                    (item.moderator or
                                     rels.get((item, user, 'contributor'))))

            # Don't reveal revenue information via /r/lounge's subscribers
            if (g.lounge_reddit and item.name == g.lounge_reddit
                and not c.user_is_admin):
                item._ups = 0

            item.score = item._ups

            # override "voting" score behavior (it will override the use of
            # item.score in builder.py to be ups-downs)
            item.likes = item.subscriber or None
            base_score = item.score - (1 if item.likes else 0)
            item.voting_score = [(base_score + x - 1) for x in range(3)]
            item.score_fmt = Score.subscribers

            #will seem less horrible when add_props is in pages.py
            from r2.lib.pages import UserText
            item.usertext = UserText(item, item.description)


        Printable.add_props(user, wrapped)
    #TODO: make this work
    cache_ignore = set(["subscribers"]).union(Printable.cache_ignore)
    @staticmethod
    def wrapped_cache_key(wrapped, style):
        s = Printable.wrapped_cache_key(wrapped, style)
        s.extend([wrapped._spam])
        return s

    @classmethod
    def top_lang_srs(cls, lang, limit, filter_allow_top = False, over18 = True,
                     over18_only = False, ids=False, stale=False):
        from r2.lib import sr_pops
        lang = tup(lang)

        sr_ids = sr_pops.pop_reddits(lang, over18, over18_only, filter_allow_top = filter_allow_top)
        sr_ids = sr_ids[:limit]

        return (sr_ids if ids
                else Subreddit._byID(sr_ids, data=True, return_dict=False, stale=stale))

    @classmethod
    def default_subreddits(cls, ids = True, over18 = False, limit = g.num_default_reddits,
                           stale=True):
        """
        Generates a list of the subreddits any user with the current
        set of language preferences and no subscriptions would see.

        An optional kw argument 'limit' is defaulted to g.num_default_reddits
        """

        # we'll let these be unordered for now
        auto_srs = []
        if g.automatic_reddits:
            auto_srs = map(lambda sr: sr._id,
                           Subreddit._by_name(g.automatic_reddits, stale=stale).values())

        srs = cls.top_lang_srs(c.content_langs, limit + len(auto_srs),
                               filter_allow_top = True,
                               over18 = over18, ids = True,
                               stale=stale)

        rv = []
        for sr in srs:
            if len(rv) >= limit:
                break
            if sr in auto_srs:
                continue
            rv.append(sr)

        rv = auto_srs + rv

        return rv if ids else Subreddit._byID(rv, data=True, return_dict=False, stale=stale)

    @classmethod
    @memoize('random_reddits', time = 1800)
    def random_reddits(cls, user_name, sr_ids, limit):
        """This gets called when a user is subscribed to more than 50
        reddits. Randomly choose 50 of those reddits and cache it for
        a while so their front page doesn't jump around."""
        return random.sample(sr_ids, limit)

    @classmethod
    def random_reddit(cls, limit = 1000, over18 = False):
        srs = cls.top_lang_srs(c.content_langs, limit,
                               filter_allow_top = False,
                               over18 = over18,
                               over18_only = over18,
                               ids=True)
        return (Subreddit._byID(random.choice(srs))
                if srs else Subreddit._by_name(g.default_sr))

    @classmethod
    def user_subreddits(cls, user, ids = True, over18=False, limit = sr_limit, stale=False):
        """
        subreddits that appear in a user's listings. If the user has
        subscribed, returns the stored set of subscriptions.

        Otherwise, return the default set.
        """
        # note: for user not logged in, the fake user account has
        # has_subscribed == False by default.
        if user and user.has_subscribed:
            sr_ids = Subreddit.reverse_subscriber_ids(user)

            # Allow the goldies to see more subreddits
            if user.gold:
                limit = 100

            if limit and len(sr_ids) > limit:
                sr_ids.sort()
                sr_ids = cls.random_reddits(user.name, sr_ids, limit)
            return sr_ids if ids else Subreddit._byID(sr_ids,
                                                      data=True,
                                                      return_dict=False,
                                                      stale=stale)
        else:
            return cls.default_subreddits(ids = ids, over18=over18,
                                          limit=g.num_default_reddits,
                                          stale=stale)

    @classmethod
    @memoize('subreddit.special_reddits')
    def special_reddits_cache(cls, user_id, query_param):
        reddits = SRMember._query(SRMember.c._name == query_param,
                                  SRMember.c._thing2_id == user_id,
                                  #hack to prevent the query from
                                  #adding it's own date
                                  sort = (desc('_t1_ups'), desc('_t1_date')),
                                  eager_load = True,
                                  thing_data = True,
                                  limit = 100)

        return [ sr._thing1_id for sr in reddits ]

    # Used to pull all of the SRs a given user moderates or is a contributor
    # to (which one is controlled by query_param)
    @classmethod
    def special_reddits(cls, user, query_param, _update=False):
        return cls.special_reddits_cache(user._id, query_param, _update=_update)

    def is_subscriber_defaults(self, user):
        if user.has_subscribed:
            return self.is_subscriber(user)
        else:
            return self in self.default_subreddits(ids = False)

    @classmethod
    def subscribe_defaults(cls, user):
        if not user.has_subscribed:
            for sr in cls.user_subreddits(None, False,
                                          limit = g.num_default_reddits):
                #this will call reverse_subscriber_ids after every
                #addition. if it becomes a problem we should make an
                #add_multiple_subscriber fn
                if sr.add_subscriber(user):
                    sr._incr('_ups', 1)
            user.has_subscribed = True
            user._commit()

    @classmethod
    def submit_sr_names(cls, user):
        """subreddit names that appear in a user's submit page. basically a
        sorted/rearranged version of user_subreddits()."""
        srs = cls.user_subreddits(user, ids = False)
        names = [s.name for s in srs if s.can_submit(user)]
        names.sort()

        #add the current site to the top (default_sr)
        if g.default_sr in names:
            names.remove(g.default_sr)
            names.insert(0, g.default_sr)

        if c.lang in names:
            names.remove(c.lang)
            names.insert(0, c.lang)

        return names

    @property
    def path(self):
        return "/r/%s/" % self.name


    def keep_item(self, wrapped):
        if c.user_is_admin:
            return True

        user = c.user if c.user_is_loggedin else None
        return self.can_view(user)

    def get_images(self):
        """
        Iterator over list of (name, image_num) pairs which have been
        uploaded for custom styling of this subreddit.
        """
        for name, img_num in self.images.iteritems():
            if isinstance(img_num, int):
                yield (name, img_num)

    def add_image(self, name, max_num = None):
        """
        Adds an image to the subreddit's image list.  The resulting
        number of the image is returned.  Note that image numbers are
        non-sequential insofar as unused numbers in an existing range
        will be populated before a number outside the range is
        returned.  Imaged deleted with del_image are pushed onto the
        "/empties/" stack in the images dict, and those values are
        pop'd until the stack is empty.

        raises ValueError if the resulting number is >= max_num.

        The Subreddit will be _dirty if a new image has been added to
        its images list, and no _commit is called.
        """
        if not self.images.has_key(name):
            # copy and blank out the images list to flag as _dirty
            l = self.images
            self.images = None
            # initialize the /empties/ list 
            l.setdefault('/empties/', [])
            try:
                num = l['/empties/'].pop() # grab old number if we can
            except IndexError:
                num = len(l) - 1 # one less to account for /empties/ key
            if max_num is not None and num >= max_num:
                raise ValueError, "too many images"
            # update the dictionary and rewrite to images attr
            l[name] = num
            self.images = l
        else:
            # we've seen the image before, so just return the existing num
            num = self.images[name]
        return num

    def del_image(self, name):
        """
        Deletes an image from the images dictionary assuming an image
        of that name is in the current dictionary.  The freed up
        number is pushed onto the /empties/ stack for later recycling
        by add_image.

        The Subreddit will be _dirty if image has been removed from
        its images list, and no _commit is called.
        """
        if self.images.has_key(name):
            l = self.images
            self.images = None
            l.setdefault('/empties/', [])
            # push the number on the empties list
            l['/empties/'].append(l[name])
            del l[name]
            self.images = l

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if isinstance(self, FakeSubreddit):
            return self is other

        return self._id == other._id

    def __ne__(self, other):
        return not self.__eq__(other)


class FakeSubreddit(Subreddit):
    over_18 = False
    _nodb = True

    def __init__(self):
        Subreddit.__init__(self)
        self.title = ''

    def is_moderator(self, user):
        return c.user_is_loggedin and c.user_is_admin

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user):
        return False

    def can_change_stylesheet(self, user):
        return False

    def is_banned(self, user):
        return False

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_all_comments()

    def spammy(self):
        return False

class FriendsSR(FakeSubreddit):
    name = 'friends'
    title = 'friends'

    @classmethod
    @memoize("get_important_friends", 5*60)
    def get_important_friends(cls, user_id, max_lookup = 500, limit = 100):
        a = Account._byID(user_id, data = True)
        # friends are returned chronologically by date, so pick the end of the list
        # for the most recent additions
        friends = Account._byID(a.friends[-max_lookup:], return_dict = False,
                                data = True)

        # if we don't have a last visit for your friends, we don't
        # care about them
        last_visits = last_modified_multi(friends, "submitted")
        friends = [x for x in friends if x in last_visits]

        # sort friends by most recent interactions
        friends.sort(key = lambda x: last_visits[x], reverse = True)
        return [x._id for x in friends[:limit]]

    def get_links(self, sort, time):
        from r2.lib.db import queries
        from r2.models import Link
        from r2.controllers.errors import UserRequiredException

        if not c.user_is_loggedin:
            raise UserRequiredException

        friends = self.get_important_friends(c.user._id)

        if not friends:
            return []

        if g.use_query_cache:
            # with the precomputer enabled, this Subreddit only supports
            # being sorted by 'new'. it would be nice to have a
            # cleaner UI than just blatantly ignoring their sort,
            # though
            sort = 'new'
            time = 'all'

            friends = Account._byID(friends, return_dict=False)

            crs = [queries.get_submitted(friend, sort, time)
                   for friend in friends]
            return queries.MergedCachedResults(crs)

        else:
            q = Link._query(Link.c.author_id == friends,
                            sort = queries.db_sort(sort),
                            data = True)
            if time != 'all':
                q._filter(queries.db_times[time])
            return q

    def get_all_comments(self):
        from r2.lib.db import queries
        from r2.models import Comment
        from r2.controllers.errors import UserRequiredException

        if not c.user_is_loggedin:
            raise UserRequiredException

        friends = self.get_important_friends(c.user._id)

        if not friends:
            return []

        if g.use_query_cache:
            # with the precomputer enabled, this Subreddit only supports
            # being sorted by 'new'. it would be nice to have a
            # cleaner UI than just blatantly ignoring their sort,
            # though
            sort = 'new'
            time = 'all'

            friends = Account._byID(friends,
                                    return_dict=False)

            crs = [queries.get_comments(friend, sort, time)
                   for friend in friends]
            return queries.MergedCachedResults(crs)

        else:
            q = Comment._query(Comment.c.author_id == friends,
                               sort = desc('_date'),
                               data = True)
            return q

class AllSR(FakeSubreddit):
    name = 'all'
    title = 'all'

    def get_links(self, sort, time):
        from r2.lib import promote
        from r2.models import Link
        from r2.lib.db import queries
        q = Link._query(Link.c.sr_id > 0,
                        sort = queries.db_sort(sort),
                        read_cache = True,
                        write_cache = True,
                        cache_time = 60,
                        data = True,
                        filter_primary_sort_only=True)
        if time != 'all':
            q._filter(queries.db_times[time])
        return q

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_all_comments()

    def rising_srs(self):
        return None


class _DefaultSR(FakeSubreddit):
    #notice the space before reddit.com
    name = ' reddit.com'
    path = '/'
    header = g.default_header_url

    def get_links_sr_ids(self, sr_ids, sort, time):
        from r2.lib.db import queries
        from r2.models import Link

        if not sr_ids:
            return []
        else:
            srs = Subreddit._byID(sr_ids, data=True, return_dict = False)

        if g.use_query_cache:
            results = [queries.get_links(sr, sort, time)
                       for sr in srs]
            return queries.merge_results(*results)
        else:
            q = Link._query(Link.c.sr_id == sr_ids,
                            sort = queries.db_sort(sort), data=True)
            if time != 'all':
                q._filter(queries.db_times[time])
            return q

    def get_links(self, sort, time):
        user = c.user if c.user_is_loggedin else None
        sr_ids = Subreddit.user_subreddits(user)
        return self.get_links_sr_ids(sr_ids, sort, time)

    @property
    def title(self):
        return _("reddit: the front page of the internet")

# This is the base class for the instantiated front page reddit
class DefaultSR(_DefaultSR):
    def __init__(self):
        _DefaultSR.__init__(self)
        try:
            self._base = Subreddit._by_name(g.default_sr)
        except NotFound:
            self._base = None

    @property
    def _fullname(self):
        return "t5_6"

    @property
    def header(self):
        return (self._base and self._base.header) or _DefaultSR.header


    @property
    def header_title(self):
        return (self._base and self._base.header_title) or ""

    @property
    def stylesheet_contents(self):
        return self._base.stylesheet_contents if self._base else ""

    @property
    def sponsorship_url(self):
        return self._base.sponsorship_url if self._base else ""

    @property
    def sponsorship_text(self):
        return self._base.sponsorship_text if self._base else ""

    @property
    def sponsorship_img(self):
        return self._base.sponsorship_img if self._base else ""



class MultiReddit(_DefaultSR):
    name = 'multi'
    header = ""

    def __init__(self, sr_ids, path):
        _DefaultSR.__init__(self)
        self.real_path = path
        self.sr_ids = sr_ids

    def spammy(self):
        srs = Subreddit._byID(self.sr_ids, return_dict=False)
        return any(sr._spam for sr in srs)

    @property
    def path(self):
        return '/r/' + self.real_path

    def get_links(self, sort, time):
        return self.get_links_sr_ids(self.sr_ids, sort, time)

    def rising_srs(self):
        return self.sr_ids

    def get_all_comments(self):
        from r2.lib.db.queries import get_sr_comments, merge_results
        srs = Subreddit._byID(self.sr_ids, return_dict=False)
        results = [get_sr_comments(sr) for sr in srs]
        return merge_results(*results)

class RandomReddit(FakeSubreddit):
    name = 'random'
    header = ""

class RandomNSFWReddit(FakeSubreddit):
    name = 'randnsfw'
    header = ""

class ModContribSR(_DefaultSR):
    name  = None
    title = None
    query_param = None
    real_path = None

    @property
    def path(self):
        return '/r/' + self.real_path

    def sr_ids(self):
        if c.user_is_loggedin:
            return Subreddit.special_reddits(c.user, self.query_param)
        else:
            return []

    def get_links(self, sort, time):
        return self.get_links_sr_ids(self.sr_ids(), sort, time)

class ModSR(ModContribSR):
    name  = "communities you moderate"
    title = "communities you moderate"
    query_param = "moderator"
    real_path = "mod"

class ContribSR(ModContribSR):
    name  = "contrib"
    title = "communities you're approved on"
    query_param = "contributor"
    real_path = "contrib"

class SubSR(FakeSubreddit):
    stylesheet = 'subreddit.css'
    #this will make the javascript not send an SR parameter
    name = ''

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user):
        return True

    @property
    def path(self):
        return "/reddits/"

class DomainSR(FakeSubreddit):
    @property
    def path(self):
        return '/domain/' + self.domain

    def __init__(self, domain):
        FakeSubreddit.__init__(self)
        self.domain = domain
        self.name = domain 
        self.title = domain + ' ' + _('on reddit.com')

    def get_links(self, sort, time):
        from r2.lib.db import queries
        # TODO: once the lists are precomputed properly, this can be
        # switched over to use the non-_old variety.
        return queries.get_domain_links(self.domain, sort, time)

Sub = SubSR()
Friends = FriendsSR()
Mod = ModSR()
Contrib = ContribSR()
All = AllSR()
Random = RandomReddit()
RandomNSFW = RandomNSFWReddit()

Subreddit._specials.update(dict(friends = Friends,
                                randnsfw = RandomNSFW,
                                random = Random,
                                mod = Mod,
                                contrib = Contrib,
                                all = All))

class SRMember(Relation(Subreddit, Account)): pass
Subreddit.__bases__ += (UserRel('moderator', SRMember),
                        UserRel('contributor', SRMember),
                        UserRel('subscriber', SRMember, disable_ids_fn = True),
                        UserRel('banned', SRMember))

class Flair(Relation(Subreddit, Account)):
    @classmethod
    def store(cls, sr, account, text = None, css_class = None):
        flair = Flair(sr, account, 'flair', text = text, css_class = css_class)
        flair._commit()

        setattr(account, 'flair_%s_text' % sr._id, text)
        setattr(account, 'flair_%s_css_class' % sr._id, css_class)
        account._commit()

    @classmethod
    @memoize('flair.all_flair_by_sr')
    def all_flair_by_sr_cache(cls, sr_id):
        q = cls._query(cls.c._thing1_id == sr_id)
        return [t._id for t in q]

    @classmethod
    def all_flair_by_sr(cls, sr_id, _update=False):
        relids = cls.all_flair_by_sr_cache(sr_id, _update=_update)
        return cls._byID(relids).itervalues()

Subreddit.__bases__ += (UserRel('flair', Flair,
                                disable_ids_fn = True,
                                disable_reverse_ids_fn = True),)

class SubredditPopularityByLanguage(tdb_cassandra.View):
    _use_db = True
    _value_type = 'pickle'
    _use_new_ring = True
    _read_consistency_level = CL_ONE
