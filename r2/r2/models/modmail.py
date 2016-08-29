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
from sqlalchemy.types import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)

from r2.lib.db.thing import NotFound
from r2.lib.filters import safemarkdown
from r2.lib.utils import Enum, tup, to36
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
    is_highlighted - this field will be true if a conversation has been
        'highlighted' and false if the conversation is not 'highlighted'
    legacy_first_message_id - the ID for the first Message object in this
        conversation in the legacy messaging system (if any).

    """

    __tablename__ = "modmail_conversations"

    id = Column(BigInteger, primary_key=True)
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
    is_highlighted = Column(Boolean, nullable=False, default=False)
    legacy_first_message_id = Column(BigInteger, index=True)

    messages = relationship(
        "ModmailMessage",
        order_by="ModmailMessage.date.desc()", lazy="joined")

    mod_actions = relationship(
        "ModmailConversationAction",
        order_by="ModmailConversationAction.date.desc()", lazy="joined")

    # DO NOT REARRANGE THE ITEMS IN THIS ENUM - only append new items at bottom
    # Pseudo-states: mod (is_internal), notification (is_auto), these
    # pseudo-states act as a conversation type to denote mod only convos and
    # automoderator generated convos
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
                'id': to36(element.id)
            })

        return ordered_id_array

    @property
    def id36(self):
        return to36(self.id)

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
                 body, is_author_hidden=False, to=None,
                 legacy_first_message_id=None, is_auto=False):
        self.owner_fullname = owner._fullname
        self.subject = subject
        self.legacy_first_message_id = legacy_first_message_id
        self.num_messages = 0
        self.is_internal = False
        self.is_auto = is_auto
        participant_id = None

        if owner.is_moderator_with_perms(author, 'mail'):
            # check if moderator has addressed the new convo to someone
            # if they have make the convo not internal and add the 'to' user
            # as the participant of the conversation. If the 'to' user is also
            # a moderator of the subreddit convert the conversation to an
            # internal conversation (i.e. mod discussion). Auto conversations
            # can never be internal conversations.
            if to and not owner.is_moderator_with_perms(to, 'mail'):
                participant_id = to._id
            elif not is_auto:
                self.is_internal = True
        else:
            participant_id = author._id
            if is_author_hidden:
                raise MustBeAModError(
                        'Must be a mod to hide the message author.')

        Session.add(self)

        if participant_id:
            self.add_participant(participant_id)

        self.add_message(author, body,
                         is_author_hidden=is_author_hidden)

    @classmethod
    def unread_convo_count(cls, user):
        """Returns a dict by conversation state with a count
        of all the unread conversations for the passed user.

        Returns the following dict:
        {
            'new': <count>,
            'inprogress': <count>,
            'mod': <count>,
            'notifications': <count>,
            'highlighted': <count>,
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
                     ModmailConversationUnreadState.conversation_id == cls.id,
                     ModmailConversationUnreadState.active.is_(True)))

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
                           label('highlighted', func.count(case(
                               [(cls.is_highlighted, cls.id)],
                               else_=literal_column('NULL')))),
                           label('total', func.count(cls.id)),)
                        .select_from(subquery)
                        .group_by(cls.state))

        convo_counts = query.all()

        # initialize result dict so all keys are present
        result = {state: 0 for state in ModmailConversation.STATE.name}
        result.update({
            'notifications': 0,
            'mod': 0,
            'highlighted': 0
        })

        if not convo_counts:
            return result

        for convo_count in convo_counts:
            (state, internal_count, auto_count,
             highlighted_count, total_count) = convo_count
            num_convos = total_count - internal_count

            result['mod'] += internal_count
            result['highlighted'] += highlighted_count

            # Only add count to notifications and higlighted for 'new'
            # conversations, ignore 'inprogress' and 'archived' conversations
            if state == ModmailConversation.STATE.new:
                result['notifications'] += auto_count
                # Do not double count notification messages that are 'new'
                num_convos -= auto_count

            if state in ModmailConversation.STATE:
                result[ModmailConversation.STATE.name[state]] += num_convos

        return result

    @classmethod
    def _byID(cls, ids, current_user=None):
        """Return conversation(s) looked up by ID.

        Additional logic has been added to deal with the case
        when the current user is passed into the method. When
        a current_user is passed query.one() returns a keyedtuple,
        whereas, when a current_user is not passed it returns a
        single object.
        """
        ids = tup(ids)

        query = Session.query(cls).filter(cls.id.in_(ids))

        if current_user:
            query = query.add_columns(
                ModmailConversationUnreadState.date.label("last_unread"))

            query = query.outerjoin(
                ModmailConversationUnreadState,
                and_(ModmailConversationUnreadState.account_id ==
                     current_user._id,
                     ModmailConversationUnreadState.conversation_id.in_(ids),
                     ModmailConversationUnreadState.active.is_(True))
            )

        if len(ids) == 1:
            try:
                if not current_user:
                    return query.one()

                conversation, last_unread = query.one()
                conversation.last_unread = last_unread
                return conversation
            except NoResultFound:
                raise NotFound

        results = []
        for row in query.all():
            if current_user:
                conversation = row[0]
                conversation.last_unread = row[1]
                results.append(conversation)
            else:
                results.append(row)

        return results

    @classmethod
    def _by_legacy_message(cls, legacy_message):
        """Return conversation associated with a legacy message."""

        if legacy_message.first_message:
            legacy_id = legacy_message.first_message
        else:
            legacy_id = legacy_message._id

        query = Session.query(cls).filter_by(legacy_first_message_id=legacy_id)

        try:
            return query.one()
        except NoResultFound:
            raise NotFound

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
        elif state == 'notifications':
            query = query.filter(cls.is_auto.is_(True),
                                 cls.state == cls.STATE['new'])
        elif state == 'highlighted':
            query = query.filter(cls.is_highlighted.is_(True))
        elif state != 'all':
            query = (query.filter_by(state=cls.STATE[state])
                          .filter(cls.is_internal.is_(False)))

            if state == 'new':
                query = query.filter(cls.is_auto.is_(False))

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
                 ModmailConversationUnreadState.conversation_id == cls.id,
                 ModmailConversationUnreadState.active.is_(True))
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

        if limit:
            query = query.limit(limit)

        results = []

        # attach the last_read data to the objects
        for row in query.all():
            result = row.ModmailConversation
            result.last_unread = row.last_unread
            results.append(result)

        return results

    @classmethod
    def get_recent_convo_by_sr(cls, srs):
        if not srs:
            return

        sr_fullnames = [sr._fullname for sr in srs]
        query = (Session.query(cls.owner_fullname, func.max(cls.last_updated))
                        .filter(cls.owner_fullname.in_(sr_fullnames))
                        .group_by(cls.owner_fullname)
                        .order_by(func.max(cls.last_updated)))

        return {row[0]: row[1].isoformat() for row in query.all()}

    def make_permalink(self):
        return '{}mail/perma/{}'.format(g.modmail_base_url, self.id36)

    def get_participant_account(self):
        if self.is_internal:
            return None

        try:
            convo_participant = ModmailConversationParticipant.get_participant(
                self.id)
            participant = Account._byID(convo_participant.account_id)
        except NotFound:
            if not self.is_auto:
                raise
            return None

        if participant._deleted:
            raise NotFound

        return participant

    def add_participant(self, participant_id):
        participant = ModmailConversationParticipant(self, participant_id)
        Session.add(participant)

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

        is_first_message = (self.num_messages == 1)
        if sr.is_moderator_with_perms(author, 'mail'):
            # Check if a mod who is not the original author of the
            # conversation is responding and if so change the state
            # of the conversation to 'inprogress'. Internal
            # conversations also should not change state to 'inprogress'.
            # Lastly if a conversation is 'archived' change the state
            # to 'inprogress' regardless if the mod has participated or not
            if (not self.is_internal and
                    not is_first_message and
                    (author._id not in self.author_ids or
                     self.state == self.STATE['archived'])):
                self.state = self.STATE['inprogress']

            self.last_mod_update = message.date
        else:
            # Set the state to 'inprogress' only if a mod has responded
            # with a message in the conversation already and the conversation
            # is not already in an 'inprogress' state.
            if (self.last_mod_update is not None and
                    (self.last_mod_update !=
                     datetime.min.replace(tzinfo=g.tz)) and
                    self.state != self.STATE['inprogress']):
                self.state = self.STATE['inprogress']

            self.last_user_update = message.date

        try:
            Session.commit()
        except Exception as e:
            g.log.error('Failed to save message: {}'.format(e))
            Session.rollback()
            raise

        update_sr_mods_modmail_icon(sr)

        # create unread records for all except the author of
        # the newly created message
        ModmailConversationUnreadState.create_unreads(
            self.id,
            list((set(sr.moderators) | set(self.author_ids)) -
                 set([author._id]))
        )

        return message

    def get_participant(self):
        try:
            if not self.is_internal:
                return ModmailConversationParticipant.get_participant(
                    self.id)
        except NotFound:
            pass

        return None

    def add_action(self, account, action_type_name, commit=False):
        """Add an action message to a conversation"""
        try:
            convo_action = ModmailConversationAction(
                    self, account, action_type_name)
            Session.add(convo_action)
        except ValueError:
            raise
        except Exception as e:
            g.log.error('Failed to save mod action: {}'.format(e))
            Session.rollback()
            raise

        if commit:
            Session.commit()

    def set_state(self, state):
        """Set the state of this conversation."""
        try:
            self.state = self.STATE[state]
        except KeyError:
            Session.rollback()
            raise ValueError("invalid state")

        Session.commit()

    def set_legacy_first_message_id(self, message_id):
        """Set the legacy_first_message_id for this conversation."""
        self.legacy_first_message_id = message_id
        Session.commit()

    def mark_read(self, user):
        """Mark this conversation read for a user."""
        ModmailConversationUnreadState.mark_read(user, [self.id])

    def mark_unread(self, user):
        """Mark this conversation unread for a user."""
        ModmailConversationUnreadState.create_unreads(self.id, [user._id])

    def add_highlight(self):
        """Add a highlight to this conversation."""
        self.is_highlighted = True
        Session.commit()

    def remove_highlight(self):
        """Remove the highlight from this conversation."""
        self.is_highlighted = False
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
            'isAuto': self.is_auto,
            'numMessages': self.num_messages,
            'owner': {
                'id': self.owner_fullname,
                'type': entity._type_name,
                'displayName': entity.name
            },
            'isHighlighted': self.is_highlighted,
            'id': to36(self.id),
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
                    to36(message.id): message.to_serializable(
                        entity,
                        authors_dict.get(message.author_id),
                        current_user
                    )
                    for message in self.messages
                },
                'modActions': {
                    to36(mod_action.id): mod_action.to_serializable()
                    for mod_action in self.mod_actions
                }
            })
        else:
            result_dict.update({
                'objIds': [
                    {'key': 'messages', 'id': to36(self.messages[0].id)}
                ]
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
    user_is_mod = entity.is_moderator_with_perms(current_user, 'mail')
    author_is_mod = (entity.is_moderator_with_perms(author, 'mail') or
                     author.name == g.automoderator_account)
    if (current_user and
            (not user_is_mod and is_hidden)):
        name = entity.name

    return {
        'id': author._id,
        'name': name,
        'isAdmin': author.employee,
        'isMod': bool(author_is_mod),
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

    id = Column(BigInteger, primary_key=True)
    conversation_id = Column(
        BigInteger,
        ForeignKey(
            "modmail_conversations.id",
            deferrable=True,
            use_alter=True,
            name='fk_conversation_id',
        ),
        index=True,
    )
    date = Column(DateTime(timezone=True), nullable=False)
    author_id = Column(Integer, nullable=False, index=True)
    is_author_hidden = Column(Boolean, nullable=False, default=False)
    body = Column(Text, nullable=False)
    is_internal = Column(Boolean, nullable=False, default=False)

    conversation = relationship(
        ModmailConversation,
        primaryjoin=(conversation_id == ModmailConversation.id),
        post_update=True
    )

    def __init__(self, conversation, author, body,
                 is_author_hidden=False, is_internal=False):
        self.conversation = conversation
        self.date = datetime.now(g.tz)
        self.author_id = author._id
        self.is_author_hidden = is_author_hidden
        self.body = body
        self.is_internal = is_internal

    @property
    def id36(self):
        return to36(self.id)

    def to_serializable(self, sr, author, current_user=None):

        return {
            'id': to36(self.id),
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
        BigInteger, ForeignKey("modmail_conversations.id"), primary_key=True)
    account_id = Column(Integer, primary_key=True, index=True)
    active = Column(Boolean, index=True, default=True)
    date = Column(DateTime(timezone=True), nullable=False)

    def __init__(self, conversation_id, account_id):
        self.conversation_id = conversation_id
        self.account_id = account_id
        self.date = datetime.now(g.tz)

    @classmethod
    def mark_read(cls, user, ids):
        # Let the user update as many of their own ids as they want
        # set active to False for convos that have been read
        (Session.query(cls)
                .filter_by(account_id=user._id)
                .filter(cls.conversation_id.in_(ids))
                .update({'active': False}, synchronize_session=False))

        try:
            Session.commit()
        except Exception as e:
            g.log.error('Failed to mark conversations as read: {}'.format(e))
            Session.rollback()
            return

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
            except Exception as e:
                g.log.error('Failed to mark conversation unread: {}'.format(e))
                return

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
                    .filter(cls.account_id.in_(user_ids),
                            cls.active.is_(True))
                    .group_by(cls.account_id))

        results = dict(q.all())

        return {user_id: results.get(user_id, False)
                for user_id in user_ids}

    @classmethod
    def unreads_exist(cls, user):
        """Returns True or False for the passed user if they have unreads
        that exist or not"""

        q = (Session.query(cls)
                    .filter_by(account_id=user._id, active=True))

        return (Session.query(literal(True)).filter(q.exists()).scalar()
                is not None)

    @classmethod
    def create_unreads(cls, conversation_id, user_ids):
        """This method will create unread records for the current
        conversation, for the list of user_ids that are passed.

        The method will first look for any 'inactive' unread states
        to convert them to 'active'. After that all currently 'active'
        unread records are queried for and the union of ids of the users
        with previously 'inactive' unread records and those with active
        unread records.

        The difference is then taken from the passed user_ids and new
        unread records are created for users who did not have previously
        created unread records.
        """

        if not user_ids:
            return

        inactive_unreads_query = (
            Session.query(cls)
                   .filter(
                       cls.account_id.in_(user_ids),
                       cls.conversation_id == conversation_id,
                       cls.active.is_(False))
        )

        inactive_unreads_query.update(
            {'active': True, 'date': datetime.now(g.tz)},
            synchronize_session=False
        )

        active_unreads_query = (
            Session.query(cls.account_id)
                   .filter(
                       cls.account_id.in_(user_ids),
                       cls.conversation_id == conversation_id,
                       cls.active.is_(True))
        )

        active_user_read_states = set([row[0] for row in active_unreads_query])
        inactive_user_read_states = set([row['id']
                                        for row in inactive_unreads_query])

        read_states_already_exist = (
            active_user_read_states | inactive_user_read_states
        )

        create_read_state_user_ids = set(user_ids) - read_states_already_exist

        for user_id in create_read_state_user_ids:
            mark = cls(conversation_id, user_id)
            Session.add(mark)

        try:
            Session.commit()
        except IntegrityError as e:
            g.log.error('Failed to create unread records: {}'.format(e))
            Session.rollback()


class ModmailConversationParticipant(Base):
    """Mapping table which maps user ids to a particular conversation

    This will allow quick lookups for non-mod users who are associated
    with a particular mod conversation.
    """

    __tablename__ = 'modmail_conversation_participants'

    id = Column(BigInteger, primary_key=True)
    conversation_id = Column(
        BigInteger,
        ForeignKey(
            ModmailConversation.id,
            deferrable=True,
            use_alter=True,
            name='fk_conversation_id',
        ),
        index=True
    )
    account_id = Column(Integer, index=True)
    owner_fullname = Column(String(100), nullable=False, index=True)
    date = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )

    conversation = relationship(
        ModmailConversation,
        primaryjoin=(conversation_id == ModmailConversation.id),
        post_update=True
    )

    def __init__(self, conversation, account_id):
        self.conversation = conversation
        self.account_id = account_id
        self.owner_fullname = conversation.owner_fullname
        self.date = datetime.now(g.tz)

    @classmethod
    def get_participant(cls, conversation_id):
        query = (Session.query(cls)
                        .filter(cls.conversation_id == conversation_id))

        # only returning a single record now as there can only
        # be one non-mod participant per conversation
        try:
            return query.one()
        except NoResultFound:
            raise NotFound

    @classmethod
    def is_participant(cls, account_id, conversation_id):
        return (Session.query(exists().where(
            and_(cls.account_id == account_id,
                 cls.conversation_id == conversation_id)
        ))).scalar()


class ModmailConversationAction(Base):
    """Mapping table which will map a particular users action to its
    associated conversation

    This will track which actions have been applied by whom for each
    conversation.
    """

    __tablename__ = 'modmail_conversation_actions'

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
            BigInteger, ForeignKey(ModmailConversation.id),
            nullable=False, index=True)
    account_id = Column(Integer, index=True)
    action_type_id = Column(Integer, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)

    # DO NOT REARRANGE ORDERING, APPEND NEW TYPES TO THE END
    ACTION_TYPES = Enum(
        'highlighted',
        'unhighlighted',
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

    @property
    def id36(self):
        return to36(self.id)

    @classmethod
    def add_actions(cls, conversations, account, action_type_name):
        conversations = tup(conversations)
        try:
            for conversation in conversations:
                convo_action = ModmailConversationAction(
                        conversation, account, action_type_name)
                Session.add(convo_action)
        except Exception as e:
            g.log.error('Failed bulk action creation: {}'.format(e))
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
            'id': to36(self.id),
            'author': {
                'id': author_id,
                'name': name,
                'isAdmin': author.employee,
                'isMod': True,
                'isHidden': False,
                'isDeleted': author._deleted
            },
            'actionTypeId': self.action_type_id,
            'date': self.date.isoformat(),
        }


class MustBeAModError(Exception):
    pass


if g.db_create_tables:
    Base.metadata.create_all()
