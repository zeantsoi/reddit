from r2.lib.utils import Storage
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import NotFound
from r2.models import Subreddit

from pylons import g, c

import urllib
import re
import datetime
import os

class CollegeCounts(tdb_cassandra.Thing):
    '''
    Creates column family 'CollegeCounts' where rowkey is the date and columns
    are college names and data values are subreddit subscriber counts.
    '''

    _use_db = True
    _use_new_ring = True

    @staticmethod
    def _get_rowkey(dt):
        return dt.strftime('%Y-%j')

    @staticmethod
    def _get_date(rowkey):
        return datetime.datetime.strptime(rowkey,'%Y-%j')
    
    @classmethod
    def create(cls, name, count, date=None):
        """
        Use this instead of __init__ to have the rowkey automatically set to the
        correct value based on date.
        """
        if not date:
            date = datetime.datetime.now(g.tz)
        rowkey = cls._get_rowkey(date)
        name = name.lower() # Always store names in lowercase
        return CollegeCounts(_id=rowkey, **{name: count})

    @classmethod
    def get_counts_for_date(cls, date=None):
        if not date:
            date = datetime.datetime.now(g.tz)
        rowkey = cls._get_rowkey(date)

        try:
            cc = cls._byID(rowkey)
            counts = cc._t
            counts.pop('date')
        except tdb_cassandra.NotFound:
            return None

        # Return from Cassandra was unicode
        ret = {}
        for name, count in counts.iteritems():
            ret[str(name)] = int(count)

        return ret

    @classmethod
    def get_timestamp(cls, date=None):
        if not date:
            date = datetime.datetime.now(g.tz)
        rowkey = cls._get_rowkey(date)

        try:
            cc = cls._byID(rowkey)
            date = cc._t['date']
        except tdb_cassandra.NotFound:
            date = None
        return date

def backfill_cassandra(dir):
    """
    Copy subscription data from files into Cassandra.
    """
    files = os.listdir(dir)

    for fname in sorted(files):
        strdate = os.path.basename(fname).split('.')[0]
        date = datetime.datetime.strptime(strdate,'%Y-%j-%H')

        f = open(os.path.join(dir, fname), 'r')
        lines = f.readlines()
        f.close()

        for line in lines:
            name, count = line.split(',')
            count = int(count)
            cc = CollegeCounts.create(name, count, date)
            cc._commit()

class College(object):
    def __init__(self, name, original_count):
        self.name = name
        self.original_count = original_count
        self.previous_count = original_count
        self.current_count = original_count

    def update(self, new_count):
        self.previous_count = self.current_count
        self.current_count = new_count

    def get_count(self):
        return self.current_count

    def get_contest_growth(self):
        return self.current_count - self.original_count

    def get_day_growth(self):
        return self.current_count - self.previous_count

class Scoreboard(object):
    list_url = 'http://www.reddit.com/help/faqs/college'
    first_rowkey = '2011-242'       # The first date we have data for
    original_rowkey = 'original'    # 'Fake' row containing original
                                    # subscriber numbers

    def __init__(self, quick=False):
        self.colleges = {}
        self.sorted_colleges = None
        self._populated = False

        if quick:
            self._quick_populate()


    def update_college(self, name, count):
        name = name.lower()     # Colleges are always referred to by lowercase name
        if name in self.colleges:
            self.colleges[name].update(count)
        else:
            c = College(name, count)
            self.colleges[name] = c

    @classmethod
    def get_college_list(cls):
        """
        Read the wiki html and return a list of colleges.
        """
        f = urllib.urlopen(cls.list_url)
        text = f.read()
        f.close()

        # Hacky way to just grab the colleges
        text = text.split('<strong>College Subreddits:</strong>')[-1].split('<div class="footer-parent">')[0]
        names = re.findall('http://www.reddit.com/r/(\w+)/', text)
    
        return names

    @classmethod
    def write_current_counts(cls):
        """
        Get the current subscriber counts and put them into Cassandra.
        """
        names = cls.get_college_list()
        now = datetime.datetime.now(g.tz)
        srs = Subreddit._by_name(names)     # This can raise an exception if
                                            # len(names) <= 1 or all invalid

        for name in srs:
            count = srs[name]._ups
            cc = CollegeCounts.create(name, count, now)
            cc._commit()

    def write_original_counts(self):
        """
        Fill out the 'Fake' original row with college:original_subscriber_count.
        """
        if not self._populated:
            self._populate()
        for name in self.colleges:
            original_count = self.colleges[name].original_count
            cc = CollegeCounts(_id=self.original_rowkey,
                               **{name: original_count})
            cc._commit()

    def _quick_populate(self):
        """
        Don't read the full history, only the original counts, the most recent,
        and the one before that.
        """
        cc = CollegeCounts._byID(self.original_rowkey)
        original_counts = cc._t # Unicode dict
        original_date = original_counts.pop('date')

        first_date = CollegeCounts._get_date(self.first_rowkey)
        delta = datetime.timedelta(days=1)
        now = datetime.datetime.now() + delta # first_date doesn't have tz
                                              # go into the future to be sure
        date = now
        current_counts = None
        while date > first_date and current_counts == None:
            current_counts = CollegeCounts.get_counts_for_date(date)
            if not current_counts or len(current_counts) == 1:
                current_counts = None
                date -= delta
                continue
            self.date = CollegeCounts.get_timestamp(date=date)
            date -= delta
        if current_counts == None:
            raise tdb_cassandra.NotFound("Missing current_counts")

        previous_counts = None
        date -= delta
        while date > first_date and previous_counts == None:
            previous_counts = CollegeCounts.get_counts_for_date(date)
            if not previous_counts or len(previous_counts) == 1:
                previous_counts = None
                date -= delta
                continue
            date -= delta
        if previous_counts == None:
            raise tdb_cassandra.NotFound("Missing previous_counts")

        for name, current_count in current_counts.iteritems():
            original_count = int(original_counts.get(name, current_count))
            previous_count = previous_counts.get(name, current_count)
            college = College(name, current_count)
            college.original_count = original_count
            college.previous_count = previous_count
            self.colleges[name] = college

        self._populated = True

    def _populate(self):
        """
        Get all the subscription counts from Cassandra and fill out the
        Scoreboard.
        """
        first_date = CollegeCounts._get_date(self.first_rowkey)
        delta = datetime.timedelta(days=1)
        now = datetime.datetime.now() + delta # first_date doesn't have tz
                                              # go into the future to be sure

        date = first_date
        while date <= now:
            counts = CollegeCounts.get_counts_for_date(date)
            if not counts or len(counts) == 1:
                date += delta
                continue
            recent = set(counts.keys())
            last_update = CollegeCounts.get_timestamp(date=date)
            for name, count in counts.iteritems():
                self.update_college(name, count)
            date += delta

        # Remove colleges that weren't found in most recent list
        inactive = set(self.colleges.keys()) - recent

        for name in inactive:
            self.colleges.pop(name)

        self.date = last_update
        self._populated = True

    def get_date(self):
        if not self._populated:
            self._populate()
        return self.date

    def get_data(self):
        if not self._populated:
            self._populate()

        data = []
        srs = Subreddit._by_name(self.colleges.keys())

        for name in self.colleges:
            college = self.colleges[name]
            sr = srs[name]
            subreddit_path = sr.path
            if c.cname:
                subreddit_path = ("http://" + get_domain(cname = (site == sr),
                                                         subreddit = False))
                if c.site != sr:
                    subreddit_path += sr.path
            current = college.get_count()
            delta_total = college.get_contest_growth()
            delta_period = college.get_day_growth()

            s = Storage(name=name, title=sr.title, 
                        path=subreddit_path, 
                        current=current,
                        delta_total=delta_total, 
                        delta_period=delta_period,
                        short_name='[r/%s]' % sr.name)
            data.append(s)
        return data

def write_original_counts():
    sb = Scoreboard()
    sb.write_original_counts()

def update():
    Scoreboard.write_current_counts()

