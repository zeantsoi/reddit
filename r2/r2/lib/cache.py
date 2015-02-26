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

import sys
from threading import local
from hashlib import md5
import cPickle as pickle
from copy import copy
from curses.ascii import isgraph
import logging
from time import sleep

from pylons import g

import pylibmc
from _pylibmc import MemcachedError

import random

from pycassa import ColumnFamily
from pycassa.cassandra.ttypes import ConsistencyLevel

from r2.lib.utils import in_chunks, prefix_keys, trace, tup
from r2.lib.hardcachebackend import HardCacheBackend

from r2.lib.sgm import sgm # get this into our namespace so that it's
                           # importable from us

import random
                           
# This is for use in the health controller
_CACHE_SERVERS = set()

class NoneResult(object): pass

class CacheUtils(object):
    # Caches that never expire entries should set this to true, so that
    # CacheChain can properly count hits and misses.
    permanent = False

    def incr_multi(self, keys, delta=1, prefix=''):
        for k in keys:
            try:
                self.incr(prefix + k, delta)
            except ValueError:
                pass

    def add_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            self.add(prefix+str(k), v, time = time)

    def get_multi(self, keys, prefix='', **kw):
        return prefix_keys(keys, prefix, lambda k: self.simple_get_multi(k, **kw))


class MemcachedMaximumRetryException(Exception): pass

class MemcachedValueSizeException(Exception):
    def __init__(self, cache_name, caller, prefix, key, size):
        self.key = key
        self.size = size
        self.cache_name = cache_name
        self.caller = caller
        self.prefix = prefix

    def __str__(self):
        return ("Memcached %s %s: The object for key '%s%s' is too big for memcached at %s bytes" %
            (self.cache_name, self.caller, self.prefix, self.key, self.size))


# validation functions to be used by memcached pools
MEMCACHED_MAX_VALUE_SIZE = 2048 * 1024 # 2MB

def validate_size_warn(**kwargs):
    if 'value' in kwargs:
        size = sys.getsizeof(kwargs["value"])
        if size >= MEMCACHED_MAX_VALUE_SIZE:
            key = ".".join((
                "memcached_large_object",
                kwargs.get("cache_name", "undefined")
            ))
            g.stats.simple_event(key)
            g.log.debug(
                "Memcached %s: Attempted to cache an object > 1MB at key: '%s%s' of size %s bytes",
                kwargs.get("caller", "unknown"),
                kwargs.get("prefix", ""),
                kwargs.get("key", "undefined"),
                size
            )
            return False

    return True

def validate_size_error(**kwargs):
    if 'value' in kwargs:
        size = sys.getsizeof(kwargs["value"])
        if size >= MEMCACHED_MAX_VALUE_SIZE:
            raise MemcachedValueSizeException(
                kwargs.get("cache_name", "unknown"),
                kwargs.get("caller", "unknown"),
                kwargs.get("prefix", ""),
                kwargs.get("key", "undefined"),
                size
            )

    return True

class CMemcache(CacheUtils):
    def __init__(self,
                 name,
                 servers,
                 debug=False,
                 noreply=False,
                 no_block=False,
                 min_compress_len=512 * 1024,
                 num_clients=10,
                 timeout_retry=5,
                 binary=False,
                 validators=None):
        self.name = name
        self.servers = servers
        self.clients = pylibmc.ClientPool(n_slots = num_clients)
        self.timeout_retry = timeout_retry
        self.validators = validators or []

        for x in xrange(num_clients):
            client = pylibmc.Client(servers, binary=binary)
            behaviors = {
                'no_block': no_block, # use async I/O
                'tcp_nodelay': True, # no nagle
                '_noreply': int(noreply),
                'ketama': True, # consistent hashing
            }
            if not binary:
                behaviors['verify_keys'] = True

            client.behaviors.update(behaviors)
            self.clients.put(client)

        self.min_compress_len = min_compress_len

        _CACHE_SERVERS.update(servers)


    def retry(self, times, fn):
        ex = None
        for i in xrange(times):
            try:
                val = fn()
                if i != 0:
                    event_name = "cache.retry.%s" % fn.__name__
                    name = "success_on_retry_%s" % i
                    g.stats.event_count(event_name, name)
                return val
            except (pylibmc.NotFound,
                    pylibmc.BadKeyProvided,
                    pylibmc.UnknownStatKey,
                    pylibmc.InvalidHostProtocolError,
                    pylibmc.NotSupportedError):
                raise
            except MemcachedError as e:
                ex = e
            sleep(random.uniform(0, 0.1))

        event_name = "cache.retry.%s" % fn.__name__
        g.stats.event_count(event_name, "fail")
        raise MemcachedMaximumRetryException(ex)

    def validate(self, **kwargs):
        kwargs['caller'] = sys._getframe().f_back.f_code.co_name
        kwargs['cache_name'] = self.name
        if not all(validator(**kwargs) for validator in self.validators):
            return False

        return True

    def get(self, key, default = None):
        if not self.validate(key=key):
            return default

        def do_get():
            with self.clients.reserve() as mc:
                ret = mc.get(key)
                if ret is None:
                    return default
                return ret

        return self.retry(self.timeout_retry, do_get)

    def get_multi(self, keys, prefix = ''):
        validated_keys = [k for k in (str(k) for k in keys)
                          if self.validate(prefix=prefix, key=k)]

        def do_get_multi():
            with self.clients.reserve() as mc:
                return mc.get_multi(validated_keys, key_prefix = prefix)

        return self.retry(self.timeout_retry, do_get_multi)

    # simple_get_multi exists so that a cache chain can
    # single-instance the handling of prefixes for performance, but
    # pylibmc does this in C which is faster anyway, so CMemcache
    # implements get_multi itself. But the CacheChain still wants
    # simple_get_multi to be available for when it's already prefixed
    # them, so here it is
    simple_get_multi = get_multi

    def set(self, key, val, time = 0):
        if not self.validate(key=key, value=val):
            return None

        def do_set():
            with self.clients.reserve() as mc:
                return mc.set(key, val, time = time,
                                min_compress_len = self.min_compress_len)

        return self.retry(self.timeout_retry, do_set)

    def set_multi(self, keys, prefix='', time=0):
        str_keys = ((str(k), v) for k, v in keys.iteritems())
        validated_keys = {k: v for k, v in str_keys
                          if self.validate(prefix=prefix, key=k, value=v)}

        def do_set_multi():
            with self.clients.reserve() as mc:
                return mc.set_multi(validated_keys, key_prefix = prefix,
                                    time = time,
                                    min_compress_len = self.min_compress_len)

        return self.retry(self.timeout_retry, do_set_multi)

    def add_multi(self, keys, prefix='', time=0):
        str_keys = ((str(k), v) for k, v in keys.iteritems())
        validated_keys = {k: v for k, v in str_keys
                          if self.validate(prefix=prefix, key=k, value=v)}

        with self.clients.reserve() as mc:
            return mc.add_multi(validated_keys, key_prefix = prefix,
                                time = time)

    def incr_multi(self, keys, prefix='', delta=1):
        validated_keys = [k for k in (str(k) for k in keys)
                          if self.validate(prefix=prefix, key=k)]

        with self.clients.reserve() as mc:
            return mc.incr_multi(validated_keys,
                                 key_prefix = prefix,
                                 delta=delta)

    def append(self, key, val, time=0):
        if not self.validate(key=key, value=val):
            return None

        with self.clients.reserve() as mc:
            return mc.append(key, val, time=time)

    def incr(self, key, delta=1, time=0):
        if not self.validate(key=key):
            return None

        # ignore the time on these
        with self.clients.reserve() as mc:
            return mc.incr(key, delta)

    def add(self, key, val, time=0):
        if not self.validate(key=key, value=val):
            return None

        try:
            with self.clients.reserve() as mc:
                return mc.add(key, val, time=time)
        except pylibmc.DataExists:
            return None

    def delete(self, key, time=0):
        if not self.validate(key=key):
            return None

        def do_delete():
            with self.clients.reserve() as mc:
                return mc.delete(key)

        return self.retry(self.timeout_retry, do_delete)

    def delete_multi(self, keys, prefix=''):
        validated_keys = [k for k in (str(k) for k in keys)
                          if self.validate(prefix=prefix, key=k)]

        def do_delete_multi():
            with self.clients.reserve() as mc:
                return mc.delete_multi(validated_keys, key_prefix=prefix)

        return self.retry(self.timeout_retry, do_delete_multi)

    def __repr__(self):
        return '<%s(%r)>' % (self.__class__.__name__,
                             self.servers)

class HardCache(CacheUtils):
    backend = None
    permanent = True

    def __init__(self, gc):
        self.backend = HardCacheBackend(gc)

    def _split_key(self, key):
        tokens = key.split("-", 1)
        if len(tokens) != 2:
            raise ValueError("key %s has no dash" % key)

        category, ids = tokens
        return category, ids

    def set(self, key, val, time=0):
        if val == NoneResult:
            # NoneResult caching is for other parts of the chain
            return

        category, ids = self._split_key(key)
        self.backend.set(category, ids, val, time)

    def simple_get_multi(self, keys):
        results = {}
        category_bundles = {}
        for key in keys:
            category, ids = self._split_key(key)
            category_bundles.setdefault(category, []).append(ids)

        for category in category_bundles:
            idses = category_bundles[category]
            chunks = in_chunks(idses, size=50)
            for chunk in chunks:
                new_results = self.backend.get_multi(category, chunk)
                results.update(new_results)

        return results

    def set_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            if v != NoneResult:
                self.set(prefix+str(k), v, time=time)

    def get(self, key, default=None):
        category, ids = self._split_key(key)
        r = self.backend.get(category, ids)
        if r is None: return default
        return r

    def delete(self, key, time=0):
        # Potential optimization: When on a negative-result caching chain,
        # shove NoneResult throughout the chain when a key is deleted.
        category, ids = self._split_key(key)
        self.backend.delete(category, ids)

    def add(self, key, value, time=0):
        category, ids = self._split_key(key)
        return self.backend.add(category, ids, value, time=time)

    def incr(self, key, delta=1, time=0):
        category, ids = self._split_key(key)
        return self.backend.incr(category, ids, delta=delta, time=time)


class LocalCache(dict, CacheUtils):
    def __init__(self, *a, **kw):
        return dict.__init__(self, *a, **kw)

    def _check_key(self, key):
        if isinstance(key, unicode):
            key = str(key) # try to convert it first
        if not isinstance(key, str):
            raise TypeError('Key is not a string: %r' % (key,))

    def get(self, key, default=None):
        r = dict.get(self, key)
        if r is None: return default
        return r

    def simple_get_multi(self, keys):
        out = {}
        for k in keys:
            if self.has_key(k):
                out[k] = self[k]
        return out

    def set(self, key, val, time = 0):
        # time is ignored on localcache
        self._check_key(key)
        self[key] = val

    def set_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            self.set(prefix+str(k), v, time=time)

    def add(self, key, val, time = 0):
        self._check_key(key)
        was = key in self
        self.setdefault(key, val)
        return not was

    def delete(self, key):
        if self.has_key(key):
            del self[key]

    def delete_multi(self, keys):
        for key in keys:
            if self.has_key(key):
                del self[key]

    def incr(self, key, delta=1, time=0):
        if self.has_key(key):
            self[key] = int(self[key]) + delta

    def decr(self, key, amt=1):
        if self.has_key(key):
            self[key] = int(self[key]) - amt

    def append(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = str(self[key]) + val

    def prepend(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = val + str(self[key])

    def replace(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = val

    def flush_all(self):
        self.clear()

    def __repr__(self):
        return "<LocalCache(%d)>" % (len(self),)


class TransitionalCache(CacheUtils):
    """A cache "chain" for moving keys to a new cluster live.

    `original_cache` is the cache chain previously in use (this'll frequently
    be `g.cache` since it's the catch-all for most things) and
    `replacement_cache` is the new place for the keys using this chain to
    live.  `key_transform` is an optional function to translate the key names
    into different names on the `replacement_cache`.

    To use this cache chain, do three separate deployments as follows:

        * start dual-writing to the new pool by putting this chain in place
          with `read_original=True`.
        * cut reads over to the new pool after it is sufficiently heated up by
          deploying `read_original=False`.
        * remove this cache chain entirely and replace it with
          `replacement_cache`.

    This ensures that at any point, all apps regardless of their position in
    the push order will have a consistent view of the data in the cache pool as
    much as is possible.

    """

    def __init__(
            self, original_cache, replacement_cache, read_original,
            key_transform=None):
        self.original = original_cache
        self.replacement = replacement_cache
        self.read_original = read_original
        self.key_transform = key_transform

    @property
    def stats(self):
        if self.read_original:
            return self.original.stats
        else:
            return self.replacement.stats

    @stats.setter
    def stats(self, value):
        """No-op.

        TransitionCache is designed to wrap two cache chains. We can ignore
        the set (which happens at the end of reset_caches in app_globals.py)
        because each chain will separately get dealt with on its own.
        """
        pass

    @property
    def caches(self):
        if self.read_original:
            return self.original.caches
        else:
            return self.replacement.caches

    def transform_memcache_key(self, args):
        if self.key_transform:
            old_key = args[0]
            if isinstance(old_key, dict):  # multiget passes a dict
                new_key = {self.key_transform(k): v for k,v in
                           old_key.iteritems()}
            elif isinstance(old_key, list):
                new_key = [self.key_transform(k) for k in old_key]
            else:
                new_key = self.key_transform(old_key)

            return (new_key,) + args[1:]
        else:
            return args

    def make_get_fn(fn_name):
        def transitional_cache_get_fn(self, *args, **kwargs):
            if self.read_original:
                return getattr(self.original, fn_name)(*args, **kwargs)
            else:
                args = self.transform_memcache_key(args)
                return getattr(self.replacement, fn_name)(*args, **kwargs)
        return transitional_cache_get_fn

    get = make_get_fn("get")
    get_multi = make_get_fn("get_multi")
    simple_get_multi = make_get_fn("simple_get_multi")

    def make_set_fn(fn_name):
        def transitional_cache_set_fn(self, *args, **kwargs):
            ret_original = getattr(self.original, fn_name)(*args, **kwargs)
            args = self.transform_memcache_key(args)
            ret_replacement = getattr(self.replacement, fn_name)(*args, **kwargs)
            if self.read_original:
                return ret_original
            else:
                return ret_replacement
        return transitional_cache_set_fn

    add = make_set_fn("add")
    set = make_set_fn("set")
    append = make_set_fn("append")
    prepend = make_set_fn("prepend")
    replace = make_set_fn("replace")
    set_multi = make_set_fn("set_multi")
    add = make_set_fn("add")
    add_multi = make_set_fn("add_multi")
    incr = make_set_fn("incr")
    incr_multi = make_set_fn("incr_multi")
    decr = make_set_fn("decr")
    delete = make_set_fn("delete")
    delete_multi = make_set_fn("delete_multi")
    flush_all = make_set_fn("flush_all")
    reset = make_set_fn("reset")


def cache_timer_decorator(fn_name):
    """Use to decorate CacheChain operations so timings will be recorded."""
    def wrap(fn):
        def timed_fn(self, *a, **kw):
            use_timer = kw.pop("use_timer", True)

            try:
                getattr(g, "log")
            except TypeError:
                # don't have access to g, maybe in a thread?
                return fn(self, *a, **kw)

            if use_timer and self.stats:
                publish = random.random() < g.stats.CACHE_SAMPLE_RATE
                cache_name = self.stats.cache_name
                timer_name = "cache.%s.%s" % (cache_name, fn_name)
                timer = g.stats.get_timer(timer_name, publish)
                timer.start()
            else:
                timer = None

            result = fn(self, *a, **kw)
            if timer:
                timer.stop()

            return result
        return timed_fn
    return wrap


def log_invalid_keys(fn):
    """Use to decorate CacheChain operations to log invalid memcache keys."""
    def wrapped(self, *args, **kw):
        try:
            getattr(g, "log")
        except TypeError:
            # don't have access to g, maybe in a thread?
            return fn(self, *args, **kw)

        if self.check_keys and getattr(g, "log"):
            keys = args[0]
            prefix = kw.get("prefix", "")
            if self.stats:
                cache_name = self.stats.cache_name
            else:
                cache_name = "unknown"

            live_config = getattr(g, "live_config", {})
            log_chance = live_config.get("invalid_key_sample_rate", 1)
            will_log = random.random() < log_chance

            for key in tup(keys):
                # map_keys will coerce keys to str but we need to do
                # it for non multi operations so the `isgraph` checks
                # don't fail
                # any key that's not a valid str will end up
                # triggering a ValueError when it hits memcache
                key = str(key)

                if prefix:
                    key = prefix + key

                for c in key:
                    if will_log and not isgraph(c):
                        g.log.warning(
                            "%s: keyname is invalid: %r", cache_name, key)
                        break
        return fn(self, *args, **kw)
    return wrapped


class CacheChain(CacheUtils, local):
    def __init__(self, caches, cache_negative_results=False,
                 check_keys=True):
        self.caches = caches
        self.cache_negative_results = cache_negative_results
        self.stats = None
        self.check_keys = check_keys

    def make_set_fn(fn_name):
        @cache_timer_decorator(fn_name)
        @log_invalid_keys
        def fn(self, *a, **kw):
            ret = None
            for c in self.caches:
                ret = getattr(c, fn_name)(*a, **kw)
            return ret
        return fn

    # note that because of the naive nature of `add' when used on a
    # cache chain, its return value isn't reliable. if you need to
    # verify its return value you'll either need to make it smarter or
    # use the underlying cache directly
    add = make_set_fn('add')

    set = make_set_fn('set')
    append = make_set_fn('append')
    prepend = make_set_fn('prepend')
    replace = make_set_fn('replace')
    set_multi = make_set_fn('set_multi')
    add = make_set_fn('add')
    add_multi = make_set_fn('add_multi')
    incr = make_set_fn('incr')
    incr_multi = make_set_fn('incr_multi')
    decr = make_set_fn('decr')
    delete = make_set_fn('delete')
    delete_multi = make_set_fn('delete_multi')
    flush_all = make_set_fn('flush_all')
    cache_negative_results = False

    @cache_timer_decorator("get")
    @log_invalid_keys
    def get(self, key, default = None, allow_local = True, stale=None):
        stat_outcome = False  # assume a miss until a result is found
        try:
            for c in self.caches:
                if not allow_local and isinstance(c,LocalCache):
                    continue

                val = c.get(key)

                if val is not None:
                    if not c.permanent:
                        stat_outcome = True

                    #update other caches
                    for d in self.caches:
                        if c is d:
                            break # so we don't set caches later in the chain
                        d.set(key, val)

                    if val == NoneResult:
                        return default
                    else:
                        return val

            if self.cache_negative_results:
                for c in self.caches[:-1]:
                    c.set(key, NoneResult)

            return default
        finally:
            if self.stats:
                if stat_outcome:
                    self.stats.cache_hit()
                else:
                    self.stats.cache_miss()

    def get_multi(self, keys, prefix='', allow_local = True, **kw):
        l = lambda ks: self.simple_get_multi(ks, allow_local = allow_local, **kw)
        return prefix_keys(keys, prefix, l)

    @cache_timer_decorator("get_multi")
    @log_invalid_keys
    def simple_get_multi(self, keys, allow_local = True, stale=None):
        out = {}
        need = set(keys)
        hits = 0
        misses = 0
        for c in self.caches:
            if not allow_local and isinstance(c, LocalCache):
                continue

            if c.permanent and not misses:
                # Once we reach a "permanent" cache, we count any outstanding
                # items as misses.
                misses = len(need)

            if len(out) == len(keys):
                # we've found them all
                break
            r = c.simple_get_multi(need)
            #update other caches
            if r:
                if not c.permanent:
                    hits += len(r)
                for d in self.caches:
                    if c is d:
                        break # so we don't set caches later in the chain
                    d.set_multi(r)
                r.update(out)
                out = r
                need = need - set(r.keys())

        if need and self.cache_negative_results:
            d = dict((key, NoneResult) for key in need)
            for c in self.caches[:-1]:
                c.set_multi(d)

        out = dict((k, v)
                   for (k, v) in out.iteritems()
                   if v != NoneResult)

        if self.stats:
            if not misses:
                # If this chain contains no permanent caches, then we need to
                # count the misses here.
                misses = len(need)
            self.stats.cache_hit(hits)
            self.stats.cache_miss(misses)

        return out

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__,
                            self.caches)

    def debug(self, key):
        print "Looking up [%r]" % key
        for i, c in enumerate(self.caches):
            print "[%d] %10s has value [%r]" % (i, c.__class__.__name__,
                                                c.get(key))

    def reset(self):
        # the first item in a cache chain is a LocalCache
        self.caches = (self.caches[0].__class__(),) +  self.caches[1:]

class MemcacheChain(CacheChain):
    pass

class HardcacheChain(CacheChain):
    @log_invalid_keys
    def add(self, key, val, time=0):
        authority = self.caches[-1] # the authority is the hardcache
                                    # itself
        added_val = authority.add(key, val, time=time)
        for cache in self.caches[:-1]:
            # Calling set() rather than add() to ensure that all caches are
            # in sync and that de-syncs repair themselves
            cache.set(key, added_val, time=time)

        return added_val

    @log_invalid_keys
    def accrue(self, key, time=0, delta=1):
        auth_value = self.caches[-1].get(key)

        if auth_value is None:
            auth_value = 0

        try:
            auth_value = int(auth_value) + delta
        except ValueError:
            raise ValueError("Can't accrue %s; it's a %s (%r)" %
                             (key, auth_value.__class__.__name__, auth_value))

        for c in self.caches:
            c.set(key, auth_value, time=time)

        return auth_value

    @property
    def backend(self):
        # the hardcache is always the last item in a HardCacheChain
        return self.caches[-1].backend

class StaleCacheChain(CacheChain):
    """A cache chain of two cache chains. When allowed by `stale`,
       answers may be returned by a "closer" but potentially older
       cache. Probably doesn't play well with NoneResult cacheing"""
    staleness = 30

    def __init__(self, localcache, stalecache, realcache, check_keys=True):
        self.localcache = localcache
        self.stalecache = stalecache
        self.realcache = realcache
        self.caches = (localcache, realcache) # for the other
                                              # CacheChain machinery
        self.stats = None
        self.check_keys = check_keys

    @log_invalid_keys
    @cache_timer_decorator("get")
    def get(self, key, default=None, stale = False, **kw):
        if kw.get('allow_local', True) and key in self.localcache:
            if self.stats:
                self.stats.cache_hit()
            return self.localcache[key]

        if stale:
            stale_value = self._getstale([key]).get(key, None)
            if stale_value is not None:
                if self.stats:
                    self.stats.cache_hit()
                    self.stats.stale_hit()
                return stale_value # never return stale data into the
                                   # LocalCache, or people that didn't
                                   # say they'll take stale data may
                                   # get it
            else:
                self.stats.stale_miss()

        value = self.realcache.get(key)
        if value is None:
            if self.stats:
                self.stats.cache_miss()
            return default

        if stale:
            self.stalecache.set(key, value, time=self.staleness)

        self.localcache.set(key, value)

        if self.stats:
            self.stats.cache_hit()

        return value

    @cache_timer_decorator("get_multi")
    @log_invalid_keys
    def simple_get_multi(self, keys, stale = False, **kw):
        if not isinstance(keys, set):
            keys = set(keys)

        ret = {}

        if kw.get('allow_local'):
            for k in list(keys):
                if k in self.localcache:
                    ret[k] = self.localcache[k]
                    keys.remove(k)

        if keys and stale:
            stale_values = self._getstale(keys)
            # never put stale data into the localcache
            for k, v in stale_values.iteritems():
                ret[k] = v
                keys.remove(k)

            stale_hits = len(stale_values)
            stale_misses = len(keys)
            if self.stats:
                self.stats.stale_hit(stale_hits)
                self.stats.stale_miss(stale_misses)

        if keys:
            values = self.realcache.simple_get_multi(keys)
            if values and stale:
                self.stalecache.set_multi(values, time=self.staleness)
            self.localcache.update(values)
            ret.update(values)

        if self.stats:
            misses = len(keys - set(ret.keys()))
            hits = len(ret)
            self.stats.cache_hit(hits)
            self.stats.cache_miss(misses)

        return ret

    def _getstale(self, keys):
        # this is only in its own function to make tapping it for
        # debugging easier
        return self.stalecache.simple_get_multi(keys)

    def reset(self):
        newcache = self.localcache.__class__()
        self.localcache = newcache
        self.caches = (newcache,) +  self.caches[1:]
        if isinstance(self.realcache, CacheChain):
            assert isinstance(self.realcache.caches[0], LocalCache)
            self.realcache.caches = (newcache,) + self.realcache.caches[1:]

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__,
                            (self.localcache, self.stalecache, self.realcache))

CL_ONE = ConsistencyLevel.ONE
CL_QUORUM = ConsistencyLevel.QUORUM


class Permacache(object):
    """Cassandra key/value column family backend with a cachechain in front.
    
    Probably best to not think of this as a cache but rather as a key/value
    datastore that's faster to access than cassandra because of the cache.

    """

    COLUMN_NAME = 'value'

    def __init__(self, cache_chain, column_family, lock_factory):
        self.cache_chain = cache_chain
        self.make_lock = lock_factory
        self.cf = column_family

    @classmethod
    def _setup_column_family(cls, column_family_name, client,
                             read_consistency_level=CL_ONE,
                             write_consistency_level=CL_QUORUM):
        cf = ColumnFamily(client, column_family_name,
                          read_consistency_level=read_consistency_level,
                          write_consistency_level=write_consistency_level)
        return cf

    def _rcl(self, rcl=None):
        return rcl or self.cf.read_consistency_level

    def _wcl(self, wcl=None):
        return wcl or self.cf.write_consistency_level

    def _backend_get(self, keys, read_consistency_level=None):
        rcl = self._rcl(read_consistency_level)
        keys, is_single = tup(keys, ret_is_single=True)
        rows = self.cf.multiget(
            keys, columns=[self.COLUMN_NAME], read_consistency_level=rcl)
        ret = {
            key: pickle.loads(columns[self.COLUMN_NAME])
            for key, columns in rows.iteritems()
        }
        if is_single:
            if ret:
                return ret.values()[0]
            else:
                return None
        else:
            return ret

    def _backend_set(self, key, val, write_consistency_level=None):
        keys = {key: val}
        ret = self._backend_set_multi(
            keys, write_consistency_level=write_consistency_level)
        return ret.get(key)

    def _backend_set_multi(self, keys, prefix='', write_consistency_level=None):
        wcl = self._wcl(write_consistency_level)
        ret = {}
        with self.cf.batch(write_consistency_level=wcl):
            for key, val in keys.iteritems():
                rowkey = "%s%s" % (prefix, key)
                column = {self.COLUMN_NAME: pickle.dumps(val)}
                ret[key] = self.cf.insert(rowkey, column)
        return ret

    def _backend_delete(self, key, write_consistency_level=None):
        wcl = self._wcl(write_consistency_level)
        self.cf.remove(key, write_consistency_level=wcl)

    def get(self, key, default=None, allow_local=True, stale=False):
        val = self.cache_chain.get(
            key, default=None, allow_local=allow_local, stale=stale)

        if val is None:
            val = self._backend_get(key)
            if val:
                self.cache_chain.set(key, val)
        return val

    def set(self, key, val):
        self._backend_set(key, val)
        self.cache_chain.set(key, val)

    def set_multi(self, keys, prefix='', time=None):
        # time is sent by sgm but will be ignored
        self._backend_set_multi(keys, prefix=prefix)
        self.cache_chain.set_multi(keys, prefix=prefix)

    def get_multi(self, keys, prefix='', allow_local=True, stale=False):
        call_fn = lambda k: self.simple_get_multi(k, allow_local=allow_local,
                                                  stale=stale)
        return prefix_keys(keys, prefix, call_fn)

    def simple_get_multi(self, keys, allow_local=True, stale=False):
        ret = self.cache_chain.simple_get_multi(
            keys, allow_local=allow_local, stale=stale)
        still_need = {key for key in keys if key not in ret}
        if still_need:
            from_cass = self._backend_get(keys)
            self.cache_chain.set_multi(from_cass)
            ret.update(from_cass)
        return ret

    def delete(self, key):
        self._backend_delete(key)
        self.cache_chain.delete(key)

    def mutate(self, key, mutation_fn, default=None, willread=True):
        """Mutate a Cassandra key as atomically as possible"""
        with self.make_lock("permacache_mutate", "mutate_%s" % key):
            # This has an edge-case where the cache chain was populated by a ONE
            # read rather than a QUORUM one just before running this. We could
            # avoid this by not using memcached at all for these mutations,
            # which would require some more row-cache performance testing.
            read_consistency_level = write_consistency_level = CL_QUORUM
            if willread:
                value = self.cache_chain.get(key, allow_local=False)
                if value is None:
                    value = self._backend_get(key, read_consistency_level)
            else:
                value = None

            # send in a copy in case they mutate it in-place
            new_value = mutation_fn(copy(value))

            if not willread or value != new_value:
                self._backend_set(key, new_value, write_consistency_level)
            self.cache_chain.set(key, new_value, use_timer=False)
        return new_value

    def __repr__(self):
        return '<%s %r %r>' % (self.__class__.__name__,
                            self.cache_chain, self.cf.column_family)


def test_cache(cache, prefix=''):
    #basic set/get
    cache.set('%s1' % prefix, 1)
    assert cache.get('%s1' % prefix) == 1

    #python data
    cache.set('%s2' % prefix, [1,2,3])
    assert cache.get('%s2' % prefix) == [1,2,3]

    #set multi, no prefix
    cache.set_multi({'%s3' % prefix:3, '%s4' % prefix: 4})
    assert cache.get_multi(('%s3' % prefix, '%s4' % prefix)) == {'%s3' % prefix: 3, 
                                                                 '%s4' % prefix: 4}

    #set multi, prefix
    cache.set_multi({'3':3, '4': 4}, prefix='%sp_' % prefix)
    assert cache.get_multi(('3', 4), prefix='%sp_' % prefix) == {'3':3, 4: 4}
    assert cache.get_multi(('%sp_3' % prefix, '%sp_4' % prefix)) == {'%sp_3'%prefix: 3,
                                                                     '%sp_4'%prefix: 4}

    # delete
    cache.set('%s1'%prefix, 1)
    assert cache.get('%s1'%prefix) == 1
    cache.delete('%s1'%prefix)
    assert cache.get('%s1'%prefix) is None

    cache.set('%s1'%prefix, 1)
    cache.set('%s2'%prefix, 2)
    cache.set('%s3'%prefix, 3)
    assert cache.get('%s1'%prefix) == 1 and cache.get('%s2'%prefix) == 2
    cache.delete_multi(['%s1'%prefix, '%s2'%prefix])
    assert (cache.get('%s1'%prefix) is None
            and cache.get('%s2'%prefix) is None
            and cache.get('%s3'%prefix) == 3)

    #incr
    cache.set('%s5'%prefix, 1)
    cache.set('%s6'%prefix, 1)
    cache.incr('%s5'%prefix)
    assert cache.get('%s5'%prefix) == 2
    cache.incr('%s5'%prefix,2)
    assert cache.get('%s5'%prefix) == 4
    cache.incr_multi(('%s5'%prefix, '%s6'%prefix), 1)
    assert cache.get('%s5'%prefix) == 5
    assert cache.get('%s6'%prefix) == 2

def test_multi(cache):
    from threading import Thread

    num_threads = 100
    num_per_thread = 1000

    threads = []
    for x in range(num_threads):
        def _fn(prefix):
            def __fn():
                for y in range(num_per_thread):
                    test_cache(cache,prefix=prefix)
            return __fn
        t = Thread(target=_fn(str(x)))
        t.start()
        threads.append(t)

    for thread in threads:
        thread.join()

# a cache that occasionally dumps itself to be used for long-running
# processes
class SelfEmptyingCache(LocalCache):
    def __init__(self, max_size=10*1000):
        self.max_size = max_size

    def maybe_reset(self):
        if len(self) > self.max_size:
            self.clear()

    def set(self, key, val, time=0):
        self.maybe_reset()
        return LocalCache.set(self,key,val,time)

    def add(self, key, val, time=0):
        self.maybe_reset()
        return LocalCache.add(self, key, val)

def make_key(iden, *a, **kw):
    """
    A helper function for making memcached-usable cache keys out of
    arbitrary arguments. Hashes the arguments but leaves the `iden'
    human-readable
    """
    h = md5()

    def _conv(s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return s.encode('utf-8')
        elif isinstance(s, (tuple, list)):
            return ','.join(_conv(x) for x in s)
        elif isinstance(s, dict):
            return ','.join('%s:%s' % (_conv(k), _conv(v))
                            for (k, v) in sorted(s.iteritems()))
        else:
            return str(s)

    iden = _conv(iden)
    h.update(iden)
    h.update(_conv(a))
    h.update(_conv(kw))

    return '%s(%s)' % (iden, h.hexdigest())

def test_stale():
    from pylons import g
    ca = g.cache
    assert isinstance(ca, StaleCacheChain)

    ca.localcache.clear()

    ca.stalecache.set('foo', 'bar', time=ca.staleness)
    assert ca.stalecache.get('foo') == 'bar'
    ca.realcache.set('foo', 'baz')
    assert ca.realcache.get('foo') == 'baz'

    assert ca.get('foo', stale=True) == 'bar'
    ca.localcache.clear()
    assert ca.get('foo', stale=False) == 'baz'
    ca.localcache.clear()

    assert ca.get_multi(['foo'], stale=True) == {'foo': 'bar'}
    assert len(ca.localcache) == 0
    assert ca.get_multi(['foo'], stale=False) == {'foo': 'baz'}
    ca.localcache.clear()
