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
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import collections
import json
import re
import simplejson
import socket
import time

from Cookie import CookieError
from copy import copy
from datetime import datetime, timedelta
from functools import wraps
from hashlib import sha1
from urllib import quote, unquote
from urlparse import urlparse

import babel.core
import pylibmc

from mako.filters import url_escape
from pylons import c, g, request, response
from pylons.i18n import _
from pylons.i18n.translation import LanguageError

from r2.config.extensions import is_api, set_extension
from r2.lib import filters, pages, utils, hooks
from r2.lib.authentication import authenticate_user
from r2.lib.base import BaseController, abort
from r2.lib.cache import make_key, MemcachedError
from r2.lib.errors import (
    ErrorSet,
    BadRequestError,
    ForbiddenError,
    errors,
    reddit_http_error,
)
from r2.lib.filters import _force_utf8, _force_unicode
from r2.lib.require import RequirementException, require, require_split
from r2.lib.strings import strings
from r2.lib.template_helpers import add_sr, JSPreload
from r2.lib.tracking import encrypt, decrypt
from r2.lib.translation import set_lang
from r2.lib.utils import (
    Enum,
    SimpleSillyStub,
    UniqueIterator,
    http_utils,
    is_subdomain,
    is_throttled,
    tup,
)
from r2.lib.validator import (
    build_arg_list,
    chksrname,
    fullname_regex,
    valid_jsonp_callback,
    validate,
    VByName,
    VCount,
    VLang,
    VLength,
    VLimit,
    VTarget,
)
from r2.models import (
    Account,
    All,
    AllMinus,
    DefaultSR,
    DomainSR,
    FakeAccount,
    FakeSubreddit,
    Friends,
    Frontpage,
    LabeledMulti,
    Link,
    Mod,
    ModMinus,
    MultiReddit,
    NotFound,
    OAuth2AccessToken,
    OAuth2Client,
    OAuth2Scope,
    Random,
    RandomNSFW,
    RandomSubscription,
    Sub,
    Subreddit,
    valid_admin_cookie,
    valid_feed,
    valid_otp_cookie,
)
from r2.lib.db import tdb_cassandra


NEVER = datetime(2037, 12, 31, 23, 59, 59)
DELETE = datetime(1970, 01, 01, 0, 0, 1)
PAGECACHE_POLICY = Enum(
    # logged in users may use the pagecache as well.
    "LOGGEDIN_AND_LOGGEDOUT",
    # only attempt to use pagecache if the current user is not logged in.
    "LOGGEDOUT_ONLY",
    # do not use pagecache.
    "NEVER",
)


def pagecache_policy(policy):
    """Decorate a controller method to specify desired pagecache behaviour.

    If not specified, the policy will default to LOGGEDOUT_ONLY.

    """

    assert policy in PAGECACHE_POLICY

    def pagecache_decorator(fn):
        fn.pagecache_policy = policy
        return fn
    return pagecache_decorator


cache_affecting_cookies = ('over18', '_options')

class Cookies(dict):
    def add(self, name, value, *k, **kw):
        name = name.encode('utf-8')
        self[name] = Cookie(value, *k, **kw)

class Cookie(object):
    def __init__(self, value, expires=None, domain=None,
                 dirty=True, secure=False, httponly=False):
        self.value = value
        self.expires = expires
        self.dirty = dirty
        self.secure = secure
        self.httponly = httponly
        if domain:
            self.domain = domain
        elif c.authorized_cname and not c.default_sr:
            self.domain = utils.common_subdomain(request.host, c.site.domain)
        else:
            self.domain = g.domain

    @staticmethod
    def classify(cookie_name):
        if cookie_name == g.login_cookie:
            return "session"
        elif cookie_name == g.admin_cookie:
            return "admin"
        elif cookie_name == "reddit_first":
            return "first"
        elif cookie_name == "over18":
            return "over18"
        elif cookie_name.endswith("_last_thing"):
            return "last_thing"
        elif cookie_name.endswith("_options"):
            return "options"
        elif cookie_name.endswith("_recentclicks2"):
            return "clicks"
        elif cookie_name.startswith("__utm"):
            return "ga"
        elif cookie_name.startswith("beta_"):
            return "beta"
        else:
            return "other"

    def __repr__(self):
        return ("Cookie(value=%r, expires=%r, domain=%r, dirty=%r)"
                % (self.value, self.expires, self.domain, self.dirty))

class UnloggedUser(FakeAccount):
    COOKIE_NAME = "_options"
    allowed_prefs = {
        "pref_lang": VLang.validate_lang,
        "pref_content_langs": VLang.validate_content_langs,
        "pref_frame_commentspanel": bool,
    }

    def __init__(self, browser_langs, *a, **kw):
        FakeAccount.__init__(self, *a, **kw)
        if browser_langs:
            lang = browser_langs[0]
            content_langs = list(browser_langs)
            # try to coerce the default language 
            if g.lang not in content_langs:
                content_langs.append(g.lang)
            content_langs.sort()
        else:
            lang = g.lang
            content_langs = 'all'
        self._defaults = self._defaults.copy()
        self._defaults['pref_lang'] = lang
        self._defaults['pref_content_langs'] = content_langs
        self._defaults['pref_frame_commentspanel'] = False
        self._load()

    @property
    def name(self):
        raise NotImplementedError

    def _decode_json(self, json_blob):
        data = json.loads(json_blob)
        validated = {}
        for k, v in data.iteritems():
            validator = self.allowed_prefs.get(k)
            if validator:
                try:
                    validated[k] = validator(v)
                except ValueError:
                    pass  # don't override defaults for bad data
        return validated

    def _from_cookie(self):
        cookie = c.cookies.get(self.COOKIE_NAME)
        if not cookie:
            return {}

        try:
            return self._decode_json(cookie.value)
        except ValueError:
            # old-style _options cookies are encrypted
            try:
                plaintext = decrypt(cookie.value)
                values = self._decode_json(plaintext)
            except (TypeError, ValueError):
                # this cookie is totally invalid, delete it
                c.cookies[self.COOKIE_NAME] = Cookie(value="", expires=DELETE)
                return {}
            else:
                self._to_cookie(values)  # upgrade the cookie
                return values

    def _to_cookie(self, data):
        allowed_data = {k: v for k, v in data.iteritems()
                        if k in self.allowed_prefs}
        jsonified = json.dumps(allowed_data, sort_keys=True)
        c.cookies[self.COOKIE_NAME] = Cookie(value=jsonified)

    def _subscribe(self, sr):
        pass

    def _unsubscribe(self, sr):
        pass

    def valid_hash(self, hash):
        return False

    def _commit(self):
        if self._dirty:
            for k, (oldv, newv) in self._dirties.iteritems():
                self._t[k] = newv
            self._to_cookie(self._t)

    def _load(self):
        self._t.update(self._from_cookie())
        self._loaded = True

def read_user_cookie(name):
    uname = c.user.name if c.user_is_loggedin else ""
    cookie_name = uname + '_' + name
    if cookie_name in c.cookies:
        return c.cookies[cookie_name].value
    else:
        return ''

def set_user_cookie(name, val, **kwargs):
    uname = c.user.name if c.user_is_loggedin else ""
    c.cookies[uname + '_' + name] = Cookie(value=val,
                                           **kwargs)


valid_click_cookie = fullname_regex(Link, True).match
def set_recent_clicks():
    c.recent_clicks = []
    if not c.user_is_loggedin:
        return

    click_cookie = read_user_cookie('recentclicks2')
    if click_cookie:
        if valid_click_cookie(click_cookie):
            names = [ x for x in UniqueIterator(click_cookie.split(',')) if x ]

            if len(names) > 5:
                names = names[:5]
                set_user_cookie('recentclicks2', ','.join(names))
            #eventually this will look at the user preference
            names = names[:5]

            try:
                c.recent_clicks = Link._by_fullname(names, data=True,
                                                    return_dict=False)
            except NotFound:
                # clear their cookie because it's got bad links in it
                set_user_cookie('recentclicks2', '')
        else:
            #if the cookie wasn't valid, clear it
            set_user_cookie('recentclicks2', '')

def delete_obsolete_cookies():
    for cookie_name in c.cookies:
        if cookie_name.endswith(("_last_thing", "_mod")):
            c.cookies[cookie_name] = Cookie("", expires=DELETE)

def over18():
    if c.user_is_loggedin:
        return c.user.pref_over_18 or c.user_is_admin
    else:
        if 'over18' in c.cookies:
            cookie = c.cookies['over18'].value
            if cookie == "1":
                return True
            else:
                c.cookies["over18"] = Cookie(value="", expires=DELETE)

def set_obey_over18():
    "querystring parameter for API to obey over18 filtering rules"
    c.obey_over18 = request.GET.get("obey_over18") == "true"

valid_ascii_domain = re.compile(r'\A(\w[-\w]*\.)+[\w]+\Z')
def set_subreddit():
    #the r parameter gets added by javascript for POST requests so we
    #can reference c.site in api.py
    sr_name = request.environ.get("subreddit", request.POST.get('r'))
    domain = request.environ.get("domain")

    can_stale = request.method.upper() in ('GET', 'HEAD')

    c.site = Frontpage
    if not sr_name:
        #check for cnames
        cname = request.environ.get('legacy-cname')
        if cname:
            sr = Subreddit._by_domain(cname) or Frontpage
            domain = g.domain
            if g.domain_prefix:
                domain = ".".join((g.domain_prefix, domain))
            path = 'http://%s%s' % (domain, sr.path)
            abort(301, location=BaseController.format_output_url(path))
    elif sr_name == 'r':
        #reddits
        c.site = Sub
    elif '+' in sr_name:
        sr_names = sr_name.split('+')
        srs = Subreddit._by_name(sr_names, stale=can_stale).values()
        if All in srs:
            c.site = All
        elif Friends in srs:
            c.site = Friends
        else:
            srs = [sr for sr in srs if not isinstance(sr, FakeSubreddit)]
            multi_path = '/r/' + sr_name
            if not srs:
                c.site = MultiReddit(multi_path, [])
            elif len(srs) == 1:
                c.site = srs[0]
            else:
                c.site = MultiReddit(multi_path, srs)
    elif '-' in sr_name:
        sr_names = sr_name.split('-')
        base_sr_name, exclude_sr_names = sr_names[0], sr_names[1:]
        srs = Subreddit._by_name(sr_names, stale=can_stale)
        base_sr = srs.pop(base_sr_name, None)
        exclude_srs = [sr for sr in srs.itervalues()
                          if not isinstance(sr, FakeSubreddit)]

        if base_sr == All:
            if exclude_srs:
                c.site = AllMinus(exclude_srs)
            else:
                c.site = All
        elif base_sr == Mod:
            if exclude_srs:
                c.site = ModMinus(exclude_srs)
            else:
                c.site = Mod
        else:
            path = "/subreddits/search?q=%s" % sr_name
            abort(302, location=BaseController.format_output_url(path))
    else:
        try:
            c.site = Subreddit._by_name(sr_name, stale=can_stale)
        except NotFound:
            sr_name = chksrname(sr_name)
            if sr_name:
                path = "/subreddits/search?q=%s" % sr_name
                abort(302, location=BaseController.format_output_url(path))
            elif not c.error_page and not request.path.startswith("/api/login/") :
                abort(404)

    #if we didn't find a subreddit, check for a domain listing
    if not sr_name and isinstance(c.site, DefaultSR) and domain:
        # Redirect IDN to their IDNA name if necessary
        try:
            idna = _force_unicode(domain).encode("idna")
            if idna != domain:
                path_info = request.environ["PATH_INFO"]
                path = "/domain/%s%s" % (idna, path_info)
                abort(302, location=BaseController.format_output_url(path))
        except UnicodeError:
            domain = ''  # Ensure valid_ascii_domain fails
        if not c.error_page and not valid_ascii_domain.match(domain):
            abort(404)
        c.site = DomainSR(domain)

    if isinstance(c.site, FakeSubreddit):
        c.default_sr = True


def set_multireddit():
    routes_dict = request.environ["pylons.routes_dict"]
    if "multipath" in routes_dict:
        multipath = routes_dict["multipath"].lower()
        multi_id = None

        if c.user_is_loggedin and routes_dict.get("my_multi"):
            multi_id = "/user/%s/m/%s" % (c.user.name.lower(), multipath)
        elif "username" in routes_dict:
            username = routes_dict["username"].lower()

            if c.user_is_loggedin:
                # redirect /user/foo/m/... to /me/m/... for user foo.
                if username == c.user.name.lower():
                    # trim off multi id
                    url_parts = request.path_qs.split("/")[5:]
                    url_parts.insert(0, "/me/m/%s" % multipath)
                    path = "/".join(url_parts)
                    abort(302, location=BaseController.format_output_url(path))

            multi_id = "/user/%s/m/%s" % (username, multipath)

        if multi_id:
            try:
                c.site = LabeledMulti._byID(multi_id)
            except tdb_cassandra.NotFound:
                abort(404)


def set_content_type():
    e = request.environ
    c.render_style = e['render_style']
    response.content_type = e['content_type']

    if e.has_key('extension'):
        c.extension = ext = e['extension']
        if ext in ('embed', 'widget'):
            wrapper = request.params.get("callback", "document.write")
            wrapper = filters._force_utf8(wrapper)
            if not valid_jsonp_callback(wrapper):
                abort(BadRequestError(errors.BAD_JSONP_CALLBACK))

            # force logged-out state since these can be accessed cross-domain
            c.user = UnloggedUser(get_browser_langs())
            c.user_is_loggedin = False

            def to_js(content):
                return wrapper + "(" + utils.string2js(content) + ");"

            c.response_wrapper = to_js
        if ext in ("rss", "api", "json") and request.method.upper() == "GET":
            user = valid_feed(request.GET.get("user"),
                              request.GET.get("feed"),
                              request.path)
            if user and not g.read_only_mode:
                c.user = user
                c.user_is_loggedin = True
        if ext in ("mobile", "m") and not request.GET.get("keep_extension"):
            try:
                if request.cookies['reddit_mobility'] == "compact":
                    c.extension = "compact"
                    c.render_style = "compact"
            except (ValueError, KeyError):
                c.suggest_compact = True
        if ext in ("mobile", "m", "compact"):
            if request.GET.get("keep_extension"):
                c.cookies['reddit_mobility'] = Cookie(ext, expires=NEVER)
    # allow JSONP requests to generate callbacks, but do not allow
    # the user to be logged in for these 
    callback = request.GET.get("jsonp")
    if is_api() and request.method.upper() == "GET" and callback:
        if not valid_jsonp_callback(callback):
            abort(BadRequestError(errors.BAD_JSONP_CALLBACK))
        c.allowed_callback = callback
        c.user = UnloggedUser(get_browser_langs())
        c.user_is_loggedin = False
        response.content_type = "application/javascript"

def get_browser_langs():
    browser_langs = []
    langs = request.environ.get('HTTP_ACCEPT_LANGUAGE')
    if langs:
        langs = langs.split(',')
        browser_langs = []
        seen_langs = set()
        # extract languages from browser string
        for l in langs:
            if ';' in l:
                l = l.split(';')[0]
            if l not in seen_langs and l in g.languages:
                browser_langs.append(l)
                seen_langs.add(l)
            if '-' in l:
                l = l.split('-')[0]
            if l not in seen_langs and l in g.languages:
                browser_langs.append(l)
                seen_langs.add(l)
    return browser_langs

def set_iface_lang():
    host_lang = request.environ.get('reddit-prefer-lang')
    lang = host_lang or c.user.pref_lang

    if getattr(g, "lang_override") and lang.startswith("en"):
        lang = g.lang_override

    c.lang = lang

    try:
        set_lang(lang, fallback_lang=g.lang)
    except LanguageError:
        lang = g.lang
        set_lang(lang, graceful_fail=True)

    try:
        c.locale = babel.core.Locale.parse(lang, sep='-')
    except (babel.core.UnknownLocaleError, ValueError):
        c.locale = babel.core.Locale.parse(g.lang, sep='-')


def set_content_lang():
    if c.user.pref_content_langs != 'all':
        c.content_langs = list(c.user.pref_content_langs)
        c.content_langs.sort()
    else:
        c.content_langs = c.user.pref_content_langs

def set_cnameframe():
    if (bool(request.params.get(utils.UrlParser.cname_get))
        or not request.host.split(":")[0].endswith(g.domain)):
        c.cname = True
        request.environ['REDDIT_CNAME'] = 1
    c.frameless_cname = request.environ.get('frameless_cname', False)
    if hasattr(c.site, 'domain'):
        c.authorized_cname = request.environ.get('authorized_cname', False)

def set_colors():
    theme_rx = re.compile(r'')
    color_rx = re.compile(r'\A([a-fA-F0-9]){3}(([a-fA-F0-9]){3})?\Z')
    c.theme = None
    if color_rx.match(request.GET.get('bgcolor') or ''):
        c.bgcolor = request.GET.get('bgcolor')
    if color_rx.match(request.GET.get('bordercolor') or ''):
        c.bordercolor = request.GET.get('bordercolor')


def _get_ratelimit_timeslice(slice_seconds):
    slice_start, secs_since = divmod(time.time(), slice_seconds)
    slice_start = time.gmtime(int(slice_start * slice_seconds))
    secs_to_next = slice_seconds - int(secs_since)
    return slice_start, secs_to_next


def ratelimit_agent(agent, limit=10, slice_size=10):
    slice_size = min(slice_size, 60)
    time_slice, retry_after = _get_ratelimit_timeslice(slice_size)
    key = "rate_agent_" + agent + time.strftime("_%S", time_slice)
    g.cache.add(key, 0, time=slice_size + 1)
    if g.cache.incr(key) > limit:
        request.environ['retry_after'] = retry_after
        abort(429)

appengine_re = re.compile(r'AppEngine-Google; \(\+http://code.google.com/appengine; appid: (?:dev|s)~([a-z0-9-]{6,30})\)\Z')
def ratelimit_agents():
    user_agent = request.user_agent

    if not user_agent:
        return

    # parse out the appid for appengine apps
    appengine_match = appengine_re.search(user_agent)
    if appengine_match:
        appid = appengine_match.group(1)
        ratelimit_agent(appid)
        return

    user_agent = user_agent.lower()
    for agent, limit in g.agents.iteritems():
        if agent in user_agent:
            ratelimit_agent(agent, limit)
            return

def ratelimit_throttled():
    ip = request.ip.strip()
    if is_throttled(ip):
        abort(429)


def paginated_listing(default_page_size=25, max_page_size=100, backend='sql'):
    def decorator(fn):
        @validate(num=VLimit('limit', default=default_page_size,
                             max_limit=max_page_size),
                  after=VByName('after', backend=backend),
                  before=VByName('before', backend=backend),
                  count=VCount('count'),
                  target=VTarget("target"),
                  show=VLength('show', 3, empty_error=None,
                               docs={"show": "(optional) the string `all`"}),
        )
        @wraps(fn)
        def new_fn(self, before, **env):
            if c.render_style == "htmllite":
                c.link_target = env.get("target")
            elif "target" in env:
                del env["target"]

            if "show" in env and env['show'] == 'all':
                c.ignore_hide_rules = True
            kw = build_arg_list(fn, env)

            #turn before into after/reverse
            kw['reverse'] = False
            if before:
                kw['after'] = before
                kw['reverse'] = True

            return fn(self, **kw)

        if hasattr(fn, "_api_doc"):
            notes = fn._api_doc["notes"] or []
            if paginated_listing.doc_note not in notes:
                notes.append(paginated_listing.doc_note)
            fn._api_doc["notes"] = notes

        return new_fn
    return decorator

paginated_listing.doc_note = "*This endpoint is [a listing](#listings).*"

#TODO i want to get rid of this function. once the listings in front.py are
#moved into listingcontroller, we shouldn't have a need for this
#anymore
def base_listing(fn):
    return paginated_listing()(fn)

def is_trusted_origin(origin):
    try:
        origin = urlparse(origin)
    except ValueError:
        return False

    return any(is_subdomain(origin.hostname, domain) for domain in g.trusted_domains)

def cross_domain(origin_check=is_trusted_origin, **options):
    """Set up cross domain validation and hoisting for a request handler."""
    def cross_domain_wrap(fn):
        cors_perms = {
            "origin_check": origin_check,
            "allow_credentials": bool(options.get("allow_credentials"))
        }

        @wraps(fn)
        def cross_domain_handler(self, *args, **kwargs):
            if request.params.get("hoist") == "cookie":
                # Cookie polling response
                if cors_perms["origin_check"](g.origin):
                    name = request.environ["pylons.routes_dict"]["action_name"]
                    resp = fn(self, *args, **kwargs)
                    c.cookies.add('hoist_%s' % name, ''.join(tup(resp)))
                    response.content_type = 'text/html'
                    return ""
                else:
                    abort(403)
            else:
                self.check_cors()
                return fn(self, *args, **kwargs)

        cross_domain_handler.cors_perms = cors_perms
        return cross_domain_handler
    return cross_domain_wrap

def require_https():
    if not c.secure:
        abort(ForbiddenError(errors.HTTPS_REQUIRED))


def require_domain(required_domain):
    if not is_subdomain(request.host, required_domain):
        abort(ForbiddenError(errors.WRONG_DOMAIN))


def disable_subreddit_css():
    def wrap(f):
        @wraps(f)
        def no_funny_business(*args, **kwargs):
            c.allow_styles = False
            return f(*args, **kwargs)
        return no_funny_business
    return wrap


def request_timer_name(action):
    return "service_time.web." + action


def flatten_response(content):
    """Convert a content iterable to a string, properly handling unicode."""
    # TODO: it would be nice to replace this with response.body someday
    # once unicode issues are ironed out.
    return "".join(_force_utf8(x) for x in tup(content) if x)


def abort_with_error(error, code=None):
    if not code and not error.code:
        raise ValueError('Error %r missing status code' % error)

    abort(reddit_http_error(
        code=code or error.code,
        error_name=error.name,
        explanation=error.message,
        fields=error.fields,
    ))


class MinimalController(BaseController):

    allow_stylesheets = False
    defer_ratelimiting = False

    def request_key(self):
        # note that this references the cookie at request time, not
        # the current value of it
        try:
            cookies_key = [(x, request.cookies.get(x, ''))
                           for x in cache_affecting_cookies]
        except CookieError:
            cookies_key = ''

        return make_key('request',
                        c.lang,
                        c.content_langs,
                        request.host,
                        c.secure,
                        c.cname,
                        request.fullpath,
                        c.over18,
                        c.extension,
                        c.render_style,
                        cookies_key)

    def cached_response(self):
        return ""

    def run_sitewide_ratelimits(self):
        """Ratelimit users and add ratelimit headers to the response.

        Headers added are:
        X-Ratelimit-Used: Number of requests used in this period
        X-Ratelimit-Remaining: Number of requests left to use
        X-Ratelimit-Reset: Approximate number of seconds to end of period

        This function only has an effect if one of
        g.RL_SITEWIDE_ENABLED or g.RL_OAUTH_SITEWIDE_ENABLED
        are set to 'true' in the app configuration

        If the ratelimit is exceeded, a 429 response will be sent,
        unless the app configuration has g.ENFORCE_RATELIMIT off.
        Headers will be sent even on aborted requests.

        """
        if c.error_page:
            # ErrorController is re-running pre, don't double ratelimit
            return
        if c.cdn_cacheable:
            type_ = "cdn"
        elif not is_api():
            type_ = "web"
        elif c.oauth_user and g.RL_OAUTH_SITEWIDE_ENABLED:
            type_ = "oauth"
            period = g.RL_OAUTH_RESET_SECONDS
            max_reqs = c.oauth_client._max_reqs
            # Convert client_id to ascii str for use as memcache key
            client_id = c.oauth2_access_token.client_id.encode("ascii")
            # OAuth2 ratelimits are per user-app combination
            key = 'siterl-oauth-' + c.user._id36 + ":" + client_id
        elif g.RL_SITEWIDE_ENABLED:
            type_ = "api"
            max_reqs = g.RL_MAX_REQS
            period = g.RL_RESET_SECONDS
            # API (non-oauth) limits are per-ip
            key = 'siterl-api-' + request.ip
        else:
            type_ = "none"

        g.stats.event_count("ratelimit.type", type_, sample_rate=0.01)
        if type_ in ("cdn", "web", "none"):
            # No ratelimiting or headers for:
            # * Web requests (HTML)
            # * CDN requests (logged out via www.reddit.com)
            return

        period_start, retry_after = _get_ratelimit_timeslice(period)
        key += time.strftime("-%H%M%S", period_start)

        try:
            g.ratelimitcache.add(key, 0, time=retry_after + 1)

            try:
                # Increment the key to track the current request
                recent_reqs = g.ratelimitcache.incr(key)
            except pylibmc.NotFound:
                # Previous round of ratelimiting fell out in the
                # time between calling `add` and calling `incr`.
                g.ratelimitcache.add(key, 1, time=retry_after + 1)
                recent_reqs = 1
        except pylibmc.Error as e:
            # Ratelimiting is non-critical; if the caches are
            # having issues, just skip adding the headers
            g.log.info("ratelimitcache error: %s", e)
            return

        reqs_remaining = max(0, max_reqs - recent_reqs)

        c.ratelimit_headers = {
            "X-Ratelimit-Used": str(recent_reqs),
            "X-Ratelimit-Reset": str(retry_after),
            "X-Ratelimit-Remaining": str(reqs_remaining),
        }

        if reqs_remaining <= 0:
            if recent_reqs > (2 * max_reqs):
                g.stats.event_count("ratelimit.exceeded", "hyperbolic")
            else:
                g.stats.event_count("ratelimit.exceeded", "over")
            if g.ENFORCE_RATELIMIT:
                # For non-abort situations, the headers will be added in post(),
                # to avoid including them in a pagecache
                response.headers.update(c.ratelimit_headers)
                abort(429)
        elif reqs_remaining < (0.1 * max_reqs):
            g.stats.event_count("ratelimit.exceeded", "close")

    def pre(self):
        action = request.environ["pylons.routes_dict"].get("action")
        if action:
            if not self._get_action_handler():
                action = 'invalid'
            controller = request.environ["pylons.routes_dict"]["controller"]
            key = "{}.{}".format(controller, action)
            c.request_timer = g.stats.get_timer(request_timer_name(key))
        else:
            c.request_timer = SimpleSillyStub()

        c.response_wrapper = None
        c.start_time = datetime.now(g.tz)
        c.request_timer.start()
        g.reset_caches()

        c.domain_prefix = request.environ.get("reddit-domain-prefix",
                                              g.domain_prefix)
        c.secure = request.environ["wsgi.url_scheme"] == "https"
        c.request_origin = request.host_url

        #check if user-agent needs a dose of rate-limiting
        if not c.error_page:
            ratelimit_throttled()
            ratelimit_agents()

        c.allow_loggedin_cache = False
        c.allow_framing = False

        c.cdn_cacheable = (request.via_cdn and
                           g.login_cookie not in request.cookies)

        c.extension = request.environ.get('extension')
        # the domain has to be set before Cookies get initialized
        set_subreddit()
        c.errors = ErrorSet()
        c.cookies = Cookies()
        # if an rss feed, this will also log the user in if a feed=
        # GET param is included
        set_content_type()

        c.request_timer.intermediate("minimal-pre")
        # True/False forces. None updates for most non-POST requests
        c.update_last_visit = None

        g.stats.count_string('user_agents', request.user_agent)

        if not self.defer_ratelimiting:
            self.run_sitewide_ratelimits()
            c.request_timer.intermediate("minimal-ratelimits")

        hooks.get_hook("reddit.request.minimal_begin").call()

    def can_use_pagecache(self):
        handler = self._get_action_handler()
        policy = getattr(handler, "pagecache_policy",
                         PAGECACHE_POLICY.LOGGEDOUT_ONLY)

        if policy == PAGECACHE_POLICY.LOGGEDIN_AND_LOGGEDOUT:
            return True
        elif policy == PAGECACHE_POLICY.LOGGEDOUT_ONLY:
            return not c.user_is_loggedin

        return False

    def try_pagecache(self):
        c.can_use_pagecache = self.can_use_pagecache()

        if request.method.upper() == 'GET' and c.can_use_pagecache:
            request_key = self.request_key()
            try:
                r = g.pagecache.get(request_key)
            except MemcachedError as e:
                g.log.warning("pagecache error: %s", e)
                return

            if r:
                r, c.cookies = r
                response.headers = r.headers
                response.body = r.body
                response.status_int = r.status_int

                request.environ['pylons.routes_dict']['action'] = 'cached_response'
                c.request_timer.name = request_timer_name("cached_response")

                c.used_cache = True
                # response wrappers have already been applied before cache write
                c.response_wrapper = None

    def post(self):
        c.request_timer.intermediate("action")

        # if the action raised an HTTPException (i.e. it aborted) then pylons
        # will have replaced response with the exception itself.
        c.is_exception_response = getattr(response, "_exception", False)

        if c.response_wrapper and not c.is_exception_response:
            content = flatten_response(response.content)
            wrapped_content = c.response_wrapper(content)
            response.content = wrapped_content

        if c.user_is_loggedin and not c.allow_loggedin_cache:
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Pragma'] = 'no-cache'

        # pagecache stores headers. we need to not add X-Frame-Options to
        # cached requests (such as media embeds) that intend to allow framing.
        if not c.allow_framing and not c.used_cache:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # set some headers related to client security
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # save the result of this page to the pagecache if possible.  we
        # mustn't cache things that rely on state not tracked by request_key
        # such as If-Modified-Since headers for 304s or requesting IP for 429s.
        if (g.page_cache_time
            and request.method.upper() == 'GET'
            and c.can_use_pagecache
            and not c.used_cache
            and response.status_int not in (304, 429)
            and not response.status.startswith("5")
            and not c.is_exception_response):
            try:
                g.pagecache.set(self.request_key(),
                                (response._current_obj(), c.cookies),
                                g.page_cache_time)
            except MemcachedError as e:
                # this codepath will actually never be hit as long as
                # the pagecache memcached client is in no_reply mode.
                g.log.warning("Ignored exception (%r) on pagecache "
                              "write for %r", e, request.path)

        pragmas = [p.strip() for p in
                   request.headers.get("Pragma", "").split(",")]
        if g.debug or "x-reddit-pagecache" in pragmas:
            if c.can_use_pagecache:
                pagecache_state = "hit" if c.used_cache else "miss"
            else:
                pagecache_state = "disallowed"
            response.headers["X-Reddit-Pagecache"] = pagecache_state

        if c.ratelimit_headers:
            response.headers.update(c.ratelimit_headers)

        # send cookies
        for k, v in c.cookies.iteritems():
            if v.dirty:
                response.set_cookie(key=k,
                                    value=quote(v.value),
                                    domain=v.domain,
                                    expires=v.expires,
                                    secure=getattr(v, 'secure', False),
                                    httponly=getattr(v, 'httponly', False))

        if self.should_update_last_visit():
            c.user.update_last_visit(c.start_time)

        hooks.get_hook("reddit.request.end").call()

        # this thread is probably going to be reused, but it could be
        # a while before it is. So we might as well dump the cache in
        # the mean time so that we don't have dead objects hanging
        # around taking up memory
        g.reset_caches()

        c.request_timer.intermediate("post")

        # push data to statsd
        c.request_timer.stop()
        g.stats.flush()

    def on_validation_error(self, error):
        if error.name == errors.USER_REQUIRED:
            self.intermediate_redirect('/login')
        elif error.name == errors.VERIFIED_USER_REQUIRED:
            self.intermediate_redirect('/verify')

    def abort404(self):
        abort(404, "not found")

    def abort403(self):
        abort(403, "forbidden")

    def check_cors(self):
        origin = request.headers.get("Origin")
        if not origin:
            return

        method = request.method
        if method == 'OPTIONS':
            # preflight request
            method = request.headers.get("Access-Control-Request-Method")
            if not method:
                self.abort403()

        action = request.environ["pylons.routes_dict"]["action_name"]

        handler = self._get_action_handler(action, method)
        cors = handler and getattr(handler, "cors_perms", None)

        if cors and cors["origin_check"](origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            if cors.get("allow_credentials"):
                response.headers["Access-Control-Allow-Credentials"] = "true"

    def OPTIONS(self):
        """Return empty responses for CORS preflight requests"""
        self.check_cors()

    def update_qstring(self, dict):
        merged = copy(request.GET)
        merged.update(dict)
        return request.path + utils.query_string(merged)

    def api_wrapper(self, kw):
        data = simplejson.dumps(kw)
        return filters.websafe_json(data)

    def should_update_last_visit(self):
        if g.disallow_db_writes:
            return False

        if not c.user_is_loggedin:
            return False

        if c.update_last_visit is not None:
            return c.update_last_visit

        return request.method.upper() != "POST"


class OAuth2ResourceController(MinimalController):
    defer_ratelimiting = True

    def authenticate_with_token(self):
        set_extension(request.environ, "json")
        set_content_type()
        require_https()
        require_domain(g.oauth_domain)

        try:
            access_token = OAuth2AccessToken.get_token(self._get_bearer_token())
            require(access_token)
            require(access_token.check_valid())
            c.oauth2_access_token = access_token
            account = Account._byID36(access_token.user_id, data=True)
            require(account)
            require(not account._deleted)
            c.user = c.oauth_user = account
            c.user_is_loggedin = True
            c.oauth_client = OAuth2Client._byID(access_token.client_id)
        except RequirementException:
            self._auth_error(401, "invalid_token")

        handler = self._get_action_handler()
        if handler:
            oauth2_perms = getattr(handler, "oauth2_perms", {})
            if oauth2_perms.get("oauth2_allowed", False):
                grant = OAuth2Scope(access_token.scope)
                required = set(oauth2_perms['required_scopes'])
                if not grant.has_access(c.site.name, required):
                    self._auth_error(403, "insufficient_scope")
                c.oauth_scope = grant
            else:
                self._auth_error(400, "invalid_request")

    def check_for_bearer_token(self):
        if self._get_bearer_token(strict=False):
            self.authenticate_with_token()

    def _auth_error(self, code, error):
        abort(code, headers=[("WWW-Authenticate", 'Bearer realm="reddit", error="%s"' % error)])

    def _get_bearer_token(self, strict=True):
        auth = request.headers.get("Authorization")
        if not auth:
            return None
        try:
            auth_scheme, bearer_token = require_split(auth, 2)
            require(auth_scheme.lower() == "bearer")
            return bearer_token
        except RequirementException:
            if strict:
                self._auth_error(400, "invalid_request")
            else:
                return None


class RedditController(OAuth2ResourceController):

    @staticmethod
    def login(user, rem=False):
        # This can't be handled in post() due to PRG and ErrorController fun.
        user.update_last_visit(c.start_time)
        c.cookies[g.login_cookie] = Cookie(value=user.make_cookie(),
                                           expires=NEVER if rem else None,
                                           httponly=True)

    @staticmethod
    def logout():
        c.cookies[g.login_cookie] = Cookie(value='', expires=DELETE)

    @staticmethod
    def enable_admin_mode(user, first_login=None):
        # no expiration time so the cookie dies with the browser session
        admin_cookie = user.make_admin_cookie(first_login=first_login)
        c.cookies[g.admin_cookie] = Cookie(value=admin_cookie, httponly=True)

    @staticmethod
    def remember_otp(user):
        cookie = user.make_otp_cookie()
        expiration = datetime.utcnow() + timedelta(seconds=g.OTP_COOKIE_TTL)
        set_user_cookie(g.otp_cookie,
                        cookie,
                        secure=True,
                        httponly=True,
                        expires=expiration)

    @staticmethod
    def disable_admin_mode(user):
        c.cookies[g.admin_cookie] = Cookie(value='', expires=DELETE)

    def pre(self):
        record_timings = g.admin_cookie in request.cookies or g.debug
        admin_bar_eligible = response.content_type == 'text/html'
        if admin_bar_eligible and record_timings:
            g.stats.start_logging_timings()

        # set up stuff needed in base templates at error time here.
        c.js_preload = JSPreload()

        MinimalController.pre(self)

        set_cnameframe()

        # populate c.cookies unless we're on the unsafe media_domain
        if request.host != g.media_domain or g.media_domain == g.domain:
            cookie_counts = collections.Counter()
            try:
                for k, v in request.cookies.iteritems():
                    # minimalcontroller can still set cookies
                    if k not in c.cookies:
                        # we can unquote even if it's not quoted
                        c.cookies[k] = Cookie(value=unquote(v), dirty=False)
                        cookie_counts[Cookie.classify(k)] += 1
            except CookieError:
                #pylons or one of the associated retarded libraries
                #can't handle broken cookies
                request.environ['HTTP_COOKIE'] = ''

            for cookietype, count in cookie_counts.iteritems():
                g.stats.simple_event("cookie.%s" % cookietype, count)

        delete_obsolete_cookies()

        # the user could have been logged in via one of the feeds 
        maybe_admin = False
        is_otpcookie_valid = False

        self.check_for_bearer_token()

        # no logins for RSS feed unless valid_feed has already been called
        if not c.user:
            if c.extension != "rss":
                authenticate_user()

                admin_cookie = c.cookies.get(g.admin_cookie)
                if c.user_is_loggedin and admin_cookie:
                    maybe_admin, first_login = valid_admin_cookie(admin_cookie.value)

                    if maybe_admin:
                        self.enable_admin_mode(c.user, first_login=first_login)
                    else:
                        self.disable_admin_mode(c.user)

                otp_cookie = read_user_cookie(g.otp_cookie)
                if c.user_is_loggedin and otp_cookie:
                    is_otpcookie_valid = valid_otp_cookie(otp_cookie)

            if not c.user:
                c.user = UnloggedUser(get_browser_langs())
                # patch for fixing mangled language preferences
                if (not isinstance(c.user.pref_lang, basestring) or
                    not all(isinstance(x, basestring)
                            for x in c.user.pref_content_langs)):
                    c.user.pref_lang = g.lang
                    c.user.pref_content_langs = [g.lang]
                    c.user._commit()
        if c.user_is_loggedin:
            if not c.user._loaded:
                c.user._load()
            c.modhash = c.user.modhash()
            if hasattr(c.user, 'msgtime') and c.user.msgtime:
                c.have_messages = c.user.msgtime
            c.have_mod_messages = bool(c.user.modmsgtime)
            c.user_is_admin = maybe_admin and c.user.name in g.admins
            c.user_special_distinguish = c.user.special_distinguish()
            c.user_is_sponsor = c.user_is_admin or c.user.name in g.sponsors
            c.otp_cached = is_otpcookie_valid
            if not isinstance(c.site, FakeSubreddit) and not g.disallow_db_writes:
                c.user.update_sr_activity(c.site)

        c.request_timer.intermediate("base-auth")

        self.run_sitewide_ratelimits()
        c.request_timer.intermediate("base-ratelimits")

        c.over18 = over18()
        set_obey_over18()

        # looking up the multireddit requires c.user.
        set_multireddit()

        #set_browser_langs()
        set_iface_lang()
        set_content_lang()
        set_recent_clicks()
        # used for HTML-lite templates
        set_colors()

        # set some environmental variables in case we hit an abort
        if not isinstance(c.site, FakeSubreddit):
            request.environ['REDDIT_NAME'] = c.site.name

        # random reddit trickery -- have to do this after the content lang is set
        if c.site == Random:
            c.site = Subreddit.random_reddit(user=c.user)
            site_path = c.site.path.strip('/')
            path = "/" + site_path + request.path_qs
            abort(302, location=self.format_output_url(path))
        elif c.site == RandomSubscription:
            if not c.user.gold:
                abort(302, location=self.format_output_url('/gold/about'))
            c.site = Subreddit.random_subscription(c.user)
            site_path = c.site.path.strip('/')
            path = '/' + site_path + request.path_qs
            abort(302, location=self.format_output_url(path))
        elif c.site == RandomNSFW:
            c.site = Subreddit.random_reddit(over18=True, user=c.user)
            site_path = c.site.path.strip('/')
            path = '/' + site_path + request.path_qs
            abort(302, location=self.format_output_url(path))

        if not request.path.startswith("/api/login/"):
            # is the subreddit banned?
            if c.site.spammy() and not c.user_is_admin and not c.error_page:
                ban_info = getattr(c.site, "ban_info", {})
                if "message" in ban_info:
                    message = ban_info['message']
                else:
                    sitelink = url_escape(add_sr("/"))
                    subject = ("/r/%s has been incorrectly banned" %
                                   c.site.name)
                    link = ("/r/redditrequest/submit?url=%s&title=%s" %
                                (sitelink, subject))
                    message = strings.banned_subreddit_message % dict(
                                                                    link=link)
                errpage = pages.RedditError(strings.banned_subreddit_title,
                                            message,
                                            image="subreddit-banned.png")
                request.environ['usable_error_content'] = errpage.render()
                self.abort404()

            # check if the user has access to this subreddit
            if not c.site.can_view(c.user) and not c.error_page:
                if isinstance(c.site, LabeledMulti):
                    # do not leak the existence of multis via 403.
                    self.abort404()
                else:
                    public_description = c.site.public_description
                    errpage = pages.RedditError(
                        strings.private_subreddit_title,
                        strings.private_subreddit_message,
                        image="subreddit-private.png",
                        sr_description=public_description,
                    )
                    request.environ['usable_error_content'] = errpage.render()
                    self.abort403()

            #check over 18
            if (c.site.over_18 and not c.over18 and
                request.path not in ("/frame", "/over18")
                and c.render_style == 'html'):
                return self.intermediate_redirect("/over18", sr_path=False)

        #check whether to allow custom styles
        c.allow_styles = True
        c.can_apply_styles = self.allow_stylesheets
        if g.css_killswitch:
            c.can_apply_styles = False
        #if the preference is set and we're not at a cname
        elif not c.user.pref_show_stylesheets and not c.cname:
            c.can_apply_styles = False
        #if the site has a cname, but we're not using it
        elif c.site.domain and c.site.css_on_cname and not c.cname:
            c.can_apply_styles = False

        c.bare_content = request.GET.pop('bare', False)

        c.show_admin_bar = admin_bar_eligible and (c.user_is_admin or g.debug)
        if not c.show_admin_bar:
            g.stats.end_logging_timings()

        hooks.get_hook("reddit.request.begin").call()

        c.request_timer.intermediate("base-pre")

    def post(self):
        MinimalController.post(self)
        self._embed_html_timing_data()

        # allow logged-out JSON requests to be read cross-domain
        if (request.method.upper() == "GET" and not c.user_is_loggedin and
            c.render_style == "api"):
            response.headers["Access-Control-Allow-Origin"] = "*"

            request_origin = request.headers.get('Origin')
            if request_origin and request_origin != g.origin:
                g.stats.simple_event('cors.api_request')
                g.stats.count_string('origins', request_origin)

    def _embed_html_timing_data(self):
        timings = g.stats.end_logging_timings()

        if not timings or not c.show_admin_bar or c.is_exception_response:
            return

        timings = [{
            "key": timing.key,
            "start": round(timing.start, 4),
            "end": round(timing.end, 4),
        } for timing in timings]

        content = flatten_response(response.content)
        # inject stats script tag at the end of the <body>
        body_parts = list(content.rpartition("</body>"))
        if body_parts[1]:
            script = ('<script type="text/javascript">'
                      'r.timings = %s'
                      '</script>') % simplejson.dumps(timings)
            body_parts.insert(1, script)
            response.content = "".join(body_parts)

    def check_modified(self, thing, action):
        # this is a legacy shim until the old last_modified system is dead
        last_modified = utils.last_modified_date(thing, action)
        return self.abort_if_not_modified(last_modified)

    def abort_if_not_modified(self, last_modified, private=True,
                              max_age=timedelta(0),
                              must_revalidate=True):
        """Check If-Modified-Since and abort(304) if appropriate."""

        if c.user_is_loggedin and not c.allow_loggedin_cache:
            return

        # HTTP timestamps round to nearest second. truncate this value for
        # comparisons.
        last_modified = last_modified.replace(microsecond=0)

        date_str = http_utils.http_date_str(last_modified)
        response.headers['last-modified'] = date_str

        cache_control = []
        if private:
            cache_control.append('private')
        cache_control.append('max-age=%d' % max_age.total_seconds())
        if must_revalidate:
            cache_control.append('must-revalidate')
        response.headers['cache-control'] = ', '.join(cache_control)

        modified_since = request.if_modified_since
        if modified_since and modified_since >= last_modified:
            abort(304, 'not modified')

    def search_fail(self, exception):
        from r2.lib.search import SearchException
        if isinstance(exception, SearchException + (socket.error,)):
            g.log.error("Search Error: %s" % repr(exception))

        errpage = pages.RedditError(_("search failed"),
                                    strings.search_failed)

        request.environ['usable_error_content'] = errpage.render()
        request.environ['retry_after'] = 60
        abort(503)
