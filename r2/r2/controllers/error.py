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
import os.path
from mako.filters import url_escape

import paste.fileapp
from pylons.middleware import error_document_template, media_path
from pylons import c, request, g
from pylons.i18n import _
import random as rand
from r2.lib.filters import safemarkdown, unsafe

try:
    # place all r2 specific imports in here.  If there is a code error, it'll get caught and
    # the stack trace won't be presented to the user in production
    from reddit_base import RedditController, Cookies
    from r2.models.subreddit import DefaultSR, Subreddit
    from r2.models.link import Link
    from r2.lib import pages
    from r2.lib.strings import strings, rand_strings
except Exception, e:
    if g.debug:
        # if debug mode, let the error filter up to pylons to be handled
        raise e
    else:
        # production environment: protect the code integrity!
        print "HuffmanEncodingError: make sure your python compiles before deploying, stupid!"
        # kill this app
        import os
        os._exit(1)

NUM_FAILIENS = 3

redditbroke =  \
'''<html>
  <head>
    <title>reddit broke!</title>
  </head>
  <body>
    <div style="margin: auto; text-align: center">
      <p>
        <a href="/">
          <img border="0" src="/static/youbrokeit%d.png" alt="you broke reddit" />
        </a>
      </p>
      <p>
        %s
      </p>
  </body>
</html>
'''

toofast =  \
'''<html>
  <head><title>service temporarily unavailable</title></head>
  <body>
    the service you request is temporarily unavailable. please try again later.
  </body>
</html>
'''            

class ErrorController(RedditController):
    """Generates error documents as and when they are required.

    The ErrorDocuments middleware forwards to ErrorController when error
    related status codes are returned from the application.

    This behaviour can be altered by changing the parameters to the
    ErrorDocuments middleware in your config/middleware.py file.
    """
    allowed_render_styles = ('html', 'xml', 'js', 'embed', '', "compact", 'api')
    # List of admins to blame (skip the first admin, "reddit")
    # If list is empty, just blame "an admin"
    admins = g.admins[1:] or ["an admin"]
    def __before__(self):
        try:
            c.error_page = True
            RedditController.__before__(self)
        except:
            handle_awful_failure("Error occurred in ErrorController.__before__")

    def __after__(self): 
        try:
            RedditController.__after__(self)
        except:
            handle_awful_failure("Error occurred in ErrorController.__after__")

    def __call__(self, environ, start_response):
        try:
            return RedditController.__call__(self, environ, start_response)
        except:
            return handle_awful_failure("something really awful just happened.")


    def send403(self):
        c.response.status_code = 403
        c.site = DefaultSR()
        res = pages.RedditError(_("forbidden (%(domain)s)") %
                                dict(domain=g.domain))
        return res.render()

    def send404(self):
        c.response.status_code = 404
        if 'usable_error_content' in request.environ:
            return request.environ['usable_error_content']
        if c.site.spammy() and not c.user_is_admin:
            ban_info = getattr(c.site, "ban_info", {})
            if "message" in ban_info:
                message = ban_info["message"]
            else:
                subject = ("the subreddit /r/%s has been incorrectly banned" %
                           c.site.name)
                lnk = ("/r/redditrequest/submit?url=%s&title=%s"
                       % (url_escape("http://%s/r/%s" % (g.domain, c.site.name)),
                          ("the subreddit /r/%s has been incorrectly banned" %
                           c.site.name)))
                message = strings.banned_subreddit % dict(link = lnk)

            res = pages.RedditError(_('this reddit has been banned'),
                                    unsafe(safemarkdown(message)))
            return res.render()
        else:
            return pages.Reddit404().render()

    def send503(self):
        c.response.status_code = 503
        if 'retry_after' in request.environ:
            c.response.headers['Retry-After'] = request.environ['retry_after']
        else:
            c.response.headers['Retry-After'] = 1

        if 'usable_error_content' in request.environ:
            return request.environ['usable_error_content']
        else:
            c.response.content = toofast
            return c.response

    def GET_document(self):
        try:
            # clear cookies the old fashioned way 
            c.cookies = Cookies()

            code =  request.GET.get('code', '')
            try:
                code = int(code)
            except ValueError:
                code = 404
            srname = request.GET.get('srname', '')
            takedown = request.GET.get('takedown', "")
            
            if srname:
                c.site = Subreddit._by_name(srname)
            if c.render_style not in self.allowed_render_styles:
                if code not in (204, 304):
                     c.response.content = str(code)
                return c.response
            elif c.render_style == "api":
                c.response.content = "{error: %s}" % code
                return c.response
            elif takedown and code == 404:
                link = Link._by_fullname(takedown)
                return pages.TakedownPage(link).render()
            elif code == 403:
                return self.send403()
            elif code == 500:
                randmin = {'admin': rand.choice(self.admins)}
                return redditbroke % (rand.randint(1,NUM_FAILIENS), rand_strings.sadmessages % randmin)
            elif code == 503:
                return self.send503()
            elif code == 304:
                if request.GET.has_key('x-sup-id'):
                    x_sup_id = request.GET.get('x-sup-id')
                    if '\r\n' not in x_sup_id:
                        c.response.headers['x-sup-id'] = x_sup_id
                return c.response
            elif c.site:
                return self.send404()
            else:
                return "page not found"
        except:
            return handle_awful_failure("something really bad just happened.")

    POST_document = GET_document

def handle_awful_failure(fail_text):
    """
    Makes sure that no errors generated in the error handler percolate
    up to the user unless debug is enabled.
    """
    if g.debug:
        import sys
        s = sys.exc_info()
        # reraise the original error with the original stack trace
        raise s[1], None, s[2]
    try:
        # log the traceback, and flag the "path" as the error location
        import traceback
        g.log.error("FULLPATH: %s" % fail_text)
        g.log.error(traceback.format_exc())
        return redditbroke % (rand.randint(1,NUM_FAILIENS), fail_text)
    except:
        # we are doomed.  Admit defeat
        return "This is an error that should never occur.  You win."
