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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement
from sqlalchemy import Column, String, DateTime, Date, Float, Integer, \
     func as safunc, and_, or_
from sqlalchemy.exceptions import IntegrityError
from sqlalchemy.schema import PrimaryKeyConstraint
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.databases.postgres import PGBigInteger as BigInteger, \
     PGInet as Inet
from sqlalchemy.ext.declarative import declarative_base
from pylons import g
from r2.lib.utils import Enum
from r2.models.account import Account
from r2.lib.db.thing import Thing, NotFound
from pylons import request
import datetime

engine = g.dbm.engines['authorize']
# Allocate a session maker for communicating object changes with the back end  
Session = sessionmaker(autocommit = True, autoflush = True, bind = engine)
# allocate a SQLalchemy base class for auto-creation of tables based
# on class fields.  
# NB: any class that inherits from this class will result in a table
# being created, and subclassing doesn't work, hence the
# object-inheriting interface classes.
Base = declarative_base(bind = engine)

class Sessionized(object):
    """
    Interface class for wrapping up the "session" in the 0.5 ORM
    required for all database communication.  This allows subclasses
    to have a "query" and "commit" method that doesn't require
    managing of the session.
    """
    session = Session()

    def __init__(self, *a, **kw):
        """
        Common init used by all other classes in this file.  Allows
        for object-creation based on the __table__ field which is
        created by Base (further explained in _disambiguate_args).
        """
        for k, v in self._disambiguate_args(None, *a, **kw):
            setattr(self, k.name, v)
    
    @classmethod
    def _new(cls, *a, **kw):
        """
        Just like __init__, except the new object is committed to the
        db before being returned.
        """
        obj = cls(*a, **kw)
        obj._commit()
        return obj

    def _commit(self):
        """
        Commits current object to the db.
        """
        with self.session.begin():
            self.session.add(self)

    def _delete(self):
        """
        Deletes current object from the db. 
        """
        with self.session.begin():
            self.session.delete(self)

    @classmethod
    def query(cls, **kw):
        """
        Ubiquitous class-level query function. 
        """
        q = cls.session.query(cls)
        if kw:
            q = q.filter_by(**kw)
        return q

    @classmethod
    def _disambiguate_args(cls, filter_fn, *a, **kw):
        """
        Used in _lookup and __init__ to interpret *a as being a list
        of args to match columns in the same order as __table__.c

        For example, if a class Foo has fields a and b, this function
        allows the two to work identically:
        
        >>> foo = Foo(a = 'arg1', b = 'arg2')
        >>> foo = Foo('arg1', 'arg2')

        Additionally, this function invokes _make_storable on each of
        the values in the arg list (including *a as well as
        kw.values())

        """
        args = []
        cols = filter(filter_fn, cls.__table__.c)
        for k, v in zip(cols, a):
            if not kw.has_key(k.name):
                args.append((k, cls._make_storable(v)))
            else:
                raise TypeError,\
                      "got multiple arguments for '%s'" % k.name
        
        cols = dict((x.name, x) for x in cls.__table__.c)
        for k, v in kw.iteritems():
            if cols.has_key(k):
                args.append((cols[k], cls._make_storable(v)))
        return args

    @classmethod
    def _make_storable(self, val):
        if isinstance(val, Account):
            return val._id
        elif isinstance(val, Thing):
            return val._fullname
        else:
            return val
            
    @classmethod
    def _lookup(cls, multiple, *a, **kw):
        """
        Generates an executes a query where it matches *a to the
        primary keys of the current class's table.

        The primary key nature can be overridden by providing an
        explicit list of columns to search.

        This function is only a convenience function, and is called
        only by one() and lookup().
        """
        args = cls._disambiguate_args(lambda x: x.primary_key, *a, **kw)
        res = cls.query().filter(and_(*[k == v for k, v in args]))
        try:
            res = res.all() if multiple else res.one()
            # res.one() will raise NoResultFound, while all() will
            # return an empty list.  This will make the response
            # uniform
            if not res:
                raise NoResultFound
        except NoResultFound: 
            raise NotFound, "%s with %s" % \
                (cls.__name__,
                 ",".join("%s=%s" % x for x in args))
        return res

    @classmethod
    def lookup(cls, *a, **kw):
        """
        Returns all objects which match the kw list, or primary keys
        that match the *a.
        """
        return cls._lookup(True, *a, **kw)

    @classmethod
    def one(cls, *a, **kw):
        """
        Same as lookup, but returns only one argument. 
        """
        return cls._lookup(False, *a, **kw)

    @classmethod
    def add(cls, key, *a):
        try:
            cls.one(key, *a)
        except NotFound:
            cls(key, *a)._commit()
    
    @classmethod
    def delete(cls, key, *a):
        try:
            cls.one(key, *a)._delete()
        except NotFound:
            pass
    
    @classmethod
    def get(cls, key):
        try:
            return cls.lookup(key)
        except NotFound:
            return []

class PayID(Sessionized, Base):
    __tablename__ = "authorize_pay_id"

    account_id    = Column(BigInteger, primary_key = True,
                           autoincrement = False)
    pay_id        = Column(BigInteger, primary_key = True,
                           autoincrement = False)

    def __repr__(self):
        return "<%s(%d)>" % (self.__class__.__name__, self.authorize_id)

    @classmethod
    def get_ids(cls, key):
        return [int(x.pay_id) for x in cls.get(key)]

class Bid(Sessionized, Base):
    __tablename__ = "bids"

    STATUS        = Enum("AUTH", "CHARGE", "REFUND", "VOID")
    
    # will be unique from authorize
    transaction   = Column(BigInteger, primary_key = True,
                           autoincrement = False)

    # identifying characteristics
    account_id    = Column(BigInteger, index = True, nullable = False)
    pay_id        = Column(BigInteger, index = True, nullable = False)
    thing_id      = Column(BigInteger, index = True, nullable = False)

    # breadcrumbs
    ip            = Column(Inet)
    date          = Column(DateTime(timezone = True), default = safunc.now(),
                           nullable = False)

    # bid information:
    bid           = Column(Float, nullable = False)
    charge        = Column(Float)
    refund        = Column(Float)

    status        = Column(Integer, nullable = False,
                           default = STATUS.AUTH)


    @classmethod
    def _new(cls, trans_id, user, pay_id, thing_id, bid):
        bid = Bid(trans_id, user, pay_id, 
                  thing_id, getattr(request, 'ip', '0.0.0.0'), bid = bid)
        bid._commit()
        return bid

    def set_status(self, status):
        if self.status != status:
            self.status = status
            self._commit()
        
    def auth(self):
        self.set_status(self.STATUS.AUTH)

    def void(self):
        self.set_status(self.STATUS.VOID)
        
    def charged(self):
        self.set_status(self.STATUS.CHARGE)

    def refund(self):
        self.set_status(self.STATUS.REFUND)

class PromoteDates(Sessionized, Base):
    __tablename__ = "promote_date"

    thing_name   = Column(String, primary_key = True, autoincrement = False)

    start_date = Column(Date(), nullable = False)
    end_date   = Column(Date(), nullable = False)

    actual_start = Column(DateTime(timezone = True))
    actual_end   = Column(DateTime(timezone = True))

    @classmethod
    def update(cls, thing, start_date, end_date):
        try:
            promo = cls.one(thing)
            promo.start_date = start_date.date()
            promo.end_date   = end_date.date()
            promo._commit()
        except NotFound:
            promo = cls._new(thing, start_date, end_date)

    @classmethod
    def log_start(cls, thing):
        promo = cls.one(thing)
        promo.actual_start = datetime.datetime.now(g.tz)
        promo._commit()

    @classmethod
    def log_end(cls, thing):
        promo = cls.one(thing)
        promo.actual_end = datetime.datetime.now(g.tz)
        promo._commit()

    @classmethod
    def for_date(cls, date):
        if isinstance(date, datetime.datetime):
            date = date.date()
        q = cls.query().filter(and_(cls.start_date <= date,
                                    cls.end_date > date))
        return q.all()
    
    @classmethod
    def for_date_range(cls, start_date, end_date):
        if isinstance(start_date, datetime.datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime.datetime):
            start_date = end_date.date()
        # Three cases to be included:
        # 1) start date is in the provided interval
        start_inside = and_(cls.start_date >= start_date,
                            cls.start_date <  end_date)
        # 2) end date is in the provided interval
        end_inside   = and_(cls.end_date   >= start_date,
                            cls.end_date   <  end_date)
        # 3) interval is a subset of a promoted interval
        surrounds    = and_(cls.start_date <= start_date,
                            cls.end_date   >= end_date)
            
        q = cls.query().filter(or_(start_inside, end_inside, surrounds))
        return q.all()
        

Base.metadata.create_all()

# negative transaction ids indicate no payment was actually involved.
# For now, we will raise if any positive transaction ids come up.
def get_account_info(user):
    raise NotImplementedError

def edit_profile(user, address, creditcard, pay_id = None):
    raise NotImplementedError

def refund_transaction(amount, user, trans_id):
    if trans_id > 0:
        raise NotImplementedError
    bid =  Bid.one(trans_id)
    bid.refund()

def void_transaction(user, trans_id):
    if trans_id > 0:
        raise NotImplementedError
    bid =  Bid.one(trans_id)
    bid.void()
 
def auth_transaction(amount, user, payid, thing):
    # use negative pay_ids to identify freebies, coupons, or anything
    # that doesn't require a CC.
    if payid < 0:
        trans_id = -thing._id
        # update previous freebie transactions if we can
        try:
            bid = Bid.one(thing_id = thing._id,
                          pay_id = payid)
            bid.bid = amount
            bid.auth()
        except NotFound:
            bid = Bid._new(trans_id, user, payid, thing._id, amount)
        return bid.transaction
        
    elif int(payid) in PayID.get_ids(user):
        raise NotImplementedError

def charge_transaction(user, trans_id):
    if trans_id > 0:
        raise NotImplementedError
    bid =  Bid.one(trans_id)
    bid.charged()
