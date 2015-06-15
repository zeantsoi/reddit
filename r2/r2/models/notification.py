# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the 'License'); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an 'AS IS' basis,
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

from collections import OrderedDict
from datetime import datetime, timedelta
from pylons import g

from r2.lib import hooks
from r2.lib.db import tdb_cassandra
from r2.models import (
    Account,
    Comment,
    Link,
    Message,
    Thing,
)
from r2.lib.utils import tup

from pycassa import (
    NotFoundException,
    types,
)
from pycassa.cassandra.ttypes import ConsistencyLevel


class NotificationView(dict):
    def __init__(self, notification):
        self['id'] = notification.id
        self['type'] = notification.type
        self['last_modified'] = (
            notification.last_modified - datetime(1970, 1, 1)
        ).total_seconds()
        self['read'] = notification.read
        self['link'] = notification.link
        self['users'] = notification.user_names
        self['count'] = notification.count
        self['subject'] = notification.subject
        self['body'] = notification.body


class Notification(object):
    LINK = 'link'
    MESSAGE = 'message'
    MODMAIL = 'modmail'
    COMMENT = 'comment'
    MENTION = 'mention'
    UNKNOWN = 'unknown'

    def __init__(self, notification_type=UNKNOWN,
                 parent_fullname='', link='', user_names=[], subject='',
                 body='', count=0, last_modified=datetime.min, read=False):

        self.id = parent_fullname
        self.type = notification_type
        self.link = link
        self.user_names = user_names
        self.subject = subject
        self.body = body
        self.count = count
        self.last_modified = last_modified
        self.read = read

    @classmethod
    def notification_type(cls, thing):
        if isinstance(thing, Comment):
            if getattr(thing, 'parent_id', None):
                return cls.COMMENT
            elif getattr(thing, 'link_id', None):
                return cls.LINK
        elif isinstance(thing, Message):
            if getattr(thing, 'to_id'):
                return cls.MESSAGE
            elif getattr(thing, 'sr_id'):
                return cls.MODMAIL
        elif getattr(thing, '_name', None) == 'mention':
            return cls.MENTION

        return cls.UNKNOWN

    @classmethod
    def notification_type_from_parent(cls, parent):
        if isinstance(parent, Link):
            return cls.LINK
        elif isinstance(parent, Comment):
            return cls.COMMENT
        elif isinstance(parent, Message):
            if getattr(parent, 'to_id'):
                return cls.MESSAGE
            elif getattr(parent, 'sr_id'):
                return cls.MODMAIL
        elif getattr(parent, '_name', None) == 'mention':
            return cls.MENTION

        return cls.UNKNOWN


class NotificationsByAccountByThing(tdb_cassandra.View):
    _use_db = True
    _ttl = None
    _type_prefix = None
    _cf_name = None
    _compare_with = types.UTF8Type()
    _read_consistency_level = ConsistencyLevel.ONE
    _write_consistency_level = ConsistencyLevel.QUORUM
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
    }

    @staticmethod
    def key(account_id, parent_fullname):
        return '%s/%s' % (account_id, parent_fullname)

    @classmethod
    def get_batch(cls):
        return cls._cf.batch()

    @classmethod
    def get_rows(cls, account_id, parent_fullnames):
        return cls._cf.multiget(
            cls.key(account_id, parent_fullname)
            for parent_fullname in parent_fullnames
        )

    @classmethod
    def create(cls, account_id, parent_fullname, reply_fullname, now, read,
               batch=None):
        cf = batch if batch else cls._cf
        ttl = timedelta(days=30).total_seconds() if read else None
        rel_values = {
            reply_fullname: str(now)
        }
        cf.insert(
            cls.key(account_id, parent_fullname),
            rel_values,
            ttl=ttl,
        )


class NotificationsByAccount(tdb_cassandra.View):
    _use_db = True
    _ttl = None
    _type_prefix = None
    _cf_name = None
    _compare_with = types.CompositeType(
        types.DateType(),
        types.UTF8Type(),
    )
    _read_consistency_level = ConsistencyLevel.ONE
    _write_consistency_level = ConsistencyLevel.QUORUM
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
    }

    @staticmethod
    def key(account_id):
        return '%s' % (account_id)

    @classmethod
    def get_batch(cls):
        return cls._cf.batch()

    @classmethod
    def get_columns(cls, account_id, **kwargs):
        return cls._cf.xget(cls.key(account_id), **kwargs)

    @classmethod
    def create(cls, account_id, parent_fullname, reply_fullname, now, read,
               batch=None):
        cf = batch if batch else cls._cf
        ttl = timedelta(days=30).total_seconds() if read else None

        values = {
            (now, reply_fullname): '%s/%s' % (parent_fullname, read)
        }
        cf.insert(
            NotificationsByAccount.key(account_id),
            values,
            ttl=ttl,
        )


def generate_notifications(things):
    comment_parent_ids = set()
    link_ids = set()
    for thing in things:
        notification_type = Notification.notification_type(
            thing
        )
        if notification_type == Notification.COMMENT:
            comment_parent_ids.add(thing.parent_id)
        elif notification_type == Notification.LINK:
            link_ids.add(thing.link_id)

    comment_parents = Comment._byID(
        list(comment_parent_ids),
        return_dict=True,
        ignore_missing=False,
        data=True,
    )

    links = Link._byID(
        list(link_ids),
        return_dict=True,
        ignore_missing=False,
        data=True,
    )

    def comment(thing):
        parent = comment_parents[thing.parent_id]
        if thing.author_id != parent.author_id:
            return {
                'account_id': parent.author_id,
                'parent_fullname': parent._fullname,
                'reply_fullname': thing._fullname,
            }

    def link(thing):
        parent = links[thing.link_id]
        if thing.author_id != parent.author_id:
            return {
                'account_id': parent.author_id,
                'parent_fullname': parent._fullname,
                'reply_fullname': thing._fullname,
            }

    def message(thing):
        return {
            'account_id': thing.to_id,
            'parent_fullname': thing._fullname,
            'reply_fullname': thing._fullname,
        }

    def modmail(thing):
        # Ignore ModMail notifications for now
        return None

    def mention(thing):
        if thing._thing2.author_id != thing._thing1._id:
            return {
                'account_id': thing._thing1._id,
                'parent_fullname': thing._fullname,
                'reply_fullname': thing._thing2._fullname,
            }

    def unknown(thing):
        g.log.error(
            'Unknown notification type for thing fullname "%s"' %
            (thing._fullname)
        )
        return None

    notification_builders = {
        Notification.COMMENT: comment,
        Notification.LINK: link,
        Notification.MESSAGE: message,
        Notification.MODMAIL: modmail,
        Notification.MENTION: mention,
        Notification.UNKNOWN: unknown,
    }

    notifications = []
    for thing in things:
        notification_type = Notification.notification_type(thing)
        notification = notification_builders[notification_type](thing)
        if notification:
            should_send_hooks = hooks.get_hook(
                'notification.should_send'
            ).call(
                notification_type=notification_type,
                recipient_id=notification.get('account_id'),
                parent_fullname=notification.get('parent_fullname'),
                reply_fullname=notification.get('reply_fullname'),
            )
            if len(should_send_hooks) > 0 and all(should_send_hooks):
                notifications.append(notification)

                hooks.get_hook('notification.send').call(
                    notification_type=notification_type,
                    recipient_id=notification.get('account_id'),
                    parent_fullname=notification.get('parent_fullname'),
                    reply_fullname=notification.get('reply_fullname'),
                )

    return notifications


def get_notifications(account_id, start_date=datetime(1970, 1, 1),
                      end_date=datetime(2038, 1, 1), count=30, reverse=False):
    # start_date and end_date default to these values because cassandra
    # converts datetimes internally into unix timestamps before comparing
    # them. If we were to use datetime.min and datetime.max we would get
    # overflows and suddenly nothing makes sense.
    notifications = []
    columns = None
    column_start = (start_date,)
    column_finish = (end_date,)
    if reverse:
        column_start, column_finish = (column_finish, column_start)

    try:
        columns = NotificationsByAccount.get_columns(
            account_id,
            column_start=column_start,
            column_finish=column_finish,
            column_count=count,
            column_reversed=reverse,
        )
    except NotFoundException:
        return notifications

    replies_by_thing = OrderedDict()
    all_fullnames = set()
    last_modifieds = {}
    reads = {}

    for key, value in columns:
        last_modified, reply_fullname = key
        parent_fullname, read = tup(value.split('/'))
        # check if there already is a replies_by_thing entry. If there is
        # not, then create one.
        reply_fullnames = replies_by_thing.get(parent_fullname, None)
        if not reply_fullnames:
            reply_fullnames = set()
            replies_by_thing[parent_fullname] = reply_fullnames
            last_modifieds[parent_fullname] = last_modified
        else:
            newest_last_modified = last_modifieds[parent_fullname]
            if last_modified > newest_last_modified:
                last_modifieds[parent_fullname] = last_modified

        reply_fullnames.add(reply_fullname)
        all_fullnames.add(parent_fullname)
        # Only put the first 3 in to all_fullnames to limit records
        if len(reply_fullnames) <= 3:
            all_fullnames.add(reply_fullname)
        reads[parent_fullname] = read

    things = Thing._by_fullname(
        all_fullnames,
        data=True,
        return_dict=True,
    )

    # Load up authors for replies so we can get the author's name later
    author_ids = set()
    for parent_fullname, reply_fullnames in replies_by_thing.iteritems():
        for reply_fullname in reply_fullnames:
            reply = things.get(reply_fullname, None)
            if reply:
                author_ids.add(reply.author_id)

    accounts = Account._byID(
        author_ids,
        return_dict=True,
        data=True,
    )

    for parent_fullname, reply_fullnames in replies_by_thing.iteritems():
        thing = things[parent_fullname]
        notification_type = Notification.notification_type_from_parent(
            thing
        )

        count = len(reply_fullnames)
        replies = [
            things[reply_fullname] for reply_fullname in reply_fullnames
            if (reply_fullname in things and
                not things[reply_fullname]._deleted and
                not things[reply_fullname]._spam)
        ]

        permalink = None

        # mentions are handled differently, the parent is an inbox rel
        if notification_type == Notification.MENTION:
            permalink = thing._thing2.make_permalink_slow()
        else:
            permalink = thing.make_permalink_slow()

        read = reads[parent_fullname]

        subject = None
        body = None
        if notification_type == Notification.MESSAGE:
            subject = thing.subject
            body = thing.body

        names = set()
        for reply in replies:
            account = accounts.get(reply.author_id)
            if account and not account._deleted:
                names.add(account.name)

        notifications.append(Notification(
            notification_type,
            parent_fullname,
            permalink,
            list(names),
            subject,
            body,
            count,
            last_modifieds[parent_fullname],
            read=read == 'True',
        ))

    return notifications


def add_notification(account_id=None, parent_fullname=None,
                     reply_fullname=None, batch=None, rel_batch=None):
    now = datetime.now()
    NotificationsByAccountByThing.create(
        account_id,
        parent_fullname,
        reply_fullname,
        now,
        read=False,
        batch=rel_batch,
    )
    NotificationsByAccount.create(
        account_id,
        parent_fullname,
        reply_fullname,
        now,
        read=False,
        batch=batch,
    )


def add_notifications(notifications):
    with NotificationsByAccount.get_batch() as batch:
        with NotificationsByAccountByThing.get_batch() as rel_batch:
            for notification in notifications:
                add_notification(
                    batch=batch,
                    rel_batch=rel_batch,
                    **notification
                )


def mark_notifications_read(account_id, parent_fullnames, read):

    rows = NotificationsByAccountByThing.get_rows(account_id, parent_fullnames)

    with NotificationsByAccountByThing.get_batch() as rel_batch:
        with NotificationsByAccount.get_batch() as batch:
            for parent_fullname in parent_fullnames:
                row = rows.get(NotificationsByAccountByThing.key(
                    account_id,
                    parent_fullname,
                ))

                for reply_fullname, str_now in row.iteritems():
                    now = datetime.strptime(str_now, '%Y-%m-%d %H:%M:%S.%f')
                    NotificationsByAccountByThing.create(
                        account_id,
                        parent_fullname,
                        reply_fullname,
                        now,
                        read=True,
                        batch=rel_batch,
                    )
                    NotificationsByAccount.create(
                        account_id,
                        parent_fullname,
                        reply_fullname,
                        now,
                        read=True,
                        batch=batch,
                    )
