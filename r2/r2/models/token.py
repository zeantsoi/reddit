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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import datetime
import functools
from os import urandom
from base64 import urlsafe_b64encode

from pycassa.system_manager import ASCII_TYPE, DATE_TYPE, UTF8_TYPE

from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons.i18n import _

from r2.lib import hooks, ratelimit
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import NotFound
from r2.models.account import Account, valid_password


def generate_token(size):
    return urlsafe_b64encode(urandom(size)).rstrip("=")


class Token(tdb_cassandra.Thing):
    """A unique randomly-generated token used for authentication."""

    _extra_schema_creation_args = dict(
        key_validation_class=ASCII_TYPE,
        default_validation_class=UTF8_TYPE,
        column_validation_classes=dict(
            date=DATE_TYPE,
            used=ASCII_TYPE
        )
    )

    @classmethod
    def _new(cls, **kwargs):
        if "_id" not in kwargs:
            kwargs["_id"] = cls._generate_unique_token()

        token = cls(**kwargs)

        token._commit()
        return token

    @classmethod
    def _generate_unique_token(cls):
        for i in range(3):
            token = generate_token(cls.token_size)
            try:
                cls._byID(token)
            except tdb_cassandra.NotFound:
                return token
            else:
                continue
        raise ValueError

    @classmethod
    def get_token(cls, _id):
        if _id is None:
            return None
        try:
            return cls._byID(_id)
        except tdb_cassandra.NotFound:
            return None


class ConsumableToken(Token):
    _defaults = dict(used=False)
    _bool_props = ("used",)
    _warn_on_partial_ttl = False

    @classmethod
    def get_token(cls, _id):
        token = super(ConsumableToken, cls).get_token(_id)
        if token and not token.used:
            return token
        else:
            return None

    def consume(self):
        self.used = True
        self._commit()

    def make_token_url(self, relative=False):
        if not hasattr(self, 'path'):
            raise TypeError

        return "{prefix}/{path}/{token_id}".format(
            prefix="" if relative else (g.https_endpoint or g.origin),
            path=self.path.strip("/"),
            token_id=self._id,
        )


class OAuth2Scope:
    scope_info = {
        None: {
            "id": None,
            "name": _("Any Scope"),
            "description": _("Endpoint is accessible with any combination "
                "of other OAuth 2 scopes."),
        },
        "account": {
            "id": "account",
            "name": _("Update account information"),
            "description": _("Update preferences and related account "
                "information. Will not have access to your email or "
                "password."),
        },
        "creddits": {
            "id": "creddits",
            "name": _("Spend reddit gold creddits"),
            "description": _("Spend my reddit gold creddits on giving "
                "gold to other users."),
        },
        "edit": {
            "id": "edit",
            "name": _("Edit Posts"),
            "description": _("Edit and delete my comments and submissions."),
        },
        "flair": {
            "id": "flair",
            "name": _("Manage My Flair"),
            "description": _("Select my subreddit flair. "
                             "Change link flair on my submissions."),
        },
        "history": {
            "id": "history",
            "name": _("History"),
            "description": _(
                "Access my voting history and comments or submissions I've"
                " saved or hidden."),
        },
        "identity": {
            "id": "identity",
            "name": _("My Identity"),
            "description": _("Access my reddit username and signup date."),
        },
        "modcontributors": {
            "id": "modcontributors",
            "name": _("Approve submitters and ban users"),
            "description": _(
                "Add/remove users to approved submitter lists and "
                "ban/unban or mute/unmute users from subreddits I moderate."
            ),
        },
        "modflair": {
            "id": "modflair",
            "name": _("Moderate Flair"),
            "description": _(
                "Manage and assign flair in subreddits I moderate."),
        },
        "modmail": {
            "id": "modmail",
            "name": _("New Modmail"),
            "description": _(
                "Access and manage modmail via mod.reddit.com."),
        },
        "modposts": {
            "id": "modposts",
            "name": _("Moderate Posts"),
            "description": _(
                "Approve, remove, mark nsfw, and distinguish content"
                " in subreddits I moderate."),
        },
        "modconfig": {
            "id": "modconfig",
            "name": _("Moderate Subreddit Configuration"),
            "description": _(
                "Manage the configuration, sidebar, and CSS"
                " of subreddits I moderate."),
        },
        "modlog": {
            "id": "modlog",
            "name": _("Moderation Log"),
            "description": _(
                "Access the moderation log in subreddits I moderate."),
        },
        "modothers": {
            "id": "modothers",
            "name": _("Invite or remove other moderators"),
            "description": _(
                "Invite or remove other moderators from subreddits I moderate."
            ),
        },
        "modself": {
            "id": "modself",
            "name": _("Make changes to your subreddit moderator "
                      "and contributor status"),
            "description": _(
                "Accept invitations to moderate a subreddit. Remove myself as "
                "a moderator or contributor of subreddits I moderate or "
                "contribute to."
            ),
        },
        "modtraffic": {
            "id": "modtraffic",
            "name": _("Subreddit Traffic"),
            "description": _("Access traffic stats in subreddits I moderate."),
        },
        "modwiki": {
            "id": "modwiki",
            "name": _("Moderate Wiki"),
            "description": _(
                "Change editors and visibility of wiki pages"
                " in subreddits I moderate."),
        },
        "mysubreddits": {
            "id": "mysubreddits",
            "name": _("My Subreddits"),
            "description": _(
                "Access the list of subreddits I moderate, contribute to,"
                " and subscribe to."),
        },
        "privatemessages": {
            "id": "privatemessages",
            "name": _("Private Messages"),
            "description": _(
                "Access my inbox and send private messages to other users."),
        },
        "read": {
            "id": "read",
            "name": _("Read Content"),
            "description": _("Access posts and comments through my account."),
        },
        "report": {
            "id": "report",
            "name": _("Report content"),
            "description": _("Report content for rules violations. "
                             "Hide & show individual submissions."),
        },
        "save": {
            "id": "save",
            "name": _("Save Content"),
            "description": _("Save and unsave comments and submissions."),
        },
        "submit": {
            "id": "submit",
            "name": _("Submit Content"),
            "description": _("Submit links and comments from my account."),
        },
        "subscribe": {
            "id": "subscribe",
            "name": _("Edit My Subscriptions"),
            "description": _('Manage my subreddit subscriptions. Manage '
                '"friends" - users whose content I follow.'),
        },
        "vote": {
            "id": "vote",
            "name": _("Vote"),
            "description":
                _("Submit and change my votes on comments and submissions."),
        },
        "wikiedit": {
            "id": "wiki",
            "name": _("Wiki Editing"),
            "description": _("Edit wiki pages on my behalf"),
        },
        "wikiread": {
            "id": "wikiread",
            "name": _("Read Wiki Pages"),
            "description": _("Read wiki pages through my account"),
        },
    }

    # Special scope, granted implicitly to clients with app_type == "script"
    FULL_ACCESS = "*"

    class InsufficientScopeError(StandardError):
        pass

    def __init__(self, scope_str=None, subreddits=None, scopes=None):
        if scope_str:
            self._parse_scope_str(scope_str)
        elif subreddits is not None or scopes is not None:
            self.subreddit_only = bool(subreddits)
            self.subreddits = subreddits
            self.scopes = scopes
        else:
            self.subreddit_only = False
            self.subreddits = set()
            self.scopes = set()

    def _parse_scope_str(self, scope_str):
        srs, sep, scopes = scope_str.rpartition(':')
        if sep:
            self.subreddit_only = True
            self.subreddits = set(srs.split('+'))
        else:
            self.subreddit_only = False
            self.subreddits = set()
        self.scopes = set(scopes.replace(',', ' ').split(' '))

    def __str__(self):
        if self.subreddit_only:
            sr_part = '+'.join(sorted(self.subreddits)) + ':'
        else:
            sr_part = ''
        return sr_part + ' '.join(sorted(self.scopes))

    def has_access(self, subreddit, required_scopes):
        if self.FULL_ACCESS in self.scopes:
            return True
        if self.subreddit_only and subreddit not in self.subreddits:
            return False
        return (self.scopes >= required_scopes)

    def has_any_scope(self, required_scopes):
        if self.FULL_ACCESS in self.scopes:
            return True

        return bool(self.scopes & required_scopes)

    def is_valid(self):
        return all(scope in self.scope_info for scope in self.scopes)

    def details(self):
        if self.FULL_ACCESS in self.scopes:
            scopes = self.scope_info.keys()
        else:
            scopes = self.scopes
        return [(scope, self.scope_info[scope]) for scope in scopes]

    @classmethod
    def merge_scopes(cls, scopes):
        """Return a by-subreddit dict representing merged OAuth2Scopes.

        Takes an iterable of OAuth2Scopes. For each of those,
        if it defines scopes on multiple subreddits, it is split
        into one OAuth2Scope per subreddit. If multiple passed in
        OAuth2Scopes reference the same scopes, they'll be combined.

        """
        merged = {}
        for scope in scopes:
            srs = scope.subreddits if scope.subreddit_only else (None,)
            for sr in srs:
                if sr in merged:
                    merged[sr].scopes.update(scope.scopes)
                else:
                    new_scope = cls()
                    new_scope.subreddits = {sr}
                    new_scope.scopes = scope.scopes
                    if sr is not None:
                        new_scope.subreddit_only = True
                    merged[sr] = new_scope
        return merged


def extra_oauth2_scope(*scopes):
    """Wrap a function so that it only returns data if user has all `scopes`

    When not in an OAuth2 context, function returns normally.
    In an OAuth2 context, the function will not be run unless the user
    has granted all scopes required of this function. Instead, the function
    will raise an OAuth2Scope.InsufficientScopeError.

    """
    def extra_oauth2_wrapper(fn):
        @functools.wraps(fn)
        def wrapper_fn(*a, **kw):
            if not c.oauth_user:
                # Not in an OAuth2 context, run function normally
                return fn(*a, **kw)
            elif c.oauth_scope.has_access(c.site.name, set(scopes)):
                # In an OAuth2 context, and have scope for this function
                return fn(*a, **kw)
            else:
                # In an OAuth2 context, but don't have scope
                raise OAuth2Scope.InsufficientScopeError(scopes)
        return wrapper_fn
    return extra_oauth2_wrapper


class OAuth2Client(Token):
    """A client registered for OAuth2 access"""
    max_developers = 20
    token_size = 10
    client_secret_size = 20
    _float_props = (
        "max_reqs_sec",
    )
    _int_props = (
        "access_token_ttl",
    )
    _defaults = dict(name="",
                     description="",
                     about_url="",
                     icon_url="",
                     secret="",
                     redirect_uri="",
                     app_type="web",
                     max_reqs_sec=g.RL_OAUTH_AVG_REQ_PER_SEC,
                    )
    _use_db = True
    _connection_pool = "main"

    _developer_colname_prefix = 'has_developer_'

    APP_TYPES = ("web", "installed", "script")
    PUBLIC_APP_TYPES = ("installed",)

    @classmethod
    def _new(cls, **kwargs):
        if "secret" not in kwargs:
            kwargs["secret"] = generate_token(cls.client_secret_size)
        return super(OAuth2Client, cls)._new(**kwargs)

    @property
    def _developer_ids(self):
        for k, v in self._t.iteritems():
            if k.startswith(self._developer_colname_prefix) and v:
                try:
                    yield int(k[len(self._developer_colname_prefix):], 36)
                except ValueError:
                    pass

    @property
    def _max_reqs(self):
        return self.max_reqs_sec * g.RL_OAUTH_RESET_SECONDS

    @property
    def _developers(self):
        """Returns a list of users who are developers of this client."""

        devs = Account._byID(list(self._developer_ids), return_dict=False)
        return [dev for dev in devs if not dev._deleted]

    def _developer_colname(self, account):
        """Developer access is granted by way of adding a column with the
        account's ID36 to the client object.  This function returns the
        column name for a given Account.
        """

        return ''.join((self._developer_colname_prefix, account._id36))

    def has_developer(self, account):
        """Returns a boolean indicating whether or not the supplied Account is a developer of this application."""

        if account._deleted:
            return False
        else:
            return getattr(self, self._developer_colname(account), False)

    def add_developer(self, account, force=False):
        """Grants developer access to the supplied Account."""

        dev_ids = set(self._developer_ids)
        if account._id not in dev_ids:
            if not force and len(dev_ids) >= self.max_developers:
                raise OverflowError('max developers reached')
            setattr(self, self._developer_colname(account), True)
            self._commit()

        # Also update index
        OAuth2ClientsByDeveloper._set_values(account._id36, {self._id: ''})

    def remove_developer(self, account):
        """Revokes the supplied Account's developer access."""

        if hasattr(self, self._developer_colname(account)):
            del self[self._developer_colname(account)]
            if not len(self._developers):
                # No developers remain, delete the client
                self.deleted = True
            self._commit()

        # Also update index
        try:
            cba = OAuth2ClientsByDeveloper._byID(account._id36)
            del cba[self._id]
        except (tdb_cassandra.NotFound, KeyError):
            pass
        else:
            cba._commit()

    @classmethod
    def _by_developer(cls, account):
        """Returns a (possibly empty) list of clients for which Account is a developer."""

        if account._deleted:
            return []

        try:
            cba = OAuth2ClientsByDeveloper._byID(account._id36)
        except tdb_cassandra.NotFound:
            return []

        clients = cls._byID(cba._values().keys())
        return [client for client in clients.itervalues()
                if not getattr(client, 'deleted', False)
                    and client.has_developer(account)]

    @classmethod
    def _by_user(cls, account):
        """Return a (possibly empty) list of client-token tuples for
        which Account has outstanding access tokens.
        """

        refresh_tokens = {
            token._id: token for token in OAuth2RefreshToken._by_user(account)
            if token.check_valid()}
        access_tokens = [token for token in OAuth2AccessToken._by_user(account)
                         if token.check_valid()]

        tokens = refresh_tokens.values()
        tokens.extend(token for token in access_tokens
                      if token.refresh_token not in refresh_tokens)

        clients = cls._byID([token.client_id for token in tokens])
        return [(clients[token.client_id], token)
                for token in tokens]

    @classmethod
    def _by_user_grouped(cls, account):
        token_tuples = cls._by_user(account)
        clients = {}
        for client, token in token_tuples:
            scope = OAuth2Scope(token.scope)
            if client._id in clients:
                client_data = clients[client._id]
                client_data['scopes'].append(scope)
            else:
                client_data = {'scopes': [scope], 'access_tokens': 0,
                               'refresh_tokens': 0, 'client': client}
                clients[client._id] = client_data
            if isinstance(token, OAuth2AccessToken):
                client_data['access_tokens'] += 1
            elif isinstance(token, OAuth2RefreshToken):
                client_data['refresh_tokens'] += 1

        for client_data in clients.itervalues():
            client_data['scopes'] = OAuth2Scope.merge_scopes(
                client_data['scopes'],
            )

        return clients

    def revoke(self, account):
        """Revoke all of the outstanding OAuth2AccessTokens for Account."""
        for token in OAuth2RefreshToken._by_user(account):
            if token.client_id == self._id:
                token.revoke()
        for token in OAuth2AccessToken._by_user(account):
            if token.client_id == self._id:
                token.revoke()

    def is_confidential(self):
        return self.app_type not in self.PUBLIC_APP_TYPES

    def is_first_party(self):
        return self.has_developer(Account.system_user())


class OAuth2ClientsByDeveloper(tdb_cassandra.View):
    """Index providing access to clients of which Account is a developer."""

    _use_db = True
    _type_prefix = 'OAuth2ClientsByDeveloper'
    _view_of = OAuth2Client
    _connection_pool = 'main'


class OAuth2AuthorizationCode(ConsumableToken):
    """An OAuth2 authorization code for completing authorization flow"""
    token_size = 20
    _ttl = datetime.timedelta(minutes=10)
    _defaults = dict(ConsumableToken._defaults.items() + [
                         ("client_id", ""),
                         ("redirect_uri", ""),
                         ("scope", ""),
                         ("refreshable", False)])
    _bool_props = ConsumableToken._bool_props + ("refreshable",)
    _warn_on_partial_ttl = False
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, client_id, redirect_uri, user_id, scope, refreshable):
        return super(OAuth2AuthorizationCode, cls)._new(
                client_id=client_id,
                redirect_uri=redirect_uri,
                user_id=user_id,
                scope=str(scope),
                refreshable=refreshable,
            )

    @classmethod
    def use_token(cls, _id, client_id, redirect_uri):
        token = cls.get_token(_id)
        if token and (token.client_id == client_id and
                      token.redirect_uri == redirect_uri):
            token.consume()
            return token
        else:
            return None


class BaseOAuth2Token(Token):
    token_size = 20
    _ttl = None
    _use_db = False
    _connection_pool = "main"

    _defaults = dict(
        scope="",
        token_type="bearer",
        user_id="",
        device_id="",
    )

    @classmethod
    def _new(cls, client_id, user_id, scope, device_id=None, **kwargs):
        try:
            user_id_prefix = int(user_id, 36)
        except (ValueError, TypeError):
            user_id_prefix = ""
        _id = "%s-%s" % (user_id_prefix, cls._generate_unique_token())

        return super(BaseOAuth2Token, cls)._new(
            _id=_id,
            client_id=client_id,
            user_id=user_id,
            scope=str(scope),
            device_id=device_id,
            **kwargs
        )

    @classmethod
    def _by_user_view(cls):
        raise NotImplementedError

    def _on_create(self):
        if self.user_id:
            self._by_user_view()._set_values(str(self.user_id), {self._id: ''})

    def check_valid(self):
        if getattr(self, 'revoked', False):
            return False

        try:
            client = OAuth2Client._byID(self.client_id)
            if getattr(client, 'deleted', False):
                raise NotFound
        except AttributeError:
            g.log.error("bad token %s: %s", self, self._t)
            raise
        except NotFound:
            return False

        if self.user_id:
            try:
                account = Account._byID36(self.user_id)
                if account._deleted:
                    raise NotFound
            except NotFound:
                return False

        return True

    def revoke(self):
        self.revoked = True
        self._commit()

        if self.user_id:
            try:
                user_tokens = self._by_user_view()._byID(self.user_id)
                del user_tokens[self._id]
            except (tdb_cassandra.NotFound, KeyError):
                pass
            else:
                user_tokens._commit()

        hooks.get_hook("oauth2.revoke_token").call(token=self)

    @classmethod
    def revoke_all_by_user(cls, account):
        user_tokens = cls._by_user(account)
        for token in user_tokens:
            token.revoke()

    @classmethod
    def _by_user(cls, account):
        try:
            user_tokens = cls._by_user_view()._byID(account._id36)
        except tdb_cassandra.NotFound:
            return []

        tokens = cls._byID(user_tokens._values().keys())
        return [token for token in tokens.itervalues() if token.check_valid()]


class OAuth2AccessToken(BaseOAuth2Token):
    """An OAuth2 access token for accessing protected resources."""

    _ttl = g.default_access_token_ttl
    _defaults = dict(BaseOAuth2Token._defaults.items() + [
        ('refresh_token', ''),
    ])
    _int_props = (
        'token_ttl',
    )
    _use_db = True

    @classmethod
    def _new(cls, client_id, user_id, scope, refresh_token=None,
             device_id=None):

        ttl = cls._determine_ttl(client_id)

        token = cls(
            _id=cls._generate_unique_token(),
            client_id=client_id,
            user_id=user_id,
            scope=str(scope),
            refresh_token=refresh_token,
            device_id=device_id,
            token_ttl=ttl,
        )

        token._commit(ttl=ttl)
        return token

    @classmethod
    def _by_user_view(cls):
        return OAuth2AccessTokensByUser

    def _on_create(self):
        """Update the by-user view upon creation."""
        if self.user_id:
            self._by_user_view()._set_values(
                str(self.user_id),
                {self._id: ''},
                ttl=self.token_ttl,
            )

    @classmethod
    def _determine_ttl(cls, client_id):
        client = OAuth2Client._byID(client_id)

        try:
            return client.access_token_ttl
        except AttributeError:
            pass

        return cls._ttl


class OAuth2AccessTokensByUser(tdb_cassandra.View):
    """Index listing the outstanding access tokens for an account."""

    _use_db = True
    _ttl = OAuth2AccessToken._ttl
    _type_prefix = 'OAuth2AccessTokensByUser'
    _view_of = OAuth2AccessToken
    _connection_pool = 'main'


class OAuth2RefreshToken(BaseOAuth2Token):
    """A refresh token for obtaining new access tokens for the same grant."""

    _use_db = True

    @classmethod
    def _by_user_view(cls):
        return OAuth2RefreshTokensByUser

    def revoke(self):
        super(OAuth2RefreshToken, self).revoke()
        account = Account._byID36(self.user_id)
        access_tokens = OAuth2AccessToken._by_user(account)
        for token in access_tokens:
            if token.refresh_token == self._id:
                token.revoke()


class OAuth2RefreshTokensByUser(tdb_cassandra.View):
    """Index listing the outstanding refresh tokens for an account."""

    _use_db = True
    _ttl = OAuth2RefreshToken._ttl
    _type_prefix = 'OAuth2RefreshTokensByUser'
    _view_of = OAuth2RefreshToken
    _connection_pool = 'main'


class EmailVerificationToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(hours=12)
    token_size = 20

    @classmethod
    def _new(cls, user):
        return super(EmailVerificationToken, cls)._new(user_id=user._fullname,
                                                       email=user.email)

    def valid_for_user(self, user):
        return self.email == user.email


class OrangeredOptInToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(days=180)
    token_size = 20

    @classmethod
    def _new(cls, user):
        return super(OrangeredOptInToken, cls)._new(user_id=user._fullname,
                                                    email=user.email)

    def valid_for_user(self, user):
        return (self.email == user.email and
            self.user_id == user._fullname)


class PasswordResetToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(hours=12)
    token_size = 20
    path = "/resetpassword/"

    @classmethod
    def _new(cls, user):
        user.add_note("Issued password reset token.")
        return super(PasswordResetToken, cls)._new(user_id=user._fullname,
                                                   email_address=user.email,
                                                   password=user.password)

    def valid_for_user(self, user):
        return (self.email_address == user.email and
                self.password == user.password)


class AccountRecoveryToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(hours=24)
    token_size = 20
    path = "/accountrecovery/"

    @classmethod
    def _new(cls, user):
        user.add_note("Issued account recovery token.")
        return super(AccountRecoveryToken, cls)._new(user_id=user._fullname,
                                                     email_address=user.email,
                                                     password=user.password)

    def valid_for_credentials(self, email, password):
        user = Account._by_fullname(self.user_id)
        return (self.email_address.lower() == email.lower() and
                valid_password(user, password, self.password))

    def ratelimit_expired(self, limit=3):
        key = "ratelimit:%s:%s" % (self.__class__.__name__, self.user_id)
        time_slice = ratelimit.get_timeslice(60 * 60)
        usage = ratelimit.record_usage(key, time_slice)
        if usage > limit:
            self.consume()
            return True


class AwardClaimToken(ConsumableToken):
    token_size = 20
    _ttl = datetime.timedelta(days=30)
    _defaults = dict(ConsumableToken._defaults.items() + [
                         ("awardfullname", ""),
                         ("description", ""),
                         ("url", ""),
                         ("uid", "")])
    _use_db = True
    _connection_pool = "main"
    path = "/awards/confirm/"

    @classmethod
    def _new(cls, uid, award, description, url):
        '''Create an AwardClaimToken with the given parameters

        `uid` - A string that uniquely identifies the kind of
                Trophy the user would be claiming.*
        `award_codename` - The codename of the Award the user will claim
        `description` - The description the Trophy will receive
        `url` - The URL the Trophy will receive

        *Note that this differs from Award codenames, because it may be
        desirable to allow users to have multiple copies of the same Award,
        but restrict another aspect of the Trophy. For example, users
        are allowed to have multiple Translator awards, but should only get
        one for each language, so the `unique_award_id`s for those would be
        of the form "i18n_%(language)s"

        '''
        return super(AwardClaimToken, cls)._new(
            awardfullname=award._fullname,
            description=description or "",
            url=url or "",
            uid=uid,
        )


def make_reset_token(token_cls, user, issue_limit=3):
    """Generate a password reset token or account recovery token.

    Checks a ratelimit to ensure that the token isn't being reset too often.
    There is also a global check on resets, such that more than 1000 per hour
    will trigger obvious and loud breakage via a ValueError.

    Issuing (or failing to issue) a token are added to user's notes.
    """

    # check if we've hit the ratelimit
    reset_count_key = "token:%s_count:%s" % (token_cls.__name__, user._id)
    time_slice = ratelimit.get_timeslice(int(token_cls._ttl))
    usage = ratelimit.record_usage(reset_count_key, time_slice)
    if usage > issue_limit:
        user.add_note("Exceeded password/email reset max attempts.")
        return None

    # check if we've hit the global rate limit and fail badly
    reset_count_global = "token:%s_count_global" % (token_cls.__name__,)
    global_time_slice = ratelimit.get_timeslice(60 * 60)
    global_usage = ratelimit.record_usage(reset_count_global,
                                          global_time_slice)

    if global_usage > 1000:
        raise ValueError(
            "Somebody's beating the hell out of the password reset endpoint"
        )

    # all is well.  issue the token.
    token = token_cls._new(user)

    return token
