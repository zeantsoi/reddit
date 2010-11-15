from r2.models import *
from validator import *
from r2.models.subreddit import MultiReddit
from r2.lib.normalized_hot import normalized_hot
from reddit_base import RedditController, base_listing
from r2.controllers import HotController

from pylons.i18n import _
from hashlib import md5

## LOGITECH

class LogitechReddit(MultiReddit):
    path = '/entertainment'
    sr_names = ['entertainment','videos','movies',
                'scifi','television','wearethefilmmakers','movieclub']

    stylesheet_master = 'logitech' # pull the stylesheet and whatnot
                                   # from this reddit

    def __init__(self):
        srs = Subreddit._by_name(self.sr_names)
        self.__srs = srs
        self.__master = Subreddit._by_name(self.stylesheet_master)
        sr_ids = set( sr._id for sr in srs.values() )
        MultiReddit.__init__(self, sr_ids, '/logitech')

    def get_links(self, _sort, _time):
        return normalized_hot(self.sr_ids)

    @property
    def master(self):
        return self.__master

    def inherit_prop(name):
        def fn(self):
            return getattr(self.master, name, '')
        return property(fn)

    stylesheet_contents = inherit_prop('stylesheet_contents')
    stylesheet_hash = inherit_prop('stylesheet_hash')
    header = inherit_prop('header')
    header_title = inherit_prop('header_title')
    description = inherit_prop('description')
    show_media = inherit_prop('show_media')

    sponsorship_text = inherit_prop('sponsorship_text')
    sponsorship_url = inherit_prop('sponsorship_url')
    sponsorship_img = inherit_prop('sponsorship_img')
    sponsorship_name = inherit_prop('sponsorship_name')

    title = inherit_prop('title')
    name = inherit_prop('title') # n.b. these are equal

    # this one's a hack
    _fullname = inherit_prop('_fullname')

class LogitechController(HotController):
    nextprev = False

    def title(self):
        return c.site.title

    def query(self):
        return c.site.get_links('hot', 'all')

    @base_listing
    @validate()
    def GET_listing(self, **env):
        lr = LogitechReddit()

        if lr.master.can_view(c.user):
            c.site = lr
            c.default_sr = False
            c.disablesearchbox = True
            return HotController.GET_listing(self, **env)
        else:
            return self.abort404()
