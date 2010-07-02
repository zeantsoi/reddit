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
from threading import local
from hashlib import md5
import cPickle as pickle
from copy import copy

import pylibmc
from _pylibmc import MemcachedError

import pycassa
import cassandra.ttypes

from r2.lib.contrib import memcache
from r2.lib.utils import in_chunks, prefix_keys
from r2.lib.hardcachebackend import HardCacheBackend

from r2.lib.sgm import sgm # get this into our namespace so that it's
                           # importable from us

class NoneResult(object): pass

class CacheUtils(object):
    def incr_multi(self, keys, delta=1, prefix=''):
        for k in keys:
            try:
                self.incr(prefix + k, delta)
            except ValueError:
                pass

    def add_multi(self, keys, prefix=''):
        for k,v in keys.iteritems():
            self.add(prefix+str(k), v)

    def get_multi(self, keys, prefix=''):
        return prefix_keys(keys, prefix, self.simple_get_multi)

class PyMemcache(CacheUtils, memcache.Client):
    """We still use our patched python-memcache to talk to the
       permacaches for legacy reasons"""
    simple_get_multi = memcache.Client.get_multi

    def __init__(self, servers):
        memcache.Client.__init__(self, servers, pickleProtocol = 1)

    def set_multi(self, keys, prefix='', time=0):
        new_keys = {}
        for k,v in keys.iteritems():
            new_keys[str(k)] = v
        memcache.Client.set_multi(self, new_keys, key_prefix = prefix,
                                  time = time)

    def get(self, key, default=None):
        r = memcache.Client.get(self, key)
        if r is None: return default
        return r

    def set(self, key, val, time=0):
        memcache.Client.set(self, key, val, time = time)

    def delete(self, key, time=0):
        memcache.Client.delete(self, key, time=time)

    def delete_multi(self, keys, prefix='', time=0):
        memcache.Client.delete_multi(self, keys, time = time,
                                     key_prefix = prefix)

class CMemcache(CacheUtils):
    def __init__(self,
                 servers,
                 debug = False,
                 noreply = False,
                 no_block = False,
                 num_clients = 10):
        self.servers = servers
        self.clients = pylibmc.ClientPool(n_slots = num_clients)
        for x in xrange(num_clients):
            client = pylibmc.Client(servers, binary=True)
            behaviors = {
                'no_block': no_block, # use async I/O
                'cache_lookups': True, # cache DNS lookups
                'tcp_nodelay': True, # no nagle
                '_noreply': int(noreply),
                'verify_key': int(debug),  # spend the CPU to verify keys
                'ketama': True, # consistent hashing
                }

            client.behaviors.update(behaviors)
            self.clients.put(client)

        self.min_compress_len = 512*1024

    def get(self, key, default = None):
        with self.clients.reserve() as mc:
            ret =  mc.get(key)
            if ret is None:
                return default
            return ret

    def get_multi(self, keys, prefix = ''):
        with self.clients.reserve() as mc:
            return mc.get_multi(keys, key_prefix = prefix)

    # simple_get_multi exists so that a cache chain can
    # single-instance the handling of prefixes for performance, but
    # pylibmc does this in C which is faster anyway, so CMemcache
    # implements get_multi itself. But the CacheChain still wants
    # simple_get_multi to be available for when it's already prefixed
    # them, so here it is
    simple_get_multi = get_multi

    def set(self, key, val, time = 0):
        with self.clients.reserve() as mc:
            return mc.set(key, val, time = time,
                          min_compress_len = self.min_compress_len)

    def set_multi(self, keys, prefix='', time=0):
        new_keys = {}
        for k,v in keys.iteritems():
            new_keys[str(k)] = v
        with self.clients.reserve() as mc:
            return mc.set_multi(new_keys, key_prefix = prefix,
                                time = time,
                                min_compress_len = self.min_compress_len)

    def add_multi(self, keys, prefix='', time=0):
        new_keys = {}
        for k,v in keys.iteritems():
            new_keys[str(k)] = v
        with self.clients.reserve() as mc:
            return mc.add_multi(new_keys, key_prefix = prefix,
                                time = time)

    def incr_multi(self, keys, prefix='', delta=1):
        with self.clients.reserve() as mc:
            return mc.incr_multi(map(str, keys),
                                 key_prefix = prefix,
                                 delta=delta)

    def append(self, key, val, time=0):
        with self.clients.reserve() as mc:
            return mc.append(key, val, time=time)

    def incr(self, key, delta=1, time=0):
        # ignore the time on these
        with self.clients.reserve() as mc:
            return mc.incr(key, delta)

    def add(self, key, val, time=0):
        try:
            with self.clients.reserve() as mc:
                return mc.add(key, val, time=time)
        except pylibmc.DataExists:
            return None

    def delete(self, key, time=0):
        with self.clients.reserve() as mc:
            return mc.delete(key)

    def delete_multi(self, keys, prefix='', time=0):
        with self.clients.reserve() as mc:
            return mc.delete_multi(keys, time = time,
                                   key_prefix = prefix)

    def __repr__(self):
        return '<%s(%r)>' % (self.__class__.__name__,
                             self.servers)

class HardCache(CacheUtils):
    backend = None

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

class CacheChain(CacheUtils, local):
    def __init__(self, caches, cache_negative_results=False):
        self.caches = caches
        self.cache_negative_results = cache_negative_results

    def make_set_fn(fn_name):
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

    def get(self, key, default = None, allow_local = True):
        for c in self.caches:
            if not allow_local and isinstance(c,LocalCache):
                continue

            val = c.get(key)

            if val is not None:
                #update other caches
                for d in self.caches:
                    if c is d:
                        break # so we don't set caches later in the chain
                    d.set(key, val)

                if val == NoneResult:
                    return default
                else:
                    return val

        #didn't find anything

        if self.cache_negative_results:
            for c in self.caches[:-1]:
                c.set(key, NoneResult)

        return default

    def get_multi(self, keys, prefix='', allow_local = True):
        l = lambda ks: self.simple_get_multi(ks, allow_local = allow_local)
        return prefix_keys(keys, prefix, l)

    def simple_get_multi(self, keys, allow_local = True):
        out = {}
        need = set(keys)
        for c in self.caches:
            if not allow_local and isinstance(c, LocalCache):
                continue

            if len(out) == len(keys):
                # we've found them all
                break
            r = c.simple_get_multi(need)
            #update other caches
            if r:
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
    def add(self, key, val, time=0):
        authority = self.caches[-1] # the authority is the hardcache
                                    # itself
        added_val = authority.add(key, val, time=time)
        for cache in self.caches[:-1]:
            # Calling set() rather than add() to ensure that all caches are
            # in sync and that de-syncs repair themselves
            cache.set(key, added_val, time=time)

        return added_val

    def accrue(self, key, time=0, delta=1):
        auth_value = self.caches[-1].get(key)

        if auth_value is None:
            self.caches[-1].set(key, 0, time)
            auth_value = 0

        try:
            auth_value = int(auth_value) + delta
        except ValueError:
            raise ValueError("Can't accrue %s; it's a %s (%r)" %
                             (key, auth_value.__class__.__name__, auth_value))

        for c in self.caches:
            c.set(key, auth_value, time=time)

    @property
    def backend(self):
        # the hardcache is always the last item in a HardCacheChain
        return self.caches[-1].backend

CL_ZERO = cassandra.ttypes.ConsistencyLevel.ZERO
CL_ONE = cassandra.ttypes.ConsistencyLevel.ONE
CL_QUORUM = cassandra.ttypes.ConsistencyLevel.QUORUM
CL_ALL = cassandra.ttypes.ConsistencyLevel.ALL

class CassandraCacheChain(CacheChain):
    def __init__(self, localcache, cassa, lock_factory, memcache=None, **kw):
        if memcache:
            caches = (localcache, memcache, cassa)
        else:
            caches = (localcache, cassa)

        self.cassa = cassa
        self.memcache = memcache
        self.make_lock = lock_factory
        CacheChain.__init__(self, caches, **kw)

    def mutate(self, key, mutation_fn, default = None):
        """Mutate a Cassandra key as atomically as possible"""
        with self.make_lock('mutate_%s' % key):
            # we have to do some of the the work of the cache chain
            # here so that we can be sure that if the value isn't in
            # memcached (an atomic store), we fetch it from Cassandra
            # with CL_QUORUM (because otherwise it's not an atomic
            # store). This requires us to know the structure of the
            # chain, which means that changing the chain will probably
            # require changing this function. (This has an edge-case
            # where memcached was populated by a ONE read rather than
            # a QUORUM one just before running this. We could avoid
            # this by not using memcached at all for these mutations,
            # which would require some more row-cache performace
            # testing)
            try:
                value = None
                if self.memcache:
                    value = self.memcache.get(key)
                if value is None:
                    value = self.cassa.get(key,
                                           read_consistency_level = CL_ONE)
            except cassandra.ttypes.NotFoundException:
                value = default

            # due to an old bug in NoneResult caching, we still have
            # some of these around
            if value == NoneResult:
                value = default

            new_value = mutation_fn(copy(value)) # send in a copy in
                                                 # case they mutate it
                                                 # in-place

            if value != new_value:
                self.cassa.set(key, new_value,
                               write_consistency_level = CL_QUORUM)
            for ca in self.caches[:-1]:
                # and update the rest of the chain; assumes that
                # Cassandra is always the last entry
                ca.set(key, new_value)
        return new_value

    def bulk_load(self, start='', end='', chunk_size = 100):
        """Try to load everything out of Cassandra and put it into
           memcached"""
        cf = self.cassa.cf
        for rows in in_chunks(cf.get_range(start=start,
                                           finish=end,
                                           columns=['value']),
                              chunk_size):
            print rows[0][0]
            rows = dict((key, pickle.loads(cols['value']))
                        for (key, cols)
                        in rows
                        if (cols
                            # hack
                            and len(key) < 250))
            self.memcache.set_multi(rows)


class CassandraCache(CacheUtils):
    """A cache that uses a Cassandra cluster. Uses a single keyspace
       and column family and only the column-name 'value'"""
    def __init__(self, keyspace, column_family, client,
                 read_consistency_level = CL_ONE,
                 write_consistency_level = CL_QUORUM):
        self.keyspace = keyspace
        self.column_family = column_family
        self.client = client
        self.cf = pycassa.ColumnFamily(self.client, self.keyspace,
                                       self.column_family,
                                       read_consistency_level = read_consistency_level,
                                       write_consistency_level = write_consistency_level)

    def _rcl(self, alternative):
        return (alternative if alternative is not None
                else self.cf.read_consistency_level)

    def _wcl(self, alternative):
        return (alternative if alternative is not None
                else self.cf.write_consistency_level)

    def get(self, key, default = None, read_consistency_level = None):
        try:
            rcl = self._rcl(read_consistency_level)
            row = self.cf.get(key, columns=['value'],
                              read_consistency_level = rcl)
            return pickle.loads(row['value'])
        except (cassandra.ttypes.NotFoundException, KeyError):
            return default

    def simple_get_multi(self, keys, read_consistency_level = None):
        rcl = self._rcl(read_consistency_level)
        rows = self.cf.multiget(list(keys),
                                columns=['value'],
                                read_consistency_level = rcl)
        return dict((key, pickle.loads(row['value']))
                    for (key, row) in rows.iteritems())

    def set(self, key, val,
            write_consistency_level = None, time = None):
        if val == NoneResult:
            # NoneResult caching is for other parts of the chain
            return

        wcl = self._wcl(write_consistency_level)
        ret = self.cf.insert(key, {'value': pickle.dumps(val)},
                              write_consistency_level = wcl)
        self._warm([key])
        return ret

    def set_multi(self, keys, prefix='',
                  write_consistency_level = None, time = None):
        if not isinstance(keys, dict):
            keys = dict(keys)
        keys = dict(('%s%s' % (prefix, key), val)
                     for (key, val) in keys.iteritems())
        wcl = self._wcl(write_consistency_level)
        ret = {}
        for key, val in keys.iteritems():
            if val != NoneResult:
                ret[key] = self.cf.insert(key, {'value': pickle.dumps(val)},
                                          write_consistency_level = wcl)
        self._warm(keys.keys())

        return ret

    def _warm(self, keys):
        import random
        if False and random.random() > 0.98:
            print 'Warming', keys
            self.cf.multiget(keys)

    def delete(self, key, write_consistency_level = None):
        wcl = self._wcl(write_consistency_level)
        self.cf.remove(key, write_consistency_level = wcl)


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
