"""
Generate the data for the listings for the time-based Subreddit
queries. The format is eventually that of the CachedResults objects
used by r2.lib.db.queries (with some intermediate steps), so changes
there may warrant changes here
"""

# to run:
"""
export LINKDBHOST=prec01
export USER=ri
export INI=production.ini
cd ~/reddit/r2
time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', 'link',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_link t
                  where not t.spam and not t.deleted
                  )
                  to 'reddit_thing_link.dump'"
time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select d.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d
                  where d.key = 'url' ) to 'reddit_data_link.dump'"
cat reddit_data_link.dump reddit_thing_link.dump | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/migrate/mr_domains.py -c "join_links()" > links.joined
cat links.joined | paster --plugin=r2 run $INI r2/lib/migrate/mr_domains.py -c "time_listings()" | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/migrate/mr_domains.py -c "write_permacache()"
"""

import sys

from r2.models import Account, Subreddit, Link
from r2.lib.db.sorts import epoch_seconds, score, controversy, _hot
from r2.lib.db import queries
from r2.lib import mr_tools
from r2.lib.utils import timeago, UrlParser
from r2.lib.jsontemplates import make_fullname # what a strange place
                                               # for this function
from r2.lib.mr_top import store_keys, join_links, write_permacache

def time_listings(times = ('year','month','week','day','hour', 'all')):
    oldests = dict((t, epoch_seconds(timeago('1 %s' % t)))
                   for t in times if t != "all")
    oldests['all'] = epoch_seconds(timeago('10 years'))

    @mr_tools.dataspec_m_thing(("url", str),)
    def process(link):
        assert link.thing_type == 'link'

        timestamp = link.timestamp
        fname = make_fullname(Link, link.thing_id)

        if not link.spam and not link.deleted:
            if link.url:
                domains = UrlParser(link.url).domain_permutations()
            else:
                domains = []
            ups, downs = link.ups, link.downs

            for tkey, oldest in oldests.iteritems():
                if timestamp > oldest:
                    sc = score(ups, downs)
                    contr = controversy(ups, downs)
                    h = _hot(ups, downs, timestamp)
                    for domain in domains:
                        yield ('domain/top/%s/%s' % (tkey, domain),
                               sc, timestamp, fname)
                        yield ('domain/controversial/%s/%s' % (tkey, domain),
                               contr, timestamp, fname)
                        if tkey == "all":
                            yield ('domain/hot/%s/%s' % (tkey, domain),
                                   h, timestamp, fname)
                            yield ('domain/new/%s/%s' % (tkey, domain),
                                   timestamp, timestamp, fname)

    mr_tools.mr_map(process)
