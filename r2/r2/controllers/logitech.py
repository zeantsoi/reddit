from r2.models import *
from validator import *
from r2.models.subreddit import MultiReddit
from r2.lib.normalized_hot import normalized_hot
from reddit_base import RedditController, base_listing
from r2.controllers import ListingController

from pylons.i18n import _
from hashlib import md5

## LOGITECH

class LogitechReddit(MultiReddit):
    path = '/entertainment'
    name = 'entertainment mix'
    sr_names = ['entertainment','videos','movies']

    stylesheet_master = 'logitech' # pull the stylesheet and whatnot
                                   # from this reddit
    sr_names += [stylesheet_master] # this one must be present

    def __init__(self):
        srs = Subreddit._by_name(self.sr_names)
        self.__srs = srs
        sr_ids = set( sr._id for sr in srs.values() )
        MultiReddit.__init__(self, sr_ids, '/logitech')

    def get_links(self, _sort, _time):
        return normalized_hot(self.sr_ids)

    @property
    def master(self):
        return self.__srs[self.stylesheet_master]

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

    # this one's a hack
    _fullname = inherit_prop('_fullname')

class LogitechController(ListingController):
    def title(self):
        return c.site.title

    def query(self):
        return c.site.get_links('hot', 'all')

    @base_listing
    @validate()
    def GET_listing(self, **env):
        c.site = LogitechReddit()
        return ListingController.GET_listing(self, **env)
