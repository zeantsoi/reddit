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
from datetime import datetime
import cPickle as pickle
from copy import deepcopy
import random

import sqlalchemy as sa
from sqlalchemy.databases import postgres

from r2.lib.utils import storage, storify, iters, Results, tup, TransSet
from r2.lib.services import AppServiceMonitor
import operators
from pylons import g, c
dbm = g.dbm

import logging
log_format = logging.Formatter('sql: %(message)s')

max_val_len = 1000

transactions = TransSet()

BigInteger = postgres.PGBigInteger

MAX_THING_ID = 9223372036854775807 # http://www.postgresql.org/docs/8.3/static/datatype-numeric.html

def make_metadata(engine):
    metadata = sa.MetaData(engine)
    metadata.bind.echo = g.sqlprinting
    return metadata

def create_table(table, index_commands=None):
    t = table
    if g.db_create_tables:
        #@@hackish?
        if not t.bind.has_table(t.name):
            t.create(checkfirst = False)
            if index_commands:
                for i in index_commands:
                    t.bind.execute(i)

def index_str(table, name, on, where = None):
    index_str = 'create index idx_%s_' % name
    index_str += table.name
    index_str += ' on '+ table.name + ' (%s)' % on
    if where:
        index_str += ' where %s' % where
    return index_str


def index_commands(table, type):
    commands = []

    if type == 'thing':
        commands.append(index_str(table, 'id', 'thing_id'))
        commands.append(index_str(table, 'date', 'date'))
        commands.append(index_str(table, 'deleted_spam', 'deleted, spam'))
        commands.append(index_str(table, 'hot', 'hot(ups, downs, date), date'))
        commands.append(index_str(table, 'score', 'score(ups, downs), date'))
        commands.append(index_str(table, 'controversy', 'controversy(ups, downs), date'))
    elif type == 'data':
        commands.append(index_str(table, 'id', 'thing_id'))
        commands.append(index_str(table, 'thing_id', 'thing_id'))
        commands.append(index_str(table, 'key_value', 'key, substring(value, 1, %s)' \
                                  % max_val_len))

        #lower name
        commands.append(index_str(table, 'lower_key_value', 'key, lower(value)',
                                  where = "key = 'name'"))
        #ip
        commands.append(index_str(table, 'ip_network', 'ip_network(value)',
                                  where = "key = 'ip'"))
        #base_url
        commands.append(index_str(table, 'base_url', 'base_url(lower(value))',
                                  where = "key = 'url'"))
    elif type == 'rel':
        commands.append(index_str(table, 'thing1_name_date', 'thing1_id, name, date'))
        commands.append(index_str(table, 'thing2_name_date', 'thing2_id, name, date'))
        commands.append(index_str(table, 'thing1_id', 'thing1_id'))
        commands.append(index_str(table, 'thing2_id', 'thing2_id'))
        commands.append(index_str(table, 'name', 'name'))
        commands.append(index_str(table, 'date', 'date'))
    else:
        print "unknown index_commands() type %s" % type

    return commands

def get_type_table(metadata):
    table = sa.Table(g.db_app_name + '_type', metadata,
                     sa.Column('id', sa.Integer, primary_key = True),
                     sa.Column('name', sa.String, nullable = False))
    return table

def get_rel_type_table(metadata):
    table = sa.Table(g.db_app_name + '_type_rel', metadata,
                     sa.Column('id', sa.Integer, primary_key = True),
                     sa.Column('type1_id', sa.Integer, nullable = False),
                     sa.Column('type2_id', sa.Integer, nullable = False),
                     sa.Column('name', sa.String, nullable = False))
    return table

def get_thing_table(metadata, name):
    table = sa.Table(g.db_app_name + '_thing_' + name, metadata,
                     sa.Column('thing_id', BigInteger, primary_key = True),
                     sa.Column('ups', sa.Integer, default = 0, nullable = False),
                     sa.Column('downs',
                               sa.Integer,
                               default = 0,
                               nullable = False),
                     sa.Column('deleted',
                               sa.Boolean,
                               default = False,
                               nullable = False),
                     sa.Column('spam',
                               sa.Boolean,
                               default = False,
                               nullable = False),
                     sa.Column('date',
                               sa.DateTime(timezone = True),
                               default = sa.func.now(),
                               nullable = False))
    return table

def get_data_table(metadata, name):
    data_table = sa.Table(g.db_app_name + '_data_' + name, metadata,
                          sa.Column('thing_id', BigInteger, nullable = False,
                                    primary_key = True),
                          sa.Column('key', sa.String, nullable = False,
                                    primary_key = True),
                          sa.Column('value', sa.String),
                          sa.Column('kind', sa.String))
    return data_table

def get_rel_table(metadata, name):
    rel_table = sa.Table(g.db_app_name + '_rel_' + name, metadata,
                         sa.Column('rel_id', BigInteger, primary_key = True),
                         sa.Column('thing1_id', BigInteger, nullable = False),
                         sa.Column('thing2_id', BigInteger, nullable = False),
                         sa.Column('name', sa.String, nullable = False),
                         sa.Column('date', sa.DateTime(timezone = True),
                                   default = sa.func.now(), nullable = False),
                         sa.UniqueConstraint('thing1_id', 'thing2_id', 'name'))
    return rel_table

#get/create the type tables
def make_type_table():
    metadata = make_metadata(dbm.type_db)
    table = get_type_table(metadata)
    create_table(table)
    return table
type_table = make_type_table()

def make_rel_type_table():
    metadata = make_metadata(dbm.relation_type_db)
    table = get_rel_type_table(metadata)
    create_table(table)
    return table
rel_type_table = make_rel_type_table()

#lookup dicts
types_id = {}
types_name = {}
rel_types_id = {}
rel_types_name = {}

def check_type(table, selector, insert_vals):
    #check for type in type table, create if not existent
    r = table.select(selector).execute().fetchone()
    if not r:
        r = table.insert().execute(**insert_vals)
        type_id = r.last_inserted_ids()[0]
    else:
        type_id = r.id
    return type_id

#make the thing tables
def build_thing_tables():
    for name, engines in dbm.things.iteritems():
        type_id = check_type(type_table,
                             type_table.c.name == name,
                             dict(name = name))

        tables = []
        for engine in engines:
            metadata = make_metadata(engine)

            #make thing table
            thing_table = get_thing_table(metadata, name)
            create_table(thing_table,
                         index_commands(thing_table, 'thing'))

            #make data tables
            data_table = get_data_table(metadata, name)
            create_table(data_table,
                         index_commands(data_table, 'data'))

            tables.append((thing_table, data_table))

        thing = storage(type_id = type_id,
                        name = name,
                        avoid_master_reads = dbm.avoid_master_reads.get(name),
                        tables = tables)

        types_id[type_id] = thing
        types_name[name] = thing
build_thing_tables()

#make relation tables
def build_rel_tables():
    for name, (type1_name, type2_name, engines) in dbm.relations.iteritems():
        type1_id = types_name[type1_name].type_id
        type2_id = types_name[type2_name].type_id
        type_id = check_type(rel_type_table,
                             rel_type_table.c.name == name,
                             dict(name = name,
                                  type1_id = type1_id,
                                  type2_id = type2_id))

        tables = []
        for engine in engines:
            metadata = make_metadata(engine)

            #relation table
            rel_table = get_rel_table(metadata, name)
            create_table(rel_table, index_commands(rel_table, 'rel'))

            #make thing tables
            rel_t1_table = get_thing_table(metadata, type1_name)
            if type1_name == type2_name:
                rel_t2_table = rel_t1_table
            else:
                rel_t2_table = get_thing_table(metadata, type2_name)

            #build the data
            rel_data_table = get_data_table(metadata, 'rel_' + name)
            create_table(rel_data_table,
                         index_commands(rel_data_table, 'data'))

            tables.append((rel_table,
                           rel_t1_table,
                           rel_t2_table,
                           rel_data_table))

        rel = storage(type_id = type_id,
                      type1_id = type1_id,
                      type2_id = type2_id,
                      avoid_master_reads = dbm.avoid_master_reads.get(name),
                      name = name,
                      tables = tables)

        rel_types_id[type_id] = rel
        rel_types_name[name] = rel
build_rel_tables()

def get_type_id(name):
    return types_name[name][0]

def get_rel_type_id(name):
    return rel_types_name[name][0]

def get_write_table(tables):
    if g.disallow_db_writes:
        raise Exception("not so fast! writes are not allowed on this app.")
    else:
        return tables[0]

def get_read_table(tables):
    # short-cut for only one element
    if len(tables) == 1:
        return tables[0]

    #'t' is a list of engines itself. since we assume those engines
    #are on the same machine, just take the first one. len(ips) may be
    #< len(tables) if some tables are on the same host.
    ips = dict((t[0].bind.url.host, t) for t in tables)
    ip_loads = AppServiceMonitor.get_db_load(ips.keys())

    total_load = 0
    missing_loads = []
    no_connections = []
    have_loads = []

    for ip in ips:
        if ip not in ip_loads:
            missing_loads.append(ip)
        else:
            load, avg_load, conns, avg_conns, max_conns = ip_loads[ip]

            #prune high-connection machines
            #if conns < .9 * max_conns:
            max_load = max(load, avg_load)
            total_load += max_load
            have_loads.append((ip, max_load))
            #else:
            #    no_connections.append(ip)

    if total_load:
        avg_load = total_load / max(len(have_loads), 1)
        ip_weights = [(ip, 1 - load / total_load) for ip, load in have_loads]
    #if total_load is 0, which happens when have_loads is empty
    else:
        avg_load = 1.0
        ip_weights = [(ip, 1.0 / len(have_loads)) for ip, load in have_loads]

    if missing_loads or no_connections:
        #add in the missing load numbers with an average weight
        ip_weights.extend((ip, avg_load) for ip in missing_loads)

        #add in the over-connected machines with a 1% weight
        ip_weights.extend((ip, .01) for ip in no_connections)

    #rebalance the weights
    total_weight = sum(w[1] for w in ip_weights)
    ip_weights = [(ip, weight / total_weight)
                  for ip, weight in ip_weights]

    r = random.random()
    for ip, load in ip_weights:
        if r < load:
            # print "db ip: %s" % str(ips[ip][0].metadata.bind.url.host)
            return ips[ip]
        else:
            r = r - load

    #should never happen
    print 'yer stupid'
    return  random.choice(tables)

def get_table(kind, action, tables, avoid_master_reads = False):
    if action == 'write':
        #if this is a write, store the kind in the c.use_write_db dict
        #so that all future requests use the write db
        if not isinstance(c.use_write_db, dict):
            c.use_write_db = {}
        c.use_write_db[kind] = True

        return get_write_table(tables)
    elif action == 'read':
        #check to see if we're supposed to use the write db again
        if c.use_write_db and c.use_write_db.has_key(kind):
            return get_write_table(tables)
        else:
            if avoid_master_reads and len(tables) > 1:
                return get_read_table(tables[1:])
            return get_read_table(tables)


def get_thing_table(type_id, action = 'read' ):
    return get_table('t' + str(type_id), action,
                     types_id[type_id].tables,
                     avoid_master_reads = types_id[type_id].avoid_master_reads)

def get_rel_table(rel_type_id, action = 'read'):
    return get_table('r' + str(rel_type_id), action,
                     rel_types_id[rel_type_id].tables,
                     avoid_master_reads = rel_types_id[rel_type_id].avoid_master_reads)


#TODO does the type actually exist?
def make_thing(type_id, ups, downs, date, deleted, spam, id=None):
    table = get_thing_table(type_id, action = 'write')[0]

    params = dict(ups = ups, downs = downs,
                  date = date, deleted = deleted, spam = spam)

    if id:
        params['thing_id'] = id

    def do_insert(t):
        transactions.add_engine(t.bind)
        r = t.insert().execute(**params)
        new_id = r.last_inserted_ids()[0]
        new_r = r.last_inserted_params()
        for k, v in params.iteritems():
            if new_r[k] != v:
                raise CreationError, ("There's shit in the plumbing. " +
                                      "expected %s, got %s" % (params,  new_r))
        return new_id

    try:
        id = do_insert(table)
        params['thing_id'] = id
        return id
    except sa.exceptions.SQLError, e:
        if not 'IntegrityError' in e.message:
            raise
        # wrap the error to prevent db layer bleeding out
        raise CreationError, "Thing exists (%s)" % str(params)


def set_thing_props(type_id, thing_id, **props):
    table = get_thing_table(type_id, action = 'write')[0]

    if not props:
        return

    #use real columns
    def do_update(t):
        transactions.add_engine(t.bind)
        new_props = dict((t.c[prop], val) for prop, val in props.iteritems())
        u = t.update(t.c.thing_id == thing_id, values = new_props)
        u.execute()

    do_update(table)

def incr_thing_prop(type_id, thing_id, prop, amount):
    table = get_thing_table(type_id, action = 'write')[0]
    
    def do_update(t):
        transactions.add_engine(t.bind)
        u = t.update(t.c.thing_id == thing_id,
                     values={t.c[prop] : t.c[prop] + amount})
        u.execute()

    do_update(table)

class CreationError(Exception): pass

#TODO does the type exist?
#TODO do the things actually exist?
def make_relation(rel_type_id, thing1_id, thing2_id, name, date=None):
    table = get_rel_table(rel_type_id, action = 'write')[0]
    transactions.add_engine(table.bind)
    
    if not date: date = datetime.now(g.tz)
    try:
        r = table.insert().execute(thing1_id = thing1_id,
                                   thing2_id = thing2_id,
                                   name = name, 
                                   date = date)
        return r.last_inserted_ids()[0]
    except sa.exceptions.SQLError, e:
        if not 'IntegrityError' in e.message:
            raise
        # wrap the error to prevent db layer bleeding out
        raise CreationError, "Relation exists (%s, %s, %s)" % (name, thing1_id, thing2_id)
        

def set_rel_props(rel_type_id, rel_id, **props):
    t = get_rel_table(rel_type_id, action = 'write')[0]

    if not props:
        return

    #use real columns
    transactions.add_engine(t.bind)
    new_props = dict((t.c[prop], val) for prop, val in props.iteritems())
    u = t.update(t.c.rel_id == rel_id, values = new_props)
    u.execute()


def py2db(val, return_kind=False):
    if isinstance(val, bool):
        val = 't' if val else 'f'
        kind = 'bool'
    elif isinstance(val, (str, unicode)):
        kind = 'str'
    elif isinstance(val, (int, float, long)):
        kind = 'num'
    elif val is None:
        kind = 'none'
    else:
        kind = 'pickle'
        val = pickle.dumps(val)

    if return_kind:
        return (val, kind)
    else:
        return val

def db2py(val, kind):
    if kind == 'bool':
        val = True if val is 't' else False
    elif kind == 'num':
        try:
            val = int(val)
        except ValueError:
            val = float(val)
    elif kind == 'none':
        val = None
    elif kind == 'pickle':
        val = pickle.loads(val)

    return val

#TODO i don't need type_id
def set_data(table, type_id, thing_id, **vals):
    s = sa.select([table.c.key], sa.and_(table.c.thing_id == thing_id))

    transactions.add_engine(table.bind)
    keys = [x.key for x in s.execute().fetchall()]

    i = table.insert(values = dict(thing_id = thing_id))
    u = table.update(sa.and_(table.c.thing_id == thing_id,
                             table.c.key == sa.bindparam('key')))

    inserts = []
    for key, val in vals.iteritems():
        val, kind = py2db(val, return_kind=True)

        #TODO one update?
        if key in keys:
            u.execute(key = key, value = val, kind = kind)
        else:
            inserts.append({'key':key, 'value':val, 'kind': kind})

    #do one insert
    if inserts:
        i.execute(*inserts)

def incr_data_prop(table, type_id, thing_id, prop, amount):
    t = table
    transactions.add_engine(t.bind)
    u = t.update(sa.and_(t.c.thing_id == thing_id,
                         t.c.key == prop),
                 values={t.c.value : sa.cast(t.c.value, sa.Float) + amount})
    u.execute()

def fetch_query(table, id_col, thing_id):
    """pull the columns from the thing/data tables for a list or single
    thing_id"""
    single = False

    if not isinstance(thing_id, iters):
        single = True
        thing_id = (thing_id,)
    
    s = sa.select([table], sa.or_(*[id_col == tid
                                    for tid in thing_id]))
    r = s.execute().fetchall()
    return (r, single)

#TODO specify columns to return?
def get_data(table, thing_id):
    r, single = fetch_query(table, table.c.thing_id, thing_id)

    #if single, only return one storage, otherwise make a dict
    res = storage() if single else {}
    for row in r:
        val = db2py(row.value, row.kind)
        stor = res if single else res.setdefault(row.thing_id, storage())
        if single and row.thing_id != thing_id:
            raise ValueError, ("tdb_sql.py: there's shit in the plumbing." 
                               + " got %s, wanted %s" % (row.thing_id,
                                                         thing_id))
        stor[row.key] = val

    return res

def set_thing_data(type_id, thing_id, **vals):
    table = get_thing_table(type_id, action = 'write')[1]
    return set_data(table, type_id, thing_id, **vals)

def incr_thing_data(type_id, thing_id, prop, amount):
    table = get_thing_table(type_id, action = 'write')[1]
    return incr_data_prop(table, type_id, thing_id, prop, amount)    

def get_thing_data(type_id, thing_id):
    table = get_thing_table(type_id)[1]
    return get_data(table, thing_id)

def get_thing(type_id, thing_id):
    table = get_thing_table(type_id)[0]
    r, single = fetch_query(table, table.c.thing_id, thing_id)

    #if single, only return one storage, otherwise make a dict
    res = {} if not single else None
    for row in r:
        stor = storage(ups = row.ups,
                       downs = row.downs,
                       date = row.date,
                       deleted = row.deleted,
                       spam = row.spam)
        if single:
            res = stor
            # check that we got what we asked for
            if row.thing_id != thing_id:
                raise ValueError, ("tdb_sql.py: there's shit in the plumbing." 
                                    + " got %s, wanted %s" % (row.thing_id,
                                                              thing_id))
        else:
            res[row.thing_id] = stor
    return res

def set_rel_data(rel_type_id, thing_id, **vals):
    table = get_rel_table(rel_type_id, action = 'write')[3]
    return set_data(table, rel_type_id, thing_id, **vals)

def incr_rel_data(rel_type_id, thing_id, prop, amount):
    table = get_rel_table(rel_type_id, action = 'write')[3]
    return incr_data_prop(table, rel_type_id, thing_id, prop, amount)

def get_rel_data(rel_type_id, rel_id):
    table = get_rel_table(rel_type_id)[3]
    return get_data(table, rel_id)

def get_rel(rel_type_id, rel_id):
    r_table = get_rel_table(rel_type_id)[0]
    r, single = fetch_query(r_table, r_table.c.rel_id, rel_id)
    
    res = {} if not single else None
    for row in r:
        stor = storage(thing1_id = row.thing1_id,
                       thing2_id = row.thing2_id,
                       name = row.name,
                       date = row.date)
        if single:
            res = stor
        else:
            res[row.rel_id] = stor
    return res

def del_rel(rel_type_id, rel_id):
    tables = get_rel_table(rel_type_id, action = 'write')
    table = tables[0]
    data_table = tables[3]

    transactions.add_engine(table.bind)
    transactions.add_engine(data_table.bind)

    table.delete(table.c.rel_id == rel_id).execute()
    data_table.delete(data_table.c.thing_id == rel_id).execute()

def sa_op(op):
    #if BooleanOp
    if isinstance(op, operators.or_):
        return sa.or_(*[sa_op(o) for o in op.ops])
    elif isinstance(op, operators.and_):
        return sa.and_(*[sa_op(o) for o in op.ops])

    #else, assume op is an instance of op
    if isinstance(op, operators.eq):
        fn = lambda x,y: x == y
    elif isinstance(op, operators.ne):
        fn = lambda x,y: x != y
    elif isinstance(op, operators.gt):
        fn = lambda x,y: x > y
    elif isinstance(op, operators.lt):
        fn = lambda x,y: x < y
    elif isinstance(op, operators.gte):
        fn = lambda x,y: x >= y
    elif isinstance(op, operators.lte):
        fn = lambda x,y: x <= y

    rval = tup(op.rval)

    if not rval:
        return '2+2=5'
    else:
        return sa.or_(*[fn(op.lval, v) for v in rval])

def translate_sort(table, column_name, lval = None, rewrite_name = True):
    if isinstance(lval, operators.query_func):
        fn_name = lval.__class__.__name__
        sa_func = getattr(sa.func, fn_name)
        return sa_func(translate_sort(table,
                                      column_name,
                                      lval.lval,
                                      rewrite_name))

    if rewrite_name:
        if column_name == 'id':
            return table.c.thing_id
        elif column_name == 'hot':
            return sa.func.hot(table.c.ups, table.c.downs, table.c.date)
        elif column_name == 'score':
            return sa.func.score(table.c.ups, table.c.downs)
        elif column_name == 'controversy':
            return sa.func.controversy(table.c.ups, table.c.downs)
    #else
    return table.c[column_name]

#TODO - only works with thing tables
def add_sort(sort, t_table, select):
    sort = tup(sort)

    prefixes = t_table.keys() if isinstance(t_table, dict) else None
    #sort the prefixes so the longest come first
    prefixes.sort(key = lambda x: len(x))
    cols = []

    def make_sa_sort(s):
        orig_col = s.col

        col = orig_col
        if prefixes:
            table = None
            for k in prefixes:
                if k and orig_col.startswith(k):
                    table = t_table[k]
                    col = orig_col[len(k):]
            if not table:
                table = t_table[None]
        else:
            table = t_table

        real_col = translate_sort(table, col)

        #TODO a way to avoid overlap?
        #add column for the sort parameter using the sorted name
        select.append_column(real_col.label(orig_col))

        #avoids overlap temporarily
        select.use_labels = True

        #keep track of which columns we added so we can add joins later
        cols.append((real_col, table))

        #default to asc
        return (sa.desc(real_col) if isinstance(s, operators.desc)
                else sa.asc(real_col))
        
    sa_sort = [make_sa_sort(s) for s in sort]

    s = select.order_by(*sa_sort)

    return s, cols

def translate_thing_value(rval):
    if isinstance(rval, operators.timeago):
        return sa.text("current_timestamp - interval '%s'" % rval.interval)
    else:
        return rval

#will assume parameters start with a _ for consistency
def find_things(type_id, get_cols, sort, limit, constraints):
    table = get_thing_table(type_id)[0]
    constraints = deepcopy(constraints)

    s = sa.select([table.c.thing_id.label('thing_id')])
    
    for op in operators.op_iter(constraints):
        #assume key starts with _
        #if key.startswith('_'):
        key = op.lval_name
        op.lval = translate_sort(table, key[1:], op.lval)
        op.rval = translate_thing_value(op.rval)

    for op in constraints:
        s.append_whereclause(sa_op(op))

    if sort:
        s, cols = add_sort(sort, {'_': table}, s)

    if limit:
        s = s.limit(limit)

    r = s.execute()
    return Results(r, lambda(row): row if get_cols else row.thing_id)

def translate_data_value(alias, op):
    lval = op.lval
    need_substr = False if isinstance(lval, operators.query_func) else True
    lval = translate_sort(alias, 'value', lval, False)

    #add the substring func
    if need_substr:
        lval = sa.func.substring(lval, 1, max_val_len)
    
    op.lval = lval
        
    #convert the rval to db types
    #convert everything to strings for pg8.3
    op.rval = tuple(str(py2db(v)) for v in tup(op.rval))

#TODO sort by data fields
#TODO sort by id wants thing_id
def find_data(type_id, get_cols, sort, limit, constraints):
    t_table, d_table = get_thing_table(type_id)
    constraints = deepcopy(constraints)

    used_first = False
    s = None
    need_join = False
    have_data_rule = False
    first_alias = d_table.alias()
    s = sa.select([first_alias.c.thing_id.label('thing_id')])#, distinct=True)

    for op in operators.op_iter(constraints):
        key = op.lval_name
        vals = tup(op.rval)

        if key == '_id':
            op.lval = first_alias.c.thing_id
        elif key.startswith('_'):
            need_join = True
            op.lval = translate_sort(t_table, key[1:], op.lval)
            op.rval = translate_thing_value(op.rval)
        else:
            have_data_rule = True
            id_col = None
            if not used_first:
                alias = first_alias
                used_first = True
            else:
                alias = d_table.alias()
                id_col = first_alias.c.thing_id

            if id_col:
                s.append_whereclause(id_col == alias.c.thing_id)
            
            s.append_column(alias.c.value.label(key))
            s.append_whereclause(alias.c.key == key)
            
            #add the substring constraint if no other functions are there
            translate_data_value(alias, op)

    for op in constraints:
        s.append_whereclause(sa_op(op))

    if not have_data_rule:
        raise Exception('Data queries must have at least one data rule.')

    #TODO in order to sort by data columns, this is going to need to be smarter
    if sort:
        need_join = True
        s, cols = add_sort(sort, {'_':t_table}, s)
            
    if need_join:
        s.append_whereclause(first_alias.c.thing_id == t_table.c.thing_id)

    if limit:
        s = s.limit(limit)

    r = s.execute()

    return Results(r, lambda(row): row if get_cols else row.thing_id)


def find_rels(rel_type_id, get_cols, sort, limit, constraints):
    tables = get_rel_table(rel_type_id)
    r_table, t1_table, t2_table, d_table = tables
    constraints = deepcopy(constraints)

    t1_table, t2_table = t1_table.alias(), t2_table.alias()

    s = sa.select([r_table.c.rel_id.label('rel_id')])
    need_join1 = ('thing1_id', t1_table)
    need_join2 = ('thing2_id', t2_table)
    joins_needed = set()

    for op in operators.op_iter(constraints):
        #vals = con.rval
        key = op.lval_name
        prefix = key[:4]
        
        if prefix in ('_t1_', '_t2_'):
            #not a thing attribute
            key = key[4:]

            if prefix == '_t1_':
                join = need_join1
                joins_needed.add(join)
            elif prefix == '_t2_':
                join = need_join2
                joins_needed.add(join)

            table = join[1]
            op.lval = translate_sort(table, key, op.lval)
            op.rval = translate_thing_value(op.rval)
            #ors = [sa_op(con, key, v) for v in vals]
            #s.append_whereclause(sa.or_(*ors))

        elif prefix.startswith('_'):
            op.lval = r_table.c[key[1:]]

        else:
            alias = d_table.alias()
            s.append_whereclause(r_table.c.rel_id == alias.c.thing_id)
            s.append_column(alias.c.value.label(key))
            s.append_whereclause(alias.c.key == key)

            translate_data_value(alias, op)

    for op in constraints:
        s.append_whereclause(sa_op(op))

    if sort:
        s, cols = add_sort(sort,
                           {'_':r_table, '_t1_':t1_table, '_t2_':t2_table},
                           s)
        
        #do we need more joins?
        for (col, table) in cols:
            if table == need_join1[1]:
                joins_needed.add(need_join1)
            elif table == need_join2[1]:
                joins_needed.add(need_join2)
        
    for j in joins_needed:
        col, table = j
        s.append_whereclause(r_table.c[col] == table.c.thing_id)    

    if limit:
        s = s.limit(limit)

    r = s.execute()
    return Results(r, lambda (row): (row if get_cols else row.rel_id))

if logging.getLogger('sqlalchemy').handlers:
    logging.getLogger('sqlalchemy').handlers[0].formatter = log_format

#inconsitencies:

#relationships assume their thing and data tables are in the same
#database. things don't make that assumption. in practice thing/data
#tables always go together.
#
#we create thing tables for a relationship's things that aren't on the
#same database as the relationship, although they're never used in
#practice. we could remove a healthy chunk of code if we removed that.
