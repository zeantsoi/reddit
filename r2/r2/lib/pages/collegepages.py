from r2.lib.memoize import memoize
from r2.lib.menus import NavButton
from r2.lib.wrapped import Templated
from r2.models.college import Scoreboard
from r2.lib.utils import timesince

class CollegeRanking(Templated):
    def __init__(self, sort):
        self.sort = sort

        # Buttons
        self.buttons = {}
        self.buttons['contest'] = NavButton('Contest +/-', '/college?sort=contest')
        self.buttons['day'] = NavButton('24h +/-', '/college?sort=day')
        self.buttons['top'] = NavButton('Subscribers', '/college?sort=top')
        for b in self.buttons.values():
            b.build()

        # Data
        date, sorted_data = self.get_all_data()
        self.timesince = timesince(date)
        self.colleges = sorted_data[sort]
        Templated.__init__(self)

    @staticmethod
    @memoize('college-scoreboard-data', 60*15)
    def get_all_data():
        """
        Get all sorts at once so they are in sync.
        Cassandra cf CollegeCounts is updated in separate cron job. 
        
        TODO: Check that we don't have the problem where an incomplete row is 
        read when it has recently been written.
        """
        sb = Scoreboard(quick=True)
        date = sb.get_date()
        data = sb.get_data()

        sorted_data = {}        
        sorted_data['top'] = sorted(data, key=lambda c: c.current, reverse=True)
        sorted_data['day'] = sorted(data, key=lambda c: c.delta_period, reverse=True)
        sorted_data['contest'] = sorted(data, key=lambda c: c.delta_total, reverse=True)

        return date, sorted_data
