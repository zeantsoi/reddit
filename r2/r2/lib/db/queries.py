from r2.models import Account, Link, Comment, Trial, Vote, SaveHide
from r2.models import Message, Inbox, Subreddit, ModContribSR, ModeratorInbox
from r2.lib.db.thing import Thing, Merge
from r2.lib.db.operators import asc, desc, timeago
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import fetch_things2, tup, UniqueIterator, set_last_modified
from r2.lib import utils
from r2.lib.solrsearch import DomainSearchQuery
from r2.lib import amqp, sup, filters
from r2.lib.comment_tree import add_comments, update_comment_votes
from r2.models.query_cache import cached_query, merged_cached_query, UserQueryCache, CachedQueryMutator
from r2.models.query_cache import ThingTupleComparator

import cPickle as pickle

from datetime import datetime
import itertools
import collections

from pylons import g
query_cache = g.permacache
log = g.log
make_lock = g.make_lock
worker = amqp.worker

precompute_limit = 1000

db_sorts = dict(hot = (desc, '_hot'),
                new = (desc, '_date'),
                top = (desc, '_score'),
                controversial = (desc, '_controversy'))

def db_sort(sort):
    cls, col = db_sorts[sort]
    return cls(col)

search_sort = dict(hot = 'hot desc',
                   new = 'date desc',
                   top = 'points desc',
                   controversial = 'controversy desc',
                   old = 'date asc')

db_times = dict(all = None,
                hour = Thing.c._date >= timeago('1 hour'),
                day = Thing.c._date >= timeago('1 day'),
                week = Thing.c._date >= timeago('1 week'),
                month = Thing.c._date >= timeago('1 month'),
                year = Thing.c._date >= timeago('1 year'))

# sorts for which there can be a time filter (by day, by week,
# etc). All of these but 'all' are done in mr_top, who knows about the
# structure of the stored CachedResults (so changes here may warrant
# changes there)
time_filtered_sorts = set(('top', 'controversial'))

#we need to define the filter functions here so cachedresults can be pickled
def filter_identity(x):
    return x

def filter_thing2(x):
    """A filter to apply to the results of a relationship query returns
    the object of the relationship."""
    return x._thing2

class CachedResults(object):
    """Given a query returns a list-like object that will lazily look up
    the query from the persistent cache. """
    def __init__(self, query, filter):
        self.query = query
        self.query._limit = precompute_limit
        self.filter = filter
        self.iden = self.query._iden()
        self.sort_cols = [s.col for s in self.query._sort]
        self.data = []
        self._fetched = False

    @property
    def sort(self):
        return self.query._sort

    def fetch(self, force=False):
        """Loads the query from the cache."""
        self.fetch_multi([self], force=force)

    @classmethod
    def fetch_multi(cls, crs, force=False):
        unfetched = filter(lambda cr: force or not cr._fetched, crs)
        if not unfetched:
            return

        cached = query_cache.get_multi([cr.iden for cr in unfetched],
                                       allow_local = not force)
        for cr in unfetched:
            cr.data = cached.get(cr.iden) or []
            cr._fetched = True

    def make_item_tuple(self, item):
        """Given a single 'item' from the result of a query build the tuple
        that will be stored in the query cache. It is effectively the
        fullname of the item after passing through the filter plus the
        columns of the unfiltered item to sort by."""
        filtered_item = self.filter(item)
        lst = [filtered_item._fullname]
        for col in self.sort_cols:
            #take the property of the original 
            attr = getattr(item, col)
            #convert dates to epochs to take less space
            if isinstance(attr, datetime):
                attr = epoch_seconds(attr)
            lst.append(attr)
        return tuple(lst)

    def can_insert(self):
        """True if a new item can just be inserted rather than
           rerunning the query."""
         # This is only true in some circumstances: queries where
         # eligibility in the list is determined only by its sort
         # value (e.g. hot) and where addition/removal from the list
         # incurs an insertion/deletion event called on the query. So
         # the top hottest items in X some subreddit where the query
         # is notified on every submission/banning/unbanning/deleting
         # will work, but for queries with a time-component or some
         # other eligibility factor, it cannot be inserted this way.
        if self.query._sort in ([desc('_date')],
                                [desc('_hot'), desc('_date')],
                                [desc('_score'), desc('_date')],
                                [desc('_controversy'), desc('_date')]):
            if not any(r for r in self.query._rules
                       if r.lval.name == '_date'):
                # if no time-rule is specified, then it's 'all'
                return True
        return False

    def can_delete(self):
        "True if a item can be removed from the listing, always true for now."
        return True

    def _mutate(self, fn, willread=True):
        self.data = query_cache.mutate(self.iden, fn, default=[], willread=willread)
        self._fetched=True

    def insert(self, items):
        """Inserts the item into the cached data. This only works
           under certain criteria, see can_insert."""
        self._insert_tuples([self.make_item_tuple(item) for item in tup(items)])

    def _insert_tuples(self, t):
        def _mutate(data):
            data = data or []

            # short-circuit if we already know that no item to be
            # added qualifies to be stored. Since we know that this is
            # sorted descending by datum[1:], we can just check the
            # last item and see if we're smaller than it is
            if (len(data) >= precompute_limit
                and all(x[1:] < data[-1][1:]
                        for x in t)):
                return data

            # insert the new items, remove the duplicates (keeping the
            # one being inserted over the stored value if applicable),
            # and sort the result
            newfnames = set(x[0] for x in t)
            data = filter(lambda x: x[0] not in newfnames, data)
            data.extend(t)
            data.sort(reverse=True, key=lambda x: x[1:])
            if len(t) + len(data) > precompute_limit:
                data = data[:precompute_limit]
            return data

        self._mutate(_mutate)

    def delete(self, items):
        """Deletes an item from the cached data."""
        fnames = set(self.filter(x)._fullname for x in tup(items))

        def _mutate(data):
            data = data or []
            return filter(lambda x: x[0] not in fnames,
                          data)

        self._mutate(_mutate)

    def _replace(self, tuples):
        """Take pre-rendered tuples from mr_top and replace the
           contents of the query outright. This should be considered a
           private API"""
        def _mutate(data):
            return tuples
        self._mutate(_mutate, willread=False)

    def update(self):
        """Runs the query and stores the result in the cache. This is
           only run by hand."""
        self.data = [self.make_item_tuple(i) for i in self.query]
        self._fetched = True
        query_cache.set(self.iden, self.data)

    def __repr__(self):
        return '<CachedResults %s %s>' % (self.query._rules, self.query._sort)

    def __iter__(self):
        self.fetch()

        for x in self.data:
            yield x[0]

class MergedCachedResults(object):
    """Given two CachedResults, merges their lists based on the sorts
       of their queries."""
    # normally we'd do this by having a superclass of CachedResults,
    # but we have legacy pickled CachedResults that we don't want to
    # break

    def __init__(self, results):
        self.cached_results = results
        CachedResults.fetch_multi([r for r in results
                                   if isinstance(r, CachedResults)])
        self._fetched = True

        self.sort = results[0].sort
        comparator = ThingTupleComparator(self.sort)
        # make sure they're all the same
        assert all(r.sort == self.sort for r in results[1:])

        all_items = []
        for cr in results:
            all_items.extend(cr.data)
        all_items.sort(cmp=comparator)
        self.data = all_items


    def __repr__(self):
        return '<MergedCachedResults %r>' % (self.cached_results,)

    def __iter__(self):
        for x in self.data:
            yield x[0]

    def update(self):
        for x in self.cached_results:
            x.update()

def make_results(query, filter = filter_identity):
    if g.use_query_cache:
        return CachedResults(query, filter)
    else:
        query.prewrap_fn = filter
        return query

def merge_results(*results):
    if not results:
        return QueryishList([])
    elif g.use_query_cache:
        return MergedCachedResults(results)
    else:
        assert all((results[0]._sort == r._sort
                    and results[0].prewrap_fn == r.prewrap_fn)
                   for r in results)
        m = Merge(results, sort = results[0]._sort)
        m.prewrap_fn = results[0].prewrap_fn
        return m


@cached_query(UserQueryCache)
def get_deleted_links(user_id):
    return Link._query(Link.c.author_id == user_id,
                       Link.c._deleted == True,
                       Link.c._spam == (True, False),
                       sort=db_sort('new'))


@cached_query(UserQueryCache)
def get_deleted_comments(user_id):
    return Comment._query(Comment.c.author_id == user_id,
                          Comment.c._deleted == True,
                          Comment.c._spam == (True, False),
                          sort=db_sort('new'))


@merged_cached_query
def get_deleted(user):
    return [get_deleted_links(user),
            get_deleted_comments(user)]


def get_links(sr, sort, time):
    return _get_links(sr._id, sort, time)

def _get_links(sr_id, sort, time):
    """General link query for a subreddit."""
    q = Link._query(Link.c.sr_id == sr_id,
                    sort = db_sort(sort),
                    data = True)

    if time != 'all':
        q._filter(db_times[time])

    res = make_results(q)

    return res

def get_spam_links(sr):
    q_l = Link._query(Link.c.sr_id == sr._id,
                      Link.c._spam == True,
                      sort = db_sort('new'))
    return make_results(q_l)

def get_spam_comments(sr):
    q_c = Comment._query(Comment.c.sr_id == sr._id,
                         Comment.c._spam == True,
                         sort = db_sort('new'))
    return make_results(q_c)

def get_spam(sr):
    if isinstance(sr, ModContribSR):
        srs = Subreddit._byID(sr.sr_ids(), return_dict=False)
        results = [ get_spam_links(sr) for sr in srs ]
        return merge_results(*results)
    else:
        return merge_results(get_spam_links(sr),
                             get_spam_comments(sr))

def get_reported_links(sr):
    q_l = Link._query(Link.c.reported != 0,
                      Link.c.sr_id == sr._id,
                      Link.c._spam == False,
                      sort = db_sort('new'))
    return make_results(q_l)

def get_reported_comments(sr):
    q_c = Comment._query(Comment.c.reported != 0,
                         Comment.c.sr_id == sr._id,
                         Comment.c._spam == False,
                         sort = db_sort('new'))
    return make_results(q_c)

def get_reported(sr):
    if isinstance(sr, ModContribSR):
        srs = Subreddit._byID(sr.sr_ids(), return_dict=False)
        results = []
        results.extend(get_reported_links(sr) for sr in srs)
        results.extend(get_reported_comments(sr) for sr in srs)
        return merge_results(*results)
    else:
        return merge_results(get_reported_links(sr),
                             get_reported_comments(sr))

# TODO: Wow, what a hack. I'm doing this in a hurry to make
# /r/blah/about/trials and /r/blah/about/modqueue work. At some point
# before the heat death of the universe, we should start precomputing
# these things instead. That would require an "on_trial" attribute to be
# maintained on Links, a precomputer that keeps track of such links,
# and changes to:
#   trial_utils.py:  trial_info(), end_trial(), indict()
#   trial.py:        all_defendants_cache()
class QueryishList(list):
    prewrap_fn = None
    _rules = None
    _sort = None

    @property
    def sort(self):
        return self._sort

    def _cursor(self):
        return self

    def _filter(self):
        return True

    @property
    def data(self):
        return [ (t._fullname, 2145945600) for t in self ]
                  # Jan 1 2038 ^^^^^^^^^^
                  # so that trials show up before spam and reports

    def fetchone(self):
        if self:
            return self.pop(0)
        else:
            raise StopIteration

def get_trials_links(sr):
    l = Trial.defendants_by_sr(sr)
    s = QueryishList(l)
    s._sort = [db_sort('new')]
    return s

def get_trials(sr):
    if isinstance(sr, ModContribSR):
        srs = Subreddit._byID(sr.sr_ids(), return_dict=False)
        return get_trials_links(srs)
    else:
        return get_trials_links(sr)

def get_modqueue(sr):
    results = []
    if isinstance(sr, ModContribSR):
        srs = Subreddit._byID(sr.sr_ids(), return_dict=False)
        results.append(get_trials_links(srs))

        for sr in srs:
            results.append(get_reported_links(sr))
            results.append(get_reported_comments(sr))
            results.append(get_spam_links(sr))
            results.append(get_spam_comments(sr))
    else:
        results.append(get_trials_links(sr))
        results.append(get_reported_links(sr))
        results.append(get_reported_comments(sr))
        results.append(get_spam_links(sr))
        results.append(get_spam_comments(sr))

    return merge_results(*results)

def get_domain_links_old(domain, sort, time):
    return DomainSearchQuery(domain, sort=search_sort[sort], timerange=time)

def get_domain_links(domain, sort, time):
    from r2.lib.db import operators
    q = Link._query(operators.domain(Link.c.url) == filters._force_utf8(domain),
                    sort = db_sort(sort),
                    data = True)
    if time != "all":
        q._filter(db_times[time])

    return make_results(q)

def user_query(kind, user_id, sort, time):
    """General profile-page query."""
    q = kind._query(kind.c.author_id == user_id,
                    kind.c._spam == (True, False),
                    sort = db_sort(sort))
    if time != 'all':
        q._filter(db_times[time])
    return make_results(q)

def get_all_comments():
    """the master /comments page"""
    q = Comment._query(sort = desc('_date'))
    return make_results(q)

def get_sr_comments(sr):
    return _get_sr_comments(sr._id)

def _get_sr_comments(sr_id):
    """the subreddit /r/foo/comments page"""
    q = Comment._query(Comment.c.sr_id == sr_id,
                       sort = desc('_date'))
    return make_results(q)

def _get_comments(user_id, sort, time):
    return user_query(Comment, user_id, sort, time)

def get_comments(user, sort, time):
    return _get_comments(user._id, sort, time)

def _get_submitted(user_id, sort, time):
    return user_query(Link, user_id, sort, time)

def get_submitted(user, sort, time):
    return _get_submitted(user._id, sort, time)

def get_overview(user, sort, time):
    return merge_results(get_comments(user, sort, time),
                         get_submitted(user, sort, time))

def user_rel_query(rel, user, name, filters = []):
    """General user relationship query."""

    q = rel._query(rel.c._thing1_id == user._id,
                   rel.c._t2_deleted == False,
                   rel.c._name == name,
                   sort = desc('_date'),
                   eager_load = True,
                   thing_data = not g.use_query_cache
                   )
    if filters:
        q._filter(*filters)

    return make_results(q, filter_thing2)

vote_rel = Vote.rel(Account, Link)

def get_liked(user):
    return user_rel_query(vote_rel, user, '1')

def get_disliked(user):
    return user_rel_query(vote_rel, user, '-1')

def get_hidden(user):
    return user_rel_query(SaveHide, user, 'hide')

def get_saved(user):
    return user_rel_query(SaveHide, user, 'save')

def get_subreddit_messages(sr):
    return user_rel_query(ModeratorInbox, sr, 'inbox')

def get_unread_subreddit_messages(sr):
    return user_rel_query(ModeratorInbox, sr, 'inbox',
                          filters = [ModeratorInbox.c.new == True])

inbox_message_rel = Inbox.rel(Account, Message)
def get_inbox_messages(user):
    return user_rel_query(inbox_message_rel, user, 'inbox')

def get_unread_messages(user):
    return user_rel_query(inbox_message_rel, user, 'inbox',
                          filters = [inbox_message_rel.c.new == True])

inbox_comment_rel = Inbox.rel(Account, Comment)
def get_inbox_comments(user):
    return user_rel_query(inbox_comment_rel, user, 'inbox')

def get_unread_comments(user):
    return user_rel_query(inbox_comment_rel, user, 'inbox',
                          filters = [inbox_comment_rel.c.new == True])

def get_inbox_selfreply(user):
    return user_rel_query(inbox_comment_rel, user, 'selfreply')

def get_unread_selfreply(user):
    return user_rel_query(inbox_comment_rel, user, 'selfreply',
                          filters = [inbox_comment_rel.c.new == True])

def get_inbox(user):
    return merge_results(get_inbox_comments(user),
                         get_inbox_messages(user),
                         get_inbox_selfreply(user))

def get_sent(user):
    q = Message._query(Message.c.author_id == user._id,
                       Message.c._spam == (True, False),
                       sort = desc('_date'))
    return make_results(q)

def get_unread_inbox(user):
    return merge_results(get_unread_comments(user),
                         get_unread_messages(user),
                         get_unread_selfreply(user))

def add_queries(queries, insert_items=None, delete_items=None, foreground=False):
    """Adds multiple queries to the query queue. If insert_items or
       delete_items is specified, the query may not need to be
       recomputed against the database."""
    if not g.write_query_queue:
        return

    for q in queries:
        if insert_items and q.can_insert():
            log.debug("Inserting %s into query %s" % (insert_items, q))
            if foreground:
                q.insert(insert_items)
            else:
                worker.do(q.insert, insert_items)
        elif delete_items and q.can_delete():
            log.debug("Deleting %s from query %s" % (delete_items, q))
            if foreground:
                q.delete(delete_items)
            else:
                worker.do(q.delete, delete_items)
        else:
            raise Exception("Cannot update query %r!" % (q,))

#can be rewritten to be more efficient
def all_queries(fn, obj, *param_lists):
    """Given a fn and a first argument 'obj', calls the fn(obj, *params)
    for every permutation of the parameters in param_lists"""
    results = []
    params = [[obj]]
    for pl in param_lists:
        new_params = []
        for p in pl:
            for c in params:
                new_param = list(c)
                new_param.append(p)
                new_params.append(new_param)
        params = new_params

    results = [fn(*p) for p in params]
    return results

## The following functions should be called after their respective
## actions to update the correct listings.
def new_link(link):
    "Called on the submission and deletion of links"
    sr = Subreddit._byID(link.sr_id)
    author = Account._byID(link.author_id)

    results = [get_links(sr, 'new', 'all')]
    # we don't have to do hot/top/controversy because new_vote will do
    # that

    results.append(get_submitted(author, 'new', 'all'))

    for domain in utils.UrlParser(link.url).domain_permutations():
        results.append(get_domain_links(domain, 'new', "all"))

    if link._spam:
        results.append(get_spam_links(sr))

    add_queries(results, insert_items = link)
    amqp.add_item('new_link', link._fullname)


def new_comment(comment, inbox_rels):
    author = Account._byID(comment.author_id)
    job = [get_comments(author, 'new', 'all'),
           get_comments(author, 'top', 'all'),
           get_comments(author, 'controversial', 'all')]

    sr = Subreddit._byID(comment.sr_id)

    if comment._deleted:
        job_key = "delete_items"
        job.append(get_sr_comments(sr))
        job.append(get_all_comments())
    else:
        job_key = "insert_items"
        if comment._spam:
            job.append(get_spam_comments(sr))
        amqp.add_item('new_comment', comment._fullname)
        if not g.amqp_host:
            add_comment_tree([comment])

    job_dict = { job_key: comment }
    add_queries(job, **job_dict)

    # note that get_all_comments() is updated by the amqp process
    # r2.lib.db.queries.run_new_comments (to minimise lock contention)

    if inbox_rels:
        for inbox_rel in tup(inbox_rels):
            inbox_owner = inbox_rel._thing1
            job_dict = { job_key: inbox_rel }
            if inbox_rel._name == "inbox":
                inbox_func  = get_inbox_comments
                unread_func = get_unread_comments
            elif inbox_rel._name == "selfreply":
                inbox_func = get_inbox_selfreply
                unread_func = get_unread_selfreply
            else:
                raise ValueError("wtf is " + inbox_rel._name)

            add_queries([inbox_func(inbox_owner)], **job_dict)

            if comment._deleted:
                add_queries([unread_func(inbox_owner)], **job_dict)
            else:
                set_unread(comment, inbox_owner, True)


def new_subreddit(sr):
    "no precomputed queries here yet"
    amqp.add_item('new_subreddit', sr._fullname)


def new_vote(vote, foreground=False):
    user = vote._thing1
    item = vote._thing2

    if not isinstance(item, (Link, Comment)):
        return

    if vote.valid_thing and not item._spam and not item._deleted:
        sr = item.subreddit_slow
        results = []

        author = Account._byID(item.author_id)
        for sort in ('hot', 'top', 'controversial', 'new'):
            if isinstance(item, Link):
                results.append(get_submitted(author, sort, 'all'))
            if isinstance(item, Comment):
                results.append(get_comments(author, sort, 'all'))

        if isinstance(item, Link):
            # don't do 'new', because that was done by new_link, and
            # the time-filtered versions of top/controversial will be
            # done by mr_top
            results.extend([get_links(sr, 'hot', 'all'),
                            get_links(sr, 'top', 'all'),
                            get_links(sr, 'controversial', 'all'),
                            ])

            for domain in utils.UrlParser(item.url).domain_permutations():
                for sort in ("hot", "top", "controversial"):
                    results.append(get_domain_links(domain, sort, "all"))

        add_queries(results, insert_items = item, foreground=foreground)

    vote._fast_query_timestamp_touch(user)
    
    if isinstance(item, Link):
        # must update both because we don't know if it's a changed
        # vote
        if vote._name == '1':
            add_queries([get_liked(user)], insert_items = vote, foreground = foreground)
            add_queries([get_disliked(user)], delete_items = vote, foreground = foreground)
        elif vote._name == '-1':
            add_queries([get_liked(user)], delete_items = vote, foreground = foreground)
            add_queries([get_disliked(user)], insert_items = vote, foreground = foreground)
        else:
            add_queries([get_liked(user)], delete_items = vote, foreground = foreground)
            add_queries([get_disliked(user)], delete_items = vote, foreground = foreground)

def new_message(message, inbox_rels):
    from r2.lib.comment_tree import add_message

    from_user = Account._byID(message.author_id)
    for inbox_rel in tup(inbox_rels):
        to = inbox_rel._thing1
        add_queries([get_sent(from_user)], insert_items=message)
        # moderator message
        if isinstance(inbox_rel, ModeratorInbox):
            add_queries([get_subreddit_messages(to)],
                        insert_items = inbox_rel)
        # personal message
        else:
            add_queries([get_inbox_messages(to)],
                        insert_items = inbox_rel)
        set_unread(message, to, True)

    add_message(message)

def set_unread(messages, to, unread):
    # Maintain backwards compatability
    messages = tup(messages)

    if isinstance(to, Subreddit):
        for i in ModeratorInbox.set_unread(messages, unread):
            kw = dict(insert_items = i) if unread else dict(delete_items = i)
            add_queries([get_unread_subreddit_messages(i._thing1)], **kw)
    else:
        # All messages should be of the same type
        for i in Inbox.set_unread(messages, unread, to=to):
            kw = dict(insert_items = i) if unread else dict(delete_items = i)
            if isinstance(messages[0], Comment) and not unread:
                add_queries([get_unread_comments(i._thing1)], **kw)
                add_queries([get_unread_selfreply(i._thing1)], **kw)
            elif i._name == 'selfreply':
                add_queries([get_unread_selfreply(i._thing1)], **kw)
            elif isinstance(messages[0], Comment):
                add_queries([get_unread_comments(i._thing1)], **kw)
            else:
                add_queries([get_unread_messages(i._thing1)], **kw)

def new_savehide(rel):
    user = rel._thing1
    name = rel._name
    if name == 'save':
        add_queries([get_saved(user)], insert_items = rel)
    elif name == 'unsave':
        add_queries([get_saved(user)], delete_items = rel)
    elif name == 'hide':
        add_queries([get_hidden(user)], insert_items = rel)
    elif name == 'unhide':
        add_queries([get_hidden(user)], delete_items = rel)

def changed(things, boost_only=False):
    """Indicate to search that a given item should be updated in the index"""
    for thing in tup(things):
        msg = {'fullname': thing._fullname}
        if boost_only:
            msg['boost_only'] = True

        amqp.add_item('search_changes', pickle.dumps(msg),
                      message_id = thing._fullname,
                      delivery_mode = amqp.DELIVERY_TRANSIENT)

def _by_srid(things,srs=True):
    """Takes a list of things and returns them in a dict separated by
       sr_id, in addition to the looked-up subreddits"""
    ret = {}

    for thing in tup(things):
        if getattr(thing, 'sr_id', None) is not None:
            ret.setdefault(thing.sr_id, []).append(thing)

    if srs:
        _srs = Subreddit._byID(ret.keys(), return_dict=True) if ret else {}
        return ret, _srs
    else:
        return ret


def _by_author(things):
    by_account = collections.defaultdict(list)

    for thing in tup(things):
        author_id = getattr(thing, 'author_id')
        if author_id:
            by_account[author_id].append(thing)

    return by_account


def ban(things):
    del_or_ban(things, "ban")

def delete_links(links):
    del_or_ban(links, "del")

def delete_comments(comments):
    del_or_ban(comments, "del")

def del_or_ban(things, why):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in things if isinstance(x, Link)]
        comments = [x for x in things if isinstance(x, Comment)]

        if links:
            if why == "ban":
                add_queries([get_spam_links(sr)], insert_items = links)
            # rip it out of the listings. bam!
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all'),
                       ]

            for sort in time_filtered_sorts:
                for time in db_times.keys():
                    results.append(get_links(sr, sort, time))

            add_queries(results, delete_items = links)

        if comments:
            add_queries([get_spam_comments(sr)], insert_items = comments)
            add_queries([get_all_comments(),
                         get_sr_comments(sr)], delete_items = comments)

    if why == "del":
        with CachedQueryMutator() as m:
            for author_id, things in _by_author(things).iteritems():
                links = [x for x in things if isinstance(x, Link)]
                if links:
                    m.insert(get_deleted_links(author_id), links)

                comments = [x for x in things if isinstance(x, Comment)]
                if comments:
                    m.insert(get_deleted_comments(author_id), comments)

    changed(things)

def unban(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in things if isinstance(x, Link)]
        comments = [x for x in things if isinstance(x, Comment)]

        if links:
            add_queries([get_spam_links(sr)], delete_items = links)
            # put it back in the listings
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all'),
                       get_links(sr, 'top', 'all'),
                       get_links(sr, 'controversial', 'all'),
                       ]

            # the time-filtered listings will have to wait for the
            # next mr_top run

            add_queries(results, insert_items = links)

        if comments:
            add_queries([get_spam_comments(sr)], delete_items = comments)
            add_queries([get_all_comments(),
                         get_sr_comments(sr)], insert_items = comments)

    changed(things)

def new_report(thing):
    if isinstance(thing, Link):
        sr = Subreddit._byID(thing.sr_id)
        add_queries([get_reported_links(sr)], insert_items = thing)
    elif isinstance(thing, Comment):
        sr = Subreddit._byID(thing.sr_id)
        add_queries([get_reported_comments(sr)], insert_items = thing)

def clear_reports(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, sr_things in by_srid.iteritems():
        sr = srs[sr_id]

        links = [ x for x in sr_things if isinstance(x, Link) ]
        comments = [ x for x in sr_things if isinstance(x, Comment) ]

        if links:
            add_queries([get_reported_links(sr)], delete_items = links)
        if comments:
            add_queries([get_reported_comments(sr)], delete_items = comments)

def add_all_ban_report_srs():
    """Adds the initial spam/reported pages to the report queue"""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        add_queries([get_spam_links(sr),
                     get_spam_comments(sr),
                     get_reported_links(sr),
                     get_reported_comments(sr),
                     ])
        
def add_all_srs():
    """Recalculates every listing query for every subreddit. Very,
       very slow."""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        for q in all_queries(get_links, sr, ('hot', 'new'), ['all']):
            q.update()
        for q in all_queries(get_links, sr, time_filtered_sorts, db_times.keys()):
            q.update()
        get_spam_links(sr).update()
        get_spam_comments(sr).update()
        get_reported_links(sr).update()
        get_reported_comments(sr).update()

def update_user(user):
    if isinstance(user, str):
        user = Account._by_name(user)
    elif isinstance(user, int):
        user = Account._byID(user)

    results = [get_inbox_messages(user),
               get_inbox_comments(user),
               get_inbox_selfreply(user),
               get_sent(user),
               get_liked(user),
               get_disliked(user),
               get_saved(user),
               get_hidden(user),
               get_submitted(user, 'new', 'all'),
               get_comments(user, 'new', 'all')]
    for q in results:
        q.update()

def add_all_users():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        update_user(user)

def add_comment_tree(comments):
    #update the comment cache
    add_comments(comments)
    #update last modified
    links = Link._byID(list(set(com.link_id for com in tup(comments))),
                       data = True, return_dict = False)
    for link in links:
        set_last_modified(link, 'comments')

# amqp queue processing functions

def run_new_comments(limit=1000):
    """Add new incoming comments to the /comments page"""
    # this is done as a queue because otherwise the contention for the
    # lock on the query would be very high

    @g.stats.amqp_processor('newcomments_q')
    def _run_new_comments(msgs, chan):
        fnames = [msg.body for msg in msgs]

        comments = Comment._by_fullname(fnames, data=True, return_dict=False)
        add_queries([get_all_comments()],
                    insert_items=comments)

        bysrid = _by_srid(comments, False)
        for srid, sr_comments in bysrid.iteritems():
            add_queries([_get_sr_comments(srid)],
                        insert_items=sr_comments)

    amqp.handle_items('newcomments_q', _run_new_comments, limit=limit)

def run_commentstree(limit=100):
    """Add new incoming comments to their respective comments trees"""

    @g.stats.amqp_processor('commentstree_q')
    def _run_commentstree(msgs, chan):
        comments = Comment._by_fullname([msg.body for msg in msgs],
                                        data = True, return_dict = False)
        print 'Processing %r' % (comments,)

        add_comment_tree(comments)

    amqp.handle_items('commentstree_q', _run_commentstree, limit = limit)

vote_link_q = 'vote_link_q'
vote_comment_q = 'vote_comment_q'

def queue_vote(user, thing, dir, ip, organic = False,
               cheater = False, store = True):
    # set the vote in memcached so the UI gets updated immediately
    key = prequeued_vote_key(user, thing)
    g.cache.set(key, '1' if dir is True else '0' if dir is None else '-1')
    # queue the vote to be stored unless told not to
    if store:
        if g.amqp_host:
            if isinstance(thing, Link):
                qname = vote_link_q
            elif isinstance(thing, Comment):
                qname = vote_comment_q

            amqp.add_item(qname,
                          pickle.dumps((user._id, thing._fullname,
                                        dir, ip, organic, cheater)))
        else:
            handle_vote(user, thing, dir, ip, organic)

def prequeued_vote_key(user, item):
    return 'registered_vote_%s_%s' % (user._id, item._fullname)

def get_likes(user, items):
    if not user or not items:
        return {}

    res = {}

    # check the prequeued_vote_keys
    keys = {}
    for item in items:
        if (user, item) in res:
            continue

        key = prequeued_vote_key(user, item)
        keys[key] = (user, item)
    if keys:
        r = g.cache.get_multi(keys.keys())
        for key, v in r.iteritems():
            res[keys[key]] = (True if v == '1'
                              else False if v == '-1'
                              else None)

    # avoid requesting items that they can't have voted on (we're
    # still using the tdb_sql Thing API for this). TODO: we should do
    # this before the prequeued_vote_keys lookup, so that in extreme
    # cases we can avoid hitting the cache for them at all, but in the
    # current state that precludes brand new comments from appearing
    # to have been voted on
    for item in items:
        if (user, item) in res:
            continue

        # we can only vote on links and comments
        if isinstance(item, (Link, Comment)):
            rel = Vote.rel(user.__class__, item.__class__)
            if rel._can_skip_lookup(user, item):
                res[(user, item)] = None
        else:
            res[(user, item)] = None

    # now hit Cassandra with the remainder
    likes = Vote.likes(user, [i for i in items if (user, i) not in res])

    res.update(likes)

    return res

def handle_vote(user, thing, dir, ip, organic, cheater=False, foreground=False):
    from r2.lib.db import tdb_sql
    from sqlalchemy.exc import IntegrityError
    try:
        v = Vote.vote(user, thing, dir, ip, organic, cheater = cheater)
    except (tdb_sql.CreationError, IntegrityError):
        g.log.error("duplicate vote for: %s" % str((user, thing, dir)))
        return

    if isinstance(thing, Link):
        new_vote(v, foreground=foreground)

        #update the modified flags
        if user._id == thing.author_id:
            set_last_modified(user, 'overview')
            set_last_modified(user, 'submitted')
            #update sup listings
            sup.add_update(user, 'submitted')

            #update sup listings
            if dir:
                set_last_modified(user, 'liked')
                sup.add_update(user, 'liked')
            elif dir is False:
                set_last_modified(user, 'disliked')
                sup.add_update(user, 'disliked')

    elif isinstance(thing, Comment):
        #update last modified
        if user._id == thing.author_id:
            set_last_modified(user, 'overview')
            set_last_modified(user, 'commented')
            #update sup listings
            sup.add_update(user, 'commented')


def process_votes_single(qname, limit=0):
    # limit is taken but ignored for backwards compatibility

    @g.stats.amqp_processor(qname)
    def _handle_vote(msg):
        #assert(len(msgs) == 1)
        r = pickle.loads(msg.body)

        uid, tid, dir, ip, organic, cheater = r
        voter = Account._byID(uid, data=True)
        votee = Thing._by_fullname(tid, data = True)
        if isinstance(votee, Comment):
            update_comment_votes([votee])

        # I don't know how, but somebody is sneaking in votes
        # for subreddits
        if isinstance(votee, (Link, Comment)):
            print (voter, votee, dir, ip, organic, cheater)
            handle_vote(voter, votee, dir, ip, organic,
                        cheater = cheater, foreground=True)

    amqp.consume_items(qname, _handle_vote, verbose = False)

def process_votes_multi(qname, limit=100):
    # limit is taken but ignored for backwards compatibility
    @g.stats.amqp_processor(qname)
    def _handle_vote(msgs, chan):
        comments = []

        for msg in msgs:
            tag = msg.delivery_tag
            r = pickle.loads(msg.body)

            uid, tid, dir, ip, organic, cheater = r
            voter = Account._byID(uid, data=True)
            votee = Thing._by_fullname(tid, data = True)
            if isinstance(votee, Comment):
                comments.append(votee)

            if not isinstance(votee, (Link, Comment)):
                # I don't know how, but somebody is sneaking in votes
                # for subreddits
                continue

            print (voter, votee, dir, ip, organic, cheater)
            try:
                handle_vote(voter, votee, dir, ip, organic,
                            cheater=cheater, foreground=False)
            except Exception, e:
                print 'Rejecting %r:%r because of %r' % (msg.delivery_tag, r,e)
                chan.basic_reject(msg.delivery_tag, requeue=True)

        update_comment_votes(comments)

    amqp.handle_items(qname, _handle_vote, limit = limit)

process_votes = process_votes_single

try:
    from r2admin.lib.admin_queries import *
except ImportError:
    pass
