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

from datetime import datetime

from pylons import app_globals as g
from sqlalchemy import and_, case, exists, func, literal_column, sql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.schema import Column, ForeignKey
from sqlalchemy.sql.expression import label, literal
from sqlalchemy.types import Boolean, DateTime, Integer, String, Text

from r2.lib.db.thing import NotFound
from r2.lib.filters import safemarkdown
from r2.lib.utils import Enum, tup
from r2.models.account import Account
from r2.models.subreddit import Subreddit

ENGINE = g.dbm.get_engine("modmail")

Session = scoped_session(sessionmaker(bind=ENGINE))
Base = declarative_base(bind=ENGINE)


class ModmailConversation(Base):
    """An overall conversation/ticket, potentially multiple messages.

    owner_fullname - The fullname of the "owner" of this conversation. For
        modmail, this is a subreddit's fullname.
    subject - The overall conversation's subject.
    state - The state of the conversation (new, etc.)
    num_messages - The total number of messages in the conversation.
    last_user_update - The last datetime a user made any interaction with the
        conversation
    last_mod_update - The last datetime a mod made any interaction with the
        conversation
    last_updated - Last time that this conversation had a significant update
        (new message). Can be combined with the read-state table
        to determine if a conversation should be considered unread for a user.
        This is the max of the two values last_user_update and last_mod_update
        and is a hybrid property on the model.
    is_internal - Whether the conversation is internal-only. If true, it means
        that it can only be viewed and interacted with by someone with overall
        access to the conversations (for example, a moderator in the case of
        modmail). If the user stops having overall access, they will also lose
        access to all internal conversations, regardless of whether they
        participated in them or not.
    star - this field will be true if a conversation has been 'starred' and
        false if the conversation is not 'starred'

    """

    __tablename__ = "modmail_conversations"

    id = Column(Integer, primary_key=True)
    owner_fullname = Column(String(100), nullable=False, index=True)
    subject = Column(String(100), nullable=False)
    state = Column(Integer, index=True, default=0)
    num_messages = Column(Integer, nullable=False, default=0)
    last_user_update = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=datetime.min)
    last_mod_update = Column(
        DateTime(timezone=True),
        nullable=False, index=True,
        default=datetime.min)
    is_internal = Column(Boolean, nullable=False, default=False)
    is_auto = Column(Boolean, nullable=False, default=False)
    star = Column(Boolean, nullable=False, default=False)

    messages = relationship(
        "ModmailMessage", backref="conversation",
        order_by="ModmailMessage.date.desc()", lazy="joined")

    mod_actions = relationship(
            "ModmailConversationAction", backref="conversation",
            order_by="ModmailConversationAction.date.desc()", lazy="joined")

    # DO NOT REARRANGE THE ITEMS IN THIS ENUM - only append new items at bottom
    # Pseudo-states: mod (is_internal), notification (is_auto), these pseudo-states
    # act as a conversation type to denote mod only convos and automoderator generated
    # convos
    STATE = Enum(
        "new",
        "inprogress",
        "archived",
    )

    @property
    def author_ids(self):
        return [message.author_id for message in self.messages]

    @property
    def mod_action_account_ids(self):
        return [mod_action.account_id for mod_action in self.mod_actions]

    @property
    def ordered_msg_and_action_ids(self):
        order_elements = self.messages + self.mod_actions
        ordered_elements = sorted(order_elements, key=lambda x: x.date)

        ordered_id_array = []
        for element in ordered_elements:
            key = 'messages'
            if isinstance(element, ModmailConversationAction):
                key = 'modActions'

            ordered_id_array.append({
                'key': key,
                'id': element.id
            })

        return ordered_id_array

    @hybrid_property
    def last_updated(self):
        if self.last_user_update is None and self.last_mod_update:
            return self.last_mod_update
        elif self.last_mod_update is None and self.last_user_update:
            return self.last_user_update

        return max(self.last_user_update, self.last_mod_update)

    @last_updated.expression
    def last_updated(cls):
        return func.greatest(cls.last_mod_update, cls.last_user_update)

    def __init__(self, owner, author, subject,
                 body, is_author_hidden=False):
        self.owner_fullname = owner._fullname
        self.subject = subject
        self.num_messages = 0
        self.is_internal = False
        self.is_auto = False
        participant_id = None

        if author.name == g.automoderator_account:
            self.is_auto = True

        if owner.is_moderator_with_perms(author, 'mail'):
            self.is_internal = True
        else:
            participant_id = author._id
            if is_author_hidden:
                raise MustBeAModError(
                        'Must be a mod to hide the message author.')

        # TODO: I think it should be possible to do this in a single commit
        # by using a deferred foreign key in the messages table?
        Session.add(self)
        Session.commit()

        self.add_message(author, body,
                         is_author_hidden=is_author_hidden)

        update_sr_mods_modmail_icon(owner)

        if participant_id:
            self.add_participant(participant_id)

    @classmethod
    def unread_convo_count(cls, user):
        """Returns a dict by conversation state with a count
        of all the unread conversations for the passed user.

        Returns the following dict:
        {
            'new': <count>,
            'inprogress': <count>,
            'mod': <count>,
            'notification': <count>,
            'archived': <count>
        }
        """
        users_modded_subs = user.moderated_subreddits('mail')
        sr_fullnames = [sr._fullname for sr in users_modded_subs]

        # Build subquery to select all conversations with an unread
        # record for the passed user, this will preselect the records
        # that need to be counted as well as limit the number of
        # rows that will have to be counted in the main query
        subquery = Session.query(cls)

        subquery = subquery.outerjoin(
                ModmailConversationUnreadState,
                and_(ModmailConversationUnreadState.account_id == user._id,
                     ModmailConversationUnreadState.conversation_id == cls.id))

        subquery = subquery.filter(
                cls.owner_fullname.in_(sr_fullnames),
                ModmailConversationUnreadState.date.isnot(None))

        subquery = subquery.subquery()

        # Pass the subquery to the count query to retrieve a tuple of
        # counts for each conversation state
        query = (Session.query(
                           cls.state,
                           label('internal', func.count(case(
                               [(cls.is_internal, cls.id)],
                               else_=literal_column('NULL')))),
                           label('auto', func.count(case(
                               [(cls.is_auto, cls.id)],
                               else_=literal_column('NULL')))),
                           label('total', func.count(cls.id)),)
                        .select_from(subquery)
                        .group_by(cls.state))

        convo_counts = query.all()

        # initialize result dict so all keys are present
        result = {state: 0 for state in ModmailConversation.STATE.name}
        result.update({
            'auto': 0,
            'internal': 0,
        })

        if not convo_counts:
            return result

        for convo_count in convo_counts:
            state, internal_count, auto_count, total_count = convo_count
            num_convos = total_count - internal_count - auto_count

            result['internal'] += internal_count
            result['auto'] += auto_count

            if state in ModmailConversation.STATE:
                result[ModmailConversation.STATE.name[state]] += num_convos

        return result

    @classmethod
    def _byID(cls, ids, current_user=None):
        """Return conversation(s) looked up by ID."""
        ids = tup(ids)

        query = Session.query(cls).filter(cls.id.in_(ids))

        if current_user:
            query = query.add_columns(
                ModmailConversationUnreadState.date.label("last_unread"))

            query = query.outerjoin(
                ModmailConversationUnreadState,
                and_(ModmailConversationUnreadState.account_id ==
                     current_user._id,
                     ModmailConversationUnreadState.conversation_id.in_(ids))
            )

        if len(ids) == 1:
            try:
                return query.one()[0]
            except NoResultFound:
                raise NotFound

        return query.all()

    @classmethod
    def get_mod_conversations(cls, owners, viewer=None, limit=None, after=None,
                              sort='recent', state='all'):
        """Get the list of conversations for a specific owner or list of
        owners.

        The optional `viewer` argument should be an Account that is viewing
        the listing.

        It will attach the unread-state data for that viewer.

        """
        if not owners:
            return []

        owners = tup(owners)

        query = Session.query(cls)

        fullnames = [owner._fullname for owner in owners]
        query = query.filter(cls.owner_fullname.in_(fullnames))

        # Filter messages based on passed state, all means that
        # that messages should not be filtered by state and returned
        # respecting the sort order that has been passed in. The
        # mod state is a special state which will filter
        # out conversations that are not internal. The other special
        # state is the notification state which denotes a convo created
        # by automoderator
        if state == 'mod':
            query = query.filter(cls.is_internal.is_(True))
        elif state == 'notification':
            query = query.filter(cls.is_auto.is_(True),
                                 cls.state == cls.STATE['new'])
        elif state != 'all':
            query = (query.filter_by(state=cls.STATE[state])
                          .filter(cls.is_internal.is_(False)))

            if state == 'new':
                query = query.filter(cls.is_auto.is_(False))

        if limit:
            query = query.limit(limit).from_self()

        # If viewer context is not passed just return the results
        # without adding the last_read attribute
        if not viewer:
            results = []
            for row in query.all():
                results.append(row.ModmailConversation)
            return results

        # look up the last time they read each conversation
        query = query.add_columns(
            ModmailConversationUnreadState.date.label("last_unread"))

        query = query.outerjoin(
            ModmailConversationUnreadState,
            and_(ModmailConversationUnreadState.account_id == viewer._id,
                 ModmailConversationUnreadState.conversation_id == cls.id)
        )

        if after:
            if sort == 'mod':
                query = (query.filter(cls.last_mod_update <=
                                      after.last_mod_update)
                              .filter(cls.id != after.id))
            elif sort == 'user':
                query = (query.filter(cls.last_user_update <=
                                      after.last_user_update)
                              .filter(cls.id != after.id))
            else:
                query = (query.filter(cls.last_updated <= after.last_updated)
                              .filter(cls.id != after.id))

        if sort == 'mod':
            query = query.order_by(sql.desc(cls.last_mod_update))
        elif sort == 'user':
            query = query.order_by(sql.desc(cls.last_user_update))
        else:
            query = query.order_by(sql.desc(cls.last_updated))

        results = []

        # attach the last_read data to the objects
        for row in query.all():
            result = row.ModmailConversation
            result.last_unread = row.last_unread
            results.append(result)

        return results

    def add_participant(self, participant_id):
        participant = ModmailConversationParticipant(self.id, participant_id)
        try:
            Session.add(participant)
            Session.commit()
        except:
            Session.rollback()

    def add_message(self, author, body,
                    is_author_hidden=False,
                    is_internal=False):
        """Add a new message to the conversation."""
        sr = Subreddit._by_fullname(self.owner_fullname)

        # if the conversation is internal, make the message
        # an internal message
        if self.is_internal:
            is_internal = True

        message = ModmailMessage(
            self, author, body, is_author_hidden, is_internal)
        Session.add(message)

        self.num_messages += 1
        if sr.is_moderator_with_perms(author, 'mail'):
            # Check if a mod who is not the original author of the
            # conversation is responding and if so change the state
            # of the conversation to 'inprogress'
            if (self.state == self.STATE['new'] and
                    author._id not in self.author_ids):
                self.state = self.STATE['inprogress']

            self.last_mod_update = message.date
        else:
            self.last_user_update = message.date

        Session.commit()

        update_sr_mods_modmail_icon(sr)

        # create unread records for all except the author of
        # the newly created message
        self._create_unread_helper(
            list((set(sr.moderators) | set(self.author_ids)) -
                 set([author._id])))

        return message

    def add_action(self, account, action_type_name):
        """Add an action message to a conversation"""
        try:
            convo_action = ModmailConversationAction(
                    self, account, action_type_name)
            Session.add(convo_action)
        except ValueError:
            raise
        except Exception:
            Session.rollback()
            raise

        Session.commit()

    def set_state(self, state):
        """Set the state of this conversation."""
        try:
            self.state = self.STATE[state]
        except KeyError:
            Session.rollback()
            raise ValueError("invalid state")

        Session.commit()

    def mark_read(self, user):
        """Mark this conversation read for a user."""
        ModmailConversationUnreadState.mark_read(user, [self.id])

    def mark_unread(self, user):
        """Mark this conversation unread for a user."""
        self._create_unread_helper([user._id])

    def _create_unread_helper(self, user_ids):
        if not user_ids:
            return

        query = (
            Session.query(ModmailConversationUnreadState.account_id)
                   .filter(
                       ModmailConversationUnreadState.account_id.in_(user_ids),
                       (ModmailConversationUnreadState.conversation_id ==
                        self.id))
        )

        user_read_states = set([row[0] for row in query])
        user_ids = set(user_ids) - user_read_states

        for user_id in user_ids:
            mark = ModmailConversationUnreadState(self.id, user_id)
            Session.add(mark)

        try:
            Session.commit()
        except IntegrityError:
            Session.rollback()

    def add_star(self):
        """Add a star to this conversation."""
        self.star = True
        # TODO: Add a system message about the event here?
        Session.commit()

    def remove_star(self):
        """Remove the star from this conversation."""
        self.star = False
        # TODO: Add a system message about the event here?
        Session.commit()

    @classmethod
    def set_states(cls, convo_ids, state):
        """Set state for multiple conversations"""
        convo_ids = tup(convo_ids)

        (Session.query(cls)
                .filter(cls.id.in_(convo_ids))
                .update({"state": state}, synchronize_session='fetch'))

        Session.commit()

    def to_serializable(self, authors_dict=None, entity=None,
                        all_messages=False, current_user=None):
        # Lookup authors if they are not passed
        if not authors_dict:
            from r2.models import Account
            authors_dict = Account._byID(
                    set(self.author_ids) | set(self.mod_action_account_ids),
                    return_dict=True)

        # Lookup entity if it is not passed
        if not entity:
            entity = Subreddit._by_fullname(self.owner_fullname)

        serializable_authors = []

        for message in self.messages:
            author = authors_dict.get(message.author_id)
            serializable_authors.append(
                to_serializable_author(author, entity,
                                       current_user,
                                       is_hidden=message.is_author_hidden)
            )

        last_unread = getattr(self, 'last_unread', None)
        if last_unread is not None:
            last_unread = last_unread.isoformat()

        parsed_last_user_update = None
        parsed_last_mod_update = None

        min_tz_aware_datetime = datetime.min.replace(tzinfo=g.tz)
        if self.last_user_update != min_tz_aware_datetime:
            parsed_last_user_update = self.last_user_update.isoformat()

        if self.last_mod_update != min_tz_aware_datetime:
            parsed_last_mod_update = self.last_mod_update.isoformat()

        result_dict = {
            'state': self.state,
            'lastUpdated': self.last_updated.isoformat(),
            'lastUserUpdate': parsed_last_user_update,
            'lastModUpdate': parsed_last_mod_update,
            'lastUnread': last_unread,
            'isInternal': self.is_internal,
            'numMessages': self.num_messages,
            'owner': {
                'id': self.owner_fullname,
                'type': entity._type_name,
                'displayName': entity.name
            },
            'isStarred': self.star,
            'id': self.id,
            'subject': self.subject,
            'authors': serializable_authors,
        }

        if all_messages:
            for mod_action in self.mod_actions:
                author = authors_dict.get(mod_action.account_id)
                serializable_authors.append(
                    to_serializable_author(author, entity,
                                           current_user,
                                           is_hidden=False)
                )

            result_dict.update({
                'objIds': self.ordered_msg_and_action_ids,
                'messages': {
                    message.id: message.to_serializable(
                        entity,
                        authors_dict.get(message.author_id),
                        current_user
                    )
                    for message in self.messages
                },
                'modActions': {
                    mod_action.id: mod_action.to_serializable()
                    for mod_action in self.mod_actions
                }
            })
        else:
            result_dict.update({
                'objIds': [{'key': 'messages', 'id': self.messages[0].id}]
            })

        return result_dict


def update_sr_mods_modmail_icon(sr):
    """Helper method to set the modmail icon for mods with mail permissions
    for the passed sr.

    Method will lookup all moderators for the passed sr and query whether they
    have unread conversations that exist. If the user has unreads the modmail
    icon will be lit up, if they do not it will be disabled.

    Args:
    sr  -- Subreddit object to fetch mods with mail perms from
    """

    mods_with_perms = sr.moderators_with_perms()
    modmail_user_ids = [mod_id for mod_id, perms in mods_with_perms.iteritems()
                        if 'mail' in perms or 'all' in perms]

    mod_accounts = Account._byID(modmail_user_ids, ignore_missing=True,
                                 return_dict=False)

    mail_exists_by_user = (ModmailConversationUnreadState
                           .users_unreads_exist(mod_accounts))

    for mod in mod_accounts:
        set_modmail_icon(mod, bool(mail_exists_by_user.get(mod._id)))


def set_modmail_icon(user, icon_status):
    """Account.new_modmail_exists has the following states

    None - no new modmail srs
    False - no unreads but have a sr enrolled in the new modmail
    True - unreads exist and a sr is enrolled in the new modmail
    """
    if user.new_modmail_exists != icon_status:
        user.new_modmail_exists = icon_status
        user._commit()


def to_serializable_author(author, entity, current_user, is_hidden=False):
    if not author or author._deleted:
        return {
            'id': '',
            'name': '[deleted]',
            'isAdmin': False,
            'isMod': False,
            'isHidden': False,
            'isDeleted': True,
        }

    name = author.name
    is_mod = entity.is_moderator_with_perms(current_user, 'mail')
    if (current_user and
            (not is_mod and is_hidden)):
        name = entity.name

    return {
        'id': author._id,
        'name': name,
        'isAdmin': author.employee,
        'isMod': bool(is_mod),
        'isHidden': is_hidden,
        'isDeleted': False,
    }


class ModmailMessage(Base):
    """An individual message, part of a conversation.

    conversation_id - ID for the conversation this message belongs to.
    date - The time that the message was sent.
    author_id - Account ID for the message's sender.
    is_author_hidden - Whether the message should hide the identity of the
        sender from external viewers (doesn't apply to internal viewers).
    body - Message content (markdown).
    is_internal - Whether the message is internal-only (not visible to the
        external user that may have initiated the ticket)

    """

    __tablename__ = "modmail_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer,
        ForeignKey("modmail_conversations.id"),
        nullable=False,
        index=True,
    )
    date = Column(DateTime(timezone=True), nullable=False)
    author_id = Column(Integer, nullable=False, index=True)
    is_author_hidden = Column(Boolean, nullable=False, default=False)
    body = Column(Text, nullable=False)
    is_internal = Column(Boolean, nullable=False, default=False)

    def __init__(self, conversation, author, body,
                 is_author_hidden=False, is_internal=False):
        self.conversation_id = conversation.id
        self.date = datetime.now(g.tz)
        self.author_id = author._id
        self.is_author_hidden = is_author_hidden
        self.body = body
        self.is_internal = is_internal

    def to_serializable(self, sr, author, current_user=None):

        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'author': to_serializable_author(author, sr, current_user,
                                             self.is_author_hidden),
            'body': safemarkdown(self.body),
            'isInternal': self.is_internal
        }


class ModmailConversationUnreadState(Base):
    """Stores when a conversation has not been read for a user.

    If a row for a particular user/conversation combo exists, that
    indicates that the user has not read the conversation. To
    mark a conversation read, delete the row for that user/conversation.

    The date indicates when the conversation was marked unread.
    Messages after the date could be highlighted to the user to
    differentiate read messages from unread messages.

    conversation_id - ID of the conversation.
    account_id - ID of the viewer.
    date - Time that the conversation was marked unread

    """

    __tablename__ = "modmail_conversation_unread_state"

    conversation_id = Column(
        Integer, ForeignKey("modmail_conversations.id"), primary_key=True)
    account_id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False)

    def __init__(self, conversation_id, account_id):
        self.conversation_id = conversation_id
        self.account_id = account_id
        self.date = datetime.now(g.tz)

    @classmethod
    def mark_read(cls, user, ids):
        # Let the user delete as many of their own ids as they want
        (Session.query(cls)
                .filter_by(account_id=user._id)
                .filter(cls.conversation_id.in_(ids))
                .delete(synchronize_session='fetch'))
        Session.commit()

        set_modmail_icon(user, bool(cls.unreads_exist(user)))

    @classmethod
    def mark_unread(cls, user, ids):
        # Marking things unread takes a bit more effort.
        # Get all the conversations in bulk
        conversations = (
            Session.query(ModmailConversation)
                   .filter(ModmailConversation.id.in_(ids))
        )

        # Then we mark each of them unread, allowing the conversation
        # to handle all the checking.  This can be made more efficient,
        # but as it's a less-common operation, it can wait.
        for conversation in conversations:
            try:
                conversation.mark_unread(user)
            except ValueError:
                pass

        set_modmail_icon(user, True)

    @classmethod
    def users_unreads_exist(cls, users):
        """Accepts a collection of account objects and will return
        a dict with account ids and true or false to signal the account
        has unreads that exist.

        output: { account_id: True|False }
        """

        user_ids = [user._id for user in tup(users)]
        q = (Session.query(
                        cls.account_id.label('account_id'),
                        exists().where(cls.account_id.in_(user_ids)))
                    .filter(cls.account_id.in_(user_ids))
                    .group_by(cls.account_id))

        results = dict(q.all())

        return {user_id: results.get(user_id, False)
                for user_id in user_ids}

    @classmethod
    def unreads_exist(cls, user):
        """Returns True or False for the passed user if they have unreads
        that exist or not"""

        q = (Session.query(cls)
                    .filter_by(account_id=user._id))

        return (Session.query(literal(True)).filter(q.exists()).scalar()
                is not None)


class ModmailConversationParticipant(Base):
    """Mapping table which maps user ids to a particular conversation

    This will allow quick lookups for non-mod users who are associated
    with a particular mod conversation.
    """

    __tablename__ = 'modmail_conversation_participants'

    conversation_id = Column(
        Integer, ForeignKey(ModmailConversation.id), primary_key=True)
    account_id = Column(Integer, primary_key=True, index=True)

    def __init__(self, conversation_id, account_id):
        self.conversation_id = conversation_id
        self.account_id = account_id

    @classmethod
    def get_conversation_ids(cls, account_id):
        # TODO: implement method to return convo ids that a
        # non mod user is a participant in
        raise NotImplementedError


class ModmailConversationAction(Base):
    """Mapping table which will map a particular users action to its
    associated conversation

    This will track which actions have been applied by whom for each
    conversation.
    """

    __tablename__ = 'modmail_conversation_actions'

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
            Integer, ForeignKey(ModmailConversation.id),
            nullable=False, index=True)
    account_id = Column(Integer, index=True)
    action_type_id = Column(Integer, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)

    # DO NOT REARRANGE ORDERING, APPEND NEW TYPES TO THE END
    ACTION_TYPES = Enum(
        'marked_important',
        'unmarked_important',
        'archived',
        'unarchived',
        'reported_to_admins',
        'muted',
        'unmuted',
        'banned',
        'unbanned',
    )

    def __init__(self, conversation, account, action_type_name):
        self.conversation_id = conversation.id
        self.account_id = account._id
        self.date = datetime.now(g.tz)

        try:
            self.action_type_id = self.ACTION_TYPES[action_type_name]
        except:
            raise ValueError('Incorrect action_type_name.')

    @classmethod
    def add_actions(cls, conversations, account, action_type_name):
        try:
            for conversation in conversations:
                convo_action = ModmailConversationAction(
                        conversation, account, action_type_name)
                Session.add(convo_action)
        except:
            Session.rollback()
            raise

        Session.commit()

    def to_serializable(self, author=None):
        if not author:
            from r2.models import Account
            author = Account._byID(self.account_id)

        name = author.name
        author_id = author._id
        if author._deleted:
            name = '[deleted]'
            author_id = None

        return {
            'author': {
                'id': author_id,
                'name': name,
                'isAdmin': author.employee,
                'isMod': True,
                'isHidden': False,
                'isDeleted': author._deleted
            },
            'action_type_id': self.action_type_id,
            'date': self.date.isoformat(),
        }


class MustBeAModError(Exception):
    pass


if g.db_create_tables:
    Base.metadata.create_all()
