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
from pylons import config
import pytz, os, logging, sys, socket, re, subprocess, random
import signal
from datetime import timedelta, datetime
import pycassa
from r2.lib.cache import LocalCache, SelfEmptyingCache
from r2.lib.cache import CMemcache
from r2.lib.cache import HardCache, MemcacheChain, MemcacheChain, HardcacheChain
from r2.lib.cache import CassandraCache, CassandraCacheChain, CacheChain, CL_ONE, CL_QUORUM, CL_ZERO
from r2.lib.utils import thread_dump
from r2.lib.db.stats import QueryStats
from r2.lib.translation import get_active_langs
from r2.lib.lock import make_lock_factory
from r2.lib.manager import db_manager

class Globals(object):

    int_props = ['page_cache_time',
                 'solr_cache_time',
                 'num_mc_clients',
                 'MIN_DOWN_LINK',
                 'MIN_UP_KARMA',
                 'MIN_DOWN_KARMA',
                 'MIN_RATE_LIMIT_KARMA',
                 'MIN_RATE_LIMIT_COMMENT_KARMA',
                 'REPLY_AGE_LIMIT',
                 'WIKI_KARMA',
                 'HOT_PAGE_AGE',
                 'MODWINDOW',
                 'RATELIMIT',
                 'QUOTA_THRESHOLD',
                 'num_comments',
                 'max_comments',
                 'max_comments_gold',
                 'num_default_reddits',
                 'num_query_queue_workers',
                 'max_sr_images',
                 'num_serendipity',
                 'sr_dropdown_threshold',
                 'comment_visits_period',
                 ]

    float_props = ['min_promote_bid',
                   'max_promote_bid',
                   'usage_sampling',
                   ]

    bool_props = ['debug', 'translator',
                  'log_start',
                  'sqlprinting',
                  'template_debug',
                  'uncompressedJS',
                  'enable_doquery',
                  'use_query_cache',
                  'write_query_queue',
                  'css_killswitch',
                  'db_create_tables',
                  'disallow_db_writes',
                  'exception_logging',
                  'amqp_logging',
                  'read_only_mode',
                  ]

    tuple_props = ['memcaches',
                   'permacache_memcaches',
                   'rendercaches',
                   'local_rendercache',
                   'servicecaches',
                   'cassandra_seeds',
                   'admins',
                   'sponsors',
                   'monitored_servers',
                   'automatic_reddits',
                   'agents',
                   'allowed_css_linked_domains',
                   'authorized_cnames',
                   'hardcache_categories',
                   'proxy_addr']

    choice_props = {'cassandra_rcl': {'ZERO':   CL_ZERO,
                                      'ONE':    CL_ONE,
                                      'QUORUM': CL_QUORUM},
                    'cassandra_wcl': {'ZERO':   CL_ZERO,
                                      'ONE':    CL_ONE,
                                      'QUORUM': CL_QUORUM},
                    }


    def __init__(self, global_conf, app_conf, paths, **extra):
        """
        Globals acts as a container for objects available throughout
        the life of the application.

        One instance of Globals is created by Pylons during
        application initialization and is available during requests
        via the 'g' variable.

        ``global_conf``
            The same variable used throughout ``config/middleware.py``
            namely, the variables from the ``[DEFAULT]`` section of the
            configuration file.

        ``app_conf``
            The same ``kw`` dictionary used throughout
            ``config/middleware.py`` namely, the variables from the
            section in the config file for your application.

        ``extra``
            The configuration returned from ``load_config`` in 
            ``config/middleware.py`` which may be of use in the setup of
            your global variables.

        """

        # slop over all variables to start with
        for k, v in  global_conf.iteritems():
            if not k.startswith("_") and not hasattr(self, k):
                if k in self.int_props:
                    v = int(v)
                elif k in self.float_props:
                    v = float(v)
                elif k in self.bool_props:
                    v = self.to_bool(v)
                elif k in self.tuple_props:
                    v = tuple(self.to_iter(v))
                elif k in self.choice_props:
                    if v not in self.choice_props[k]:
                        raise ValueError("Unknown option for %r: %r not in %r"
                                         % (k, v, self.choice_props[k]))
                    v = self.choice_props[k][v]
                setattr(self, k, v)

        self.running_as_script = global_conf.get('running_as_script', False)

        if hasattr(signal, 'SIGUSR1'):
            # not all platforms have user signals
            signal.signal(signal.SIGUSR1, thread_dump)

        # initialize caches. Any cache-chains built here must be added
        # to cache_chains (closed around by reset_caches) so that they
        # can properly reset their local components

        localcache_cls = (SelfEmptyingCache if self.running_as_script
                          else LocalCache)
        num_mc_clients = self.num_mc_clients

        self.cache_chains = []

        self.memcache = CMemcache(self.memcaches, num_clients = num_mc_clients)
        self.make_lock = make_lock_factory(self.memcache)

        if not self.cassandra_seeds:
            raise ValueError("cassandra_seeds not set in the .ini")
        self.cassandra_seeds = list(self.cassandra_seeds)
        random.shuffle(self.cassandra_seeds)
        self.cassandra = pycassa.connect_thread_local(self.cassandra_seeds)
        perma_memcache = (CMemcache(self.permacache_memcaches, num_clients = num_mc_clients)
                          if self.permacache_memcaches
                          else None)
        self.permacache = self.init_cass_cache('permacache', 'permacache',
                                               self.cassandra,
                                               self.make_lock,
                                               memcache = perma_memcache,
                                               read_consistency_level = self.cassandra_rcl,
                                               write_consistency_level = self.cassandra_wcl,
                                               localcache_cls = localcache_cls)
        self.cache_chains.append(self.permacache)

        self.urlcache = self.init_cass_cache('permacache', 'urls',
                                             self.cassandra,
                                             self.make_lock,
                                             # TODO: increase this to QUORUM
                                             # once we switch to live
                                             read_consistency_level = self.cassandra_rcl,
                                             write_consistency_level = CL_ONE,
                                             localcache_cls = localcache_cls)
        self.cache_chains.append(self.urlcache)
        # hardcache is done after the db info is loaded, and then the
        # chains are reset to use the appropriate initial entries

        self.cache = MemcacheChain((localcache_cls(), self.memcache))
        self.cache_chains.append(self.cache)

        self.rendercache = MemcacheChain((localcache_cls(),
                                          CMemcache(self.rendercaches,
                                                    noreply=True, no_block=True,
                                                    num_clients = num_mc_clients)))
        self.cache_chains.append(self.rendercache)

        self.servicecache = MemcacheChain((localcache_cls(),
                                           CMemcache(self.servicecaches,
                                                     num_clients = num_mc_clients)))
        self.cache_chains.append(self.servicecache)

        self.thing_cache = CacheChain((localcache_cls(),))
        self.cache_chains.append(self.thing_cache)

        # set default time zone if one is not set
        tz = global_conf.get('timezone')
        dtz = global_conf.get('display_timezone', tz)

        self.tz = pytz.timezone(tz)
        self.display_tz = pytz.timezone(dtz)

        #load the database info
        self.dbm = self.load_db_params(global_conf)

        # can't do this until load_db_params() has been called
        self.hardcache = HardcacheChain((localcache_cls(),
                                         self.memcache,
                                         HardCache(self)),
                                        cache_negative_results = True)
        self.cache_chains.append(self.hardcache)

        # I know this sucks, but we need non-request-threads to be
        # able to reset the caches, so we need them be able to close
        # around 'cache_chains' without being able to call getattr on
        # 'g'
        cache_chains = self.cache_chains[::]
        def reset_caches():
            for chain in cache_chains:
                chain.reset()

        self.reset_caches = reset_caches
        self.reset_caches()

        #make a query cache
        self.stats_collector = QueryStats()

        # set the modwindow
        self.MODWINDOW = timedelta(self.MODWINDOW)

        self.REDDIT_MAIN = bool(os.environ.get('REDDIT_MAIN'))

        # turn on for language support
        self.languages, self.lang_name = \
                        get_active_langs(default_lang= self.lang)

        all_languages = self.lang_name.keys()
        all_languages.sort()
        self.all_languages = all_languages

        self.paths = paths

        # load the md5 hashes of files under static
        static_files = os.path.join(paths.get('static_files'), 'static')
        self.static_md5 = {}
        if os.path.exists(static_files):
            for f in os.listdir(static_files):
                if f.endswith('.md5'):
                    key = f[0:-4]
                    f = os.path.join(static_files, f)
                    with open(f, 'r') as handle:
                        md5 = handle.read().strip('\n')
                    self.static_md5[key] = md5


        #set up the logging directory
        log_path = self.log_path
        process_iden = global_conf.get('scgi_port', 'default')
        self.reddit_port = process_iden
        if log_path:
            if not os.path.exists(log_path):
                os.makedirs(log_path)
            for fname in os.listdir(log_path):
                if fname.startswith(process_iden):
                    full_name = os.path.join(log_path, fname)
                    os.remove(full_name)

        #setup the logger
        self.log = logging.getLogger('reddit')
        self.log.addHandler(logging.StreamHandler())
        if self.debug:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        # set log level for pycountry which is chatty
        logging.getLogger('pycountry.db').setLevel(logging.CRITICAL)

        if not self.media_domain:
            self.media_domain = self.domain
        if self.media_domain == self.domain:
            print ("Warning: g.media_domain == g.domain. " +
                   "This may give untrusted content access to user cookies")

        #read in our CSS so that it can become a default for subreddit
        #stylesheets
        stylesheet_path = os.path.join(paths.get('static_files'),
                                       self.static_path.lstrip('/'),
                                       self.stylesheet)
        with open(stylesheet_path) as s:
            self.default_stylesheet = s.read()

        self.profanities = None
        if self.profanity_wordlist and os.path.exists(self.profanity_wordlist):
            with open(self.profanity_wordlist, 'r') as handle:
                words = []
                for line in handle:
                    words.append(line.strip(' \n\r'))
                if words:
                    self.profanities = re.compile(r"\b(%s)\b" % '|'.join(words),
                                              re.I | re.U)

        self.reddit_host = socket.gethostname()
        self.reddit_pid  = os.getpid()

        #the shutdown toggle
        self.shutdown = False

        #if we're going to use the query_queue, we need amqp
        if self.write_query_queue and not self.amqp_host:
            raise Exception("amqp_host must be defined to use the query queue")

        # This requirement doesn't *have* to be a requirement, but there are
        # bugs at the moment that will pop up if you violate it
        if self.write_query_queue and not self.use_query_cache:
            raise Exception("write_query_queue requires use_query_cache")

        # try to set the source control revision number
        try:
            popen = subprocess.Popen(["git", "log", "--date=short",
                                      "--pretty=format:%H %h", '-n1'],
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
            resp, stderrdata = popen.communicate()
            resp = resp.strip().split(' ')
            self.version, self.short_version = resp
        except object, e:
            self.log.info("Couldn't read source revision (%r)" % e)
            self.version = self.short_version = '(unknown)'

        if self.log_start:
            self.log.error("reddit app %s:%s started %s at %s" %
                           (self.reddit_host, self.reddit_pid,
                            self.short_version, datetime.now()))

    def init_cass_cache(self, keyspace, column_family, cassandra_client,
                        lock_factory,
                        memcache = None,
                        read_consistency_level = CL_ONE,
                        write_consistency_level = CL_ONE,
                        localcache_cls = LocalCache):
        return CassandraCacheChain(localcache_cls(),
                                   CassandraCache(keyspace, column_family,
                                                  cassandra_client,
                                                  read_consistency_level = read_consistency_level,
                                                  write_consistency_level = write_consistency_level),
                                   memcache = memcache,
                                   lock_factory = lock_factory)

    @staticmethod
    def to_bool(x):
        return (x.lower() == 'true') if x else None

    @staticmethod
    def to_iter(v, delim = ','):
        return (x.strip() for x in v.split(delim) if x)

    def load_db_params(self, gc):
        from r2.lib.services import get_db_load

        self.databases = tuple(self.to_iter(gc['databases']))
        self.db_params = {}
        if not self.databases:
            return

        dbm = db_manager.db_manager()
        db_param_names = ('name', 'db_host', 'db_user', 'db_pass',
                          'pool_size', 'max_overflow')
        for db_name in self.databases:
            conf_params = self.to_iter(gc[db_name + '_db'])
            params = dict(zip(db_param_names, conf_params))
            if params['db_user'] == "*":
                params['db_user'] = self.db_user
            if params['db_pass'] == "*":
                params['db_pass'] = self.db_pass
            ip = params['db_host']
            ip_loads = get_db_load(self.servicecache, ip)
            if ip not in ip_loads or ip_loads[ip][0] < 1000:
                dbm.setup_db(db_name, g_override=self, **params)
            self.db_params[db_name] = params

        dbm.type_db = dbm.get_engine(gc['type_db'])
        dbm.relation_type_db = dbm.get_engine(gc['rel_type_db'])

        def split_flags(p):
            return ([n for n in p if not n.startswith("!")],
                    dict((n.strip('!'), True) for n in p if n.startswith("!")))

        prefix = 'db_table_'
        for k, v in gc.iteritems():
            if k.startswith(prefix):
                params = list(self.to_iter(v))
                name = k[len(prefix):]
                kind = params[0]
                if kind == 'thing':
                    engines, flags = split_flags(params[1:])
                    dbm.add_thing(name, dbm.get_engines(engines),
                                  **flags)
                elif kind == 'relation':
                    engines, flags = split_flags(params[3:])
                    dbm.add_relation(name, params[1], params[2],
                                     dbm.get_engines(engines),
                                     **flags)
        return dbm

    def __del__(self):
        """
        Put any cleanup code to be run when the application finally exits 
        here.
        """
        pass

