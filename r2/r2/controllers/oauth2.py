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

from urllib import urlencode
import base64
import simplejson

from pylons import c, g, request
from pylons.i18n import _
from r2.config.extensions import set_extension
from r2.lib.base import abort
from reddit_base import RedditController, MinimalController, require_https
from r2.lib.db.thing import NotFound
from r2.models import Account
from r2.models.token import (
    OAuth2Client, OAuth2AuthorizationCode, OAuth2AccessToken,
    OAuth2RefreshToken, OAuth2Scope)
from r2.lib.errors import ForbiddenError, errors
from r2.lib.pages import OAuth2AuthorizationPage
from r2.lib.require import RequirementException, require, require_split
from r2.lib.utils import constant_time_compare, parse_http_basic, UrlParser
from r2.lib.validator import (
    nop,
    validate,
    VRequired,
    VThrottledLogin,
    VOneOf,
    VUser,
    VModhash,
    VOAuth2ClientID,
    VOAuth2Scope,
    VOAuth2RefreshToken,
)


def _update_redirect_uri(base_redirect_uri, params):
    parsed = UrlParser(base_redirect_uri)
    parsed.update_query(**params)
    return parsed.unparse()


class OAuth2FrontendController(RedditController):
    def check_for_bearer_token(self):
        pass

    def pre(self):
        RedditController.pre(self)
        require_https()

    def _check_redirect_uri(self, client, redirect_uri):
        if not redirect_uri or not client or redirect_uri != client.redirect_uri:
            abort(ForbiddenError(errors.OAUTH2_INVALID_REDIRECT_URI))

    def _error_response(self, state, redirect_uri):
        """Return an error redirect, but only if client_id and redirect_uri are valid."""

        resp = {"state": state}

        if (errors.OAUTH2_INVALID_CLIENT, "client_id") in c.errors:
            resp["error"] = "unauthorized_client"
        elif (errors.OAUTH2_ACCESS_DENIED, "authorize") in c.errors:
            resp["error"] = "access_denied"
        elif (errors.BAD_HASH, None) in c.errors:
            resp["error"] = "access_denied"
        elif (errors.INVALID_OPTION, "response_type") in c.errors:
            resp["error"] = "unsupported_response_type"
        elif (errors.OAUTH2_INVALID_SCOPE, "scope") in c.errors:
            resp["error"] = "invalid_scope"
        else:
            resp["error"] = "invalid_request"

        final_redirect = _update_redirect_uri(redirect_uri, resp)
        return self.redirect(final_redirect, code=302)

    @validate(VUser(),
              response_type = VOneOf("response_type", ("code",)),
              client = VOAuth2ClientID(),
              redirect_uri = VRequired("redirect_uri", errors.OAUTH2_INVALID_REDIRECT_URI),
              scope = VOAuth2Scope(),
              state = VRequired("state", errors.NO_TEXT),
              duration = VOneOf("duration", ("temporary", "permanent"),
                                default="temporary"))
    def GET_authorize(self, response_type, client, redirect_uri, scope, state,
                      duration):
        """
        First step in [OAuth 2.0](http://oauth.net/2/) authentication.
        End users will be prompted for their credentials (username/password)
        and asked if they wish to authorize the application identified by
        the **client_id** parameter with the permissions specified by the
        **scope** parameter.  They are then redirected to the endpoint on
        the client application's side specified by **redirect_uri**.

        If the user granted permission to the application, the response will
        contain a **code** parameter with a temporary authorization code
        which can be exchanged for an access token at
        [/api/v1/access_token](#api_method_access_token).

        **redirect_uri** must match the URI configured for the client in the
        [app preferences](/prefs/apps).  If **client_id** or **redirect_uri**
        is not valid, or if the call does not take place over SSL, a 403
        error will be returned.  For all other errors, a redirect to
        **redirect_uri** will be returned, with a **error** parameter
        indicating why the request failed.
        """

        self._check_redirect_uri(client, redirect_uri)

        if not c.errors:
            return OAuth2AuthorizationPage(client, redirect_uri, scope, state,
                                           duration).render()
        else:
            return self._error_response(state, redirect_uri)

    @validate(VUser(),
              VModhash(fatal=False),
              client = VOAuth2ClientID(),
              redirect_uri = VRequired("redirect_uri", errors.OAUTH2_INVALID_REDIRECT_URI),
              scope = VOAuth2Scope(),
              state = VRequired("state", errors.NO_TEXT),
              duration = VOneOf("duration", ("temporary", "permanent"),
                                default="temporary"),
              authorize = VRequired("authorize", errors.OAUTH2_ACCESS_DENIED))
    def POST_authorize(self, authorize, client, redirect_uri, scope, state,
                       duration):
        """Endpoint for OAuth2 authorization."""

        self._check_redirect_uri(client, redirect_uri)

        if not c.errors:
            code = OAuth2AuthorizationCode._new(client._id, redirect_uri,
                                                c.user._id36, scope,
                                                duration == "permanent")
            resp = {"code": code._id, "state": state}
            final_redirect = _update_redirect_uri(redirect_uri, resp)
            return self.redirect(final_redirect, code=302)
        else:
            return self._error_response(state, redirect_uri)

class OAuth2AccessController(MinimalController):
    def pre(self):
        set_extension(request.environ, "json")
        MinimalController.pre(self)
        require_https()
        c.oauth2_client = self._get_client_auth()

    def _get_client_auth(self):
        auth = request.headers.get("Authorization")
        try:
            client_id, client_secret = parse_http_basic(auth)
            client = OAuth2Client.get_token(client_id)
            require(client)
            require(constant_time_compare(client.secret, client_secret))
            return client
        except RequirementException:
            abort(401, headers=[("WWW-Authenticate", 'Basic realm="reddit"')])

    @validate(grant_type=VOneOf("grant_type",
                                ("authorization_code",
                                 "refresh_token",
                                 "password")))
    def POST_access_token(self, grant_type):
        """
        Exchange an [OAuth 2.0](http://oauth.net/2/) authorization code
        or refresh token (from [/api/v1/authorize](#api_method_authorize)) for
        an access token.

        On success, returns a URL-encoded dictionary containing
        **access_token**, **token_type**, **expires_in**, and **scope**.
        If an authorization code for a permanent grant was given, a
        **refresh_token** will be included. If there is a problem, an **error**
        parameter will be returned instead.

        Must be called using SSL, and must contain a HTTP `Authorization:`
        header which contains the application's client identifier as the
        username and client secret as the password.  (The client id and secret
        are visible on the [app preferences page](/prefs/apps).)

        Per the OAuth specification, **grant_type** must
        be ``authorization_code`` for the initial access token or
        ``refresh_token`` for renewing the access token.

        **redirect_uri** must exactly match the value that was used in the call
        to [/api/v1/authorize](#api_method_authorize) that created this grant.
        """

        if grant_type == "authorization_code":
            return self._access_token_code()
        elif grant_type == "refresh_token":
            return self._access_token_refresh()
        elif grant_type == "password":
            return self._access_token_password()
        else:
            resp = {"error": "unsupported_grant_type"}
            return self.api_wrapper(resp)

    def _check_for_errors(self):
        resp = {}
        if (errors.INVALID_OPTION, "scope") in c.errors:
            resp["error"] = "invalid_scope"
        else:
            resp["error"] = "invalid_request"
        return resp

    def _make_token_dict(self, access_token, refresh_token=None):
        if not access_token:
            return {"error": "invalid_grant"}
        expires_in = int(access_token._ttl) if access_token._ttl else None
        resp = {
            "access_token": access_token._id,
            "token_type": access_token.token_type,
            "expires_in": expires_in,
            "scope": access_token.scope,
        }
        if refresh_token:
            resp["refresh_token"] = refresh_token._id
        return resp

    @validate(code=nop("code"),
              redirect_uri=VRequired("redirect_uri",
                                     errors.OAUTH2_INVALID_REDIRECT_URI))
    def _access_token_code(self, code, redirect_uri):
        if not code:
            c.errors.add("NO_TEXT", field="code")
        if c.errors:
            return self.api_wrapper(self._check_for_errors())

        access_token = None
        refresh_token = None

        auth_token = OAuth2AuthorizationCode.use_token(
            code, c.oauth2_client._id, redirect_uri)
        if auth_token:
            if auth_token.refreshable:
                refresh_token = OAuth2RefreshToken._new(
                    auth_token.client_id, auth_token.user_id,
                    auth_token.scope)
            access_token = OAuth2AccessToken._new(
                auth_token.client_id, auth_token.user_id,
                auth_token.scope,
                refresh_token._id if refresh_token else None)

        resp = self._make_token_dict(access_token, refresh_token)

        return self.api_wrapper(resp)

    @validate(refresh_token=VOAuth2RefreshToken("refresh_token"))
    def _access_token_refresh(self, refresh_token):
        resp = {}
        access_token = None
        if refresh_token:
            access_token = OAuth2AccessToken._new(
                refresh_token.client_id, refresh_token.user_id,
                refresh_token.scope,
                refresh_token=refresh_token._id)
        else:
            c.errors.add("NO_TEXT", field="refresh_token")

        if c.errors:
            resp = self._check_for_errors()
        else:
            resp = self._make_token_dict(access_token)
        return self.api_wrapper(resp)

    @validate(user=VThrottledLogin(["username", "password"]),
              scope=nop("scope"))
    def _access_token_password(self, user, scope):
        # username:password auth via OAuth is only allowed for
        # private use scripts
        client = c.oauth2_client
        if client.app_type != "script":
            return self.api_wrapper({"error": "unauthorized_client",
                "error_description": "Only script apps may use password auth"})
        dev_ids = client._developer_ids
        if not user or user._id not in dev_ids:
            return self.api_wrapper({"error": "invalid_grant"})
        if c.errors:
            return self.api_wrapper(self._check_for_errors())

        if scope:
            scope = OAuth2Scope(scope)
            if not scope.is_valid():
                c.errors.add(errors.INVALID_OPTION, "scope")
                return self.api_wrapper({"error": "invalid_scope"})
        else:
            scope = OAuth2Scope(OAuth2Scope.FULL_ACCESS)

        access_token = OAuth2AccessToken._new(
                client._id,
                user._id36,
                scope
        )
        resp = self._make_token_dict(access_token)
        return self.api_wrapper(resp)


def require_oauth2_scope(*scopes):
    def oauth2_scope_wrap(fn):
        fn.oauth2_perms = {"required_scopes": scopes, "oauth2_allowed": True}
        return fn
    return oauth2_scope_wrap


def allow_oauth2_access(fn):
    fn.oauth2_perms = {"required_scopes": [], "oauth2_allowed": True}
    return fn
