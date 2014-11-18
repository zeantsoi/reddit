import json
from collections import defaultdict
from datetime import datetime, timedelta

from pylons import g

from r2.lib.db.sorts import epoch_seconds
from r2.lib.db.tdb_cassandra import write_consistency_level
from r2.lib.utils import in_chunks
from r2.models.vote import VoteDetailsByComment, VoteDetailsByLink, VoterIPByThing


def backfill_vote_details(cls):
    ninety_days = timedelta(days=90).total_seconds()
    for chunk in in_chunks(cls._all(), size=100):
        ip_chunk = defaultdict(dict)
        with cls._cf.batch(write_consistency_level=cls._write_consistency_level) as b:
            for vote_list in chunk:
                thing_id36 = vote_list._id
                thing_fullname = vote_list.votee_fullname
                details = vote_list.decode_details()
                for detail in details:
                    voter_id36 = detail["voter_id"]

                    if "ip" in detail and detail["ip"]:
                        ip = detail["ip"]
                        ip_chunk[thing_fullname][voter_id36] = ip
                        redacted = dict(detail)
                        del redacted["ip"]
                        cast = detail["date"]
                        now = epoch_seconds(datetime.utcnow().replace(tzinfo=g.tz))
                        ttl = ninety_days - (now - cast)
                        oneweek = ""
                        if ttl < 3600 * 24 * 7:
                            oneweek = "(<= one week left)"
                        print "Inserting %s with ttl %d %s" % (redacted, ttl, oneweek)
                        b.insert(thing_id36, {voter_id36: json.dumps(redacted)}, ttl=ttl)

        for votee_fullname, valuedict in ip_chunk.iteritems():
            VoterIPByThing._set_values(votee_fullname, valuedict)


def main():
    cfs = [VoteDetailsByComment, VoteDetailsByLink]
    for cf in cfs:
        backfill_vote_details(cf)

if __name__ == '__builtin__':
    main()
