#!/bin/sh

LINKDBHOST=prec01

# e.g. 'year'
INTERVAL="$1"

# e.g. '("hour","day","week","month","year")'
LISTINGS="$2"

FNAME=links.$INTERVAL.joined
export PATH=/usr/local/pgsql/bin:/usr/local/bin:$PATH

cd $HOME/reddit/r2

if [ -e $FNAME ]; then
  echo cannot start because $FNAME existss
  exit 1
fi

# make this exist immediately to act as a lock
touch $FNAME

psql -F"\t" -A -t -d newreddit -U ri -h $LINKDBHOST \
    -c "\\copy (select t.thing_id,
                       'link',
                       t.ups,
                       t.downs,
                       t.deleted,
                       t.spam,
                       extract(epoch from t.date),
                       d.value
                  from reddit_thing_link t,
                       reddit_data_link d
                 where t.thing_id = d.thing_id
                   and not t.spam and not t.deleted
                   and d.key = 'sr_id'
                   and t.date > now() - interval '1 $INTERVAL'
               ) to '$FNAME'"
cat $FNAME | paster --plugin=r2 run production_batch.ini r2/lib/mr_top.py -c "time_listings($LISTINGS)" \
 | sort -T. -S200m \
 | paster --plugin=r2 run production_batch.ini r2/lib/mr_top.py -c "write_permacache()"

rm $FNAME

