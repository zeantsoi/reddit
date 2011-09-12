from r2.controllers.reddit_base import RedditController
from r2.lib.pages import BoringPage, CollegeRanking
from pylons import request

class CollegeController(RedditController):
    def GET_rankings(self):
        sort = request.params.get('sort', 'top').strip('/')
        if not sort in ('top', 'day', 'contest'):
            sort = 'top'
        return BoringPage('\'Grow A College Subreddit\' Scoreboard',
                      content = CollegeRanking(sort)).render()
