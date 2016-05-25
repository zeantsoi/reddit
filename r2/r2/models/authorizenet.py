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
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################

from functools import partial

from pylons import app_globals as g
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.schema import Column, PrimaryKeyConstraint
from sqlalchemy.types import (
    BigInteger,
    DateTime,
    Float,
    Integer,
    String,
)

engine = g.dbm.get_engine('authorize')
Session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base(bind=engine)

NotNullColumn = partial(Column, nullable=False)


class AuthorizeSession(object):
    """Enables class specific querying of Authorize.net data."""

    session = Session()

    @classmethod
    def last_settlement_time(cls):
        order_by = cls.settlement_time.desc()
        rows = list(Session.query(cls).order_by(order_by).limit(1))

        try:
            return rows[0].settlement_time
        except IndexError:
            return None


class AuthorizeBatchSettlement(Base, AuthorizeSession):
    """Daily batch settlements from Authorize.net."""

    __tablename__ = 'authorize_batch_settlements'

    batch_id = NotNullColumn(BigInteger(), primary_key=True,
                             autoincrement=False)
    settlement_time = NotNullColumn(DateTime())
    settlement_state = NotNullColumn(String())


class AuthorizeBatchStatistic(Base):
    """Statistics (grouped payment types) by Authorize.net
    batch settlement.

    """

    __tablename__ = 'authorize_batch_statistics'
    __table_args__ = (PrimaryKeyConstraint('batch_id', 'account_type'),)

    batch_id = NotNullColumn(BigInteger(), index=True, autoincrement=False)
    settlement_time = NotNullColumn(DateTime(), index=True)
    account_type = NotNullColumn(String(), index=True)
    charge_amount = NotNullColumn(Float(precision=2, asdecimal=True))
    charge_count = NotNullColumn(Integer())
    refund_amount = NotNullColumn(Float(precision=2, asdecimal=True))
    refund_count = NotNullColumn(Integer())
    void_count = NotNullColumn(Integer())
    decline_count = NotNullColumn(Integer())
    error_count = NotNullColumn(Integer())


class AuthorizeBatchTransaction(Base):
    """Settled transactions by settlement batch."""

    __tablename__ = 'authorize_batch_transactions'

    batch_id = NotNullColumn(BigInteger(), index=True)
    trans_id = NotNullColumn(BigInteger(), primary_key=True,
                             autoincrement=False)
    submit_time = NotNullColumn(DateTime())
    transaction_status = NotNullColumn(String(), index=True)
    invoice_number = Column(String())
    first_name = Column(String())
    last_name = Column(String())
    account_type = NotNullColumn(String())
    account_number = NotNullColumn(String())
    settle_amount = NotNullColumn(Float(precision=2, asdecimal=True))


# create the tables if they don't exist
if g.db_create_tables:
    Base.metadata.create_all()
