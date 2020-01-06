# -*- coding: utf-8 -*-
'''
Cache plugin for PostgreSQL database.

Usage:

To use the `pgjsonb` cache interface:

.. code-block:: yaml

    cache: pgjsonb

Available configurations for `pgjsonb` cache interface:

.. code-block:: yaml

    cache.pgjsonb.host: 127.0.0.1
    cache.pgjsonb.port: 5432
    cache.pgjsonb.user: 'salt'
    cache.pgjsonb.pass: 'salt'
    cache.pgjsonb.db: 'salt'

Dependencies:

The PostgreSQL server must be 9.5 or later to accommodate proper upserting.

The `psycopg2-binary` library must be installed on the master:

.. code-block:: bash

    pip install psycopg2-binary

The following database schema must be in place before `pgjsonb` can function correctly:

.. code-block:: sql

    CREATE DATABASE  salt
    WITH ENCODING 'utf-8';

    DROP TABLE IF EXISTS cache;
    CREATE TABLE cache (
        bank        varchar(255) NOT NULL,
        key         varchar(255) NOT NULL,
        data        jsonb NOT NULL,
        created_at  timestamp NOT NULL DEFAULT now(),
        expires_at  timestamp);

    CREATE UNIQUE INDEX idx_cache_i ON cache (bank, key);
    CREATE INDEX idx_cache_bank ON cache (bank);
    CREATE INDEX idx_cache_key ON cache (key);
    CREATE INDEX idx_cache_expires ON cache (expires_at);
    CREATE INDEX idx_cache_data ON cache USING gin(data);
'''
from __future__ import absolute_import, print_function, unicode_literals

import logging
from contextlib import contextmanager
import datetime
import time

import salt.exceptions
import salt.serializers.json
from salt.ext import six

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

log = logging.getLogger(__name__)

__virtualname__ = 'pgjsonb'


def __virtual__():
    '''
    Confirm that a psycopg2 client is installed.
    '''
    if not HAS_POSTGRES:
        return (False, 'Could not import postgres cache; psycopg2 is not installed.')
    return __virtualname__


# pylint: disable=unused-argument
def init_kwargs(kwargs):
    '''
    Dumby init kwargs
    '''
    return {}


@contextmanager
def _exec_pg(autocommit=True):
    '''
    pg context manager
    '''
    port = __opts__.get('cache.pgjsonb.port', 5432)
    if not isinstance(port, six.integer_types):
        port = int(port)

    try:
        conn = psycopg2.connect(
               host=__opts__.get('cache.pgjsonb.host', 'localhost'),
               port=port,
               user=__opts__.get('cache.pgjsonb.user', 'salt'),
               password=__opts__.get('cache.pgjsonb.pass', 'salt'),
               database=__opts__.get('cache.pgjsonb.db', 'salt'),
               connection_factory=psycopg2.extras.LoggingConnection)
        conn.initialize(log)
        conn.set_session(autocommit=autocommit)

    except psycopg2.OperationalError as exc:
        raise salt.exceptions.SaltMasterError('pg cache could not connect to database: {exc}'.format(exc=exc))

    cursor = conn.cursor()

    try:
        yield cursor

        # post yield we haven't received an exception, so commit
        if not autocommit:
            cursor.execute('COMMIT')
    except psycopg2.DatabaseError as err:
        error = err.args
        log.error(six.text_type(error))
        cursor.execute('ROLLBACK')
        raise err
    finally:
        conn.close()


def store(bank, key, data, expires=None):
    '''
    Store a key value.
    '''
    store_sql = ('INSERT INTO cache '
                 '(bank, key, data, created_at, expires_at) '
                 'VALUES(%s, %s, %s, %s, %s) '
                 'ON CONFLICT (bank, key) DO UPDATE '
                 'SET data=EXCLUDED.data, expires_at=EXCLUDED.expires_at, created_at=NOW()')

    if expires:
        expires_at = expires
    elif isinstance(data, dict) and 'expire' in data:
        if isinstance(data['expire'], float):
            # only convert if unix timestamp
            expires_at = datetime.datetime.fromtimestamp(data['expire']).isoformat()
    else:
        expires_at = None

    if isinstance(data, dict) and 'start' in data:
        if isinstance(data['start'], float):
            # only convert if unix timestamp
            created_at = datetime.datetime.fromtimestamp(data['start']).isoformat()
    else:
        created_at = datetime.datetime.now()

    params = (bank,
              key,
              psycopg2.extras.Json(data),
              created_at,
              expires_at)

    log.trace("pgjsonb storing %s:%s:%s:%s:%s", bank, key, data, created_at, expires_at)
    try:
        with _exec_pg(autocommit=False) as cur:
            cur.execute(store_sql, params)
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not store cache with postgres cache: {}'.format(err))


def flush(bank, key=None):
    '''
    Remove the key from the cache bank with all the key content.
    '''
    params = [bank]
    del_sql = 'DELETE FROM cache WHERE bank=%s'

    if key is not None:
        del_sql += " AND key=%s"
        params.append(key)

    log.trace("pgjsonb flushing %s:%s", bank, key)
    try:
        with _exec_pg(autocommit=False) as cur:
            cur.execute(del_sql, params)
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not flush cache with postgres cache: {}'.format(err))


def fetch(bank, key):
    '''
    Fetch a key value.
    '''
    fetch_sql = 'SELECT data FROM cache WHERE bank=%s AND key=%s'
    try:
        with _exec_pg(autocommit=True) as cur:
            cur.execute(fetch_sql, (bank, key))
            data = cur.fetchone()
            if data:
                return data[0]
            return {}
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not fetch cache with postgres cache: {}'.format(err))


def list(bank):
    '''
    Return an iterable object containing all entries stored in the specified
    bank.
    '''
    ls_sql = 'SELECT key FROM cache WHERE bank=%s'
    log.trace("pgjsonb listing %s", bank)
    try:
        with _exec_pg(autocommit=True) as cur:
            cur.execute(ls_sql, (bank,))
            tuples = cur.fetchall()
            return [x[0] for x in tuples]
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not list cache with postgres cache: {}'.format(err))


def contains(bank, key):
    '''
    Checks if the specified bank contains the specified key.
    '''
    in_sql = 'SELECT COUNT(data) FROM cache WHERE bank=%s AND key=%s'
    log.trace("pgjsonb check if %s in %s", key, bank)
    try:
        with _exec_pg(autocommit=True) as cur:
            cur.execute(in_sql, (bank, key))
            data = cur.fetchone()
            if data and data[0] == 1:
                return True
            if data and data[0] > 1:
                log.error("Found multiple values for key %s in bank %s", key, bank)
                return False
            return False
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not run contains with postgres cache: {}'.format(err))


def updated(bank, key):
    '''
    Given a bank and key, return the epoch of the expires_at if set.
    '''
    updated_sql = 'SELECT expires_at FROM cache WHERE bank = %s AND key = %s'
    log.trace("pgjsonb returning epoh key %s at %s", key, bank)
    try:
        with _exec_pg(autocommit=True) as cur:
            cur.execute(updated_sql, (bank, key))
            data = cur.fetchone()
            if data and isinstance(data[0], datetime.date):
                return time.mktime(data[0].timetuple())
            return None
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not run updated with postgres cache: {}'.format(err))


def clean_expired(bank):
    '''
    Delete keys from a bank that has expired keys if the
    'expires_at' column is not null.
    '''
    expire_sql = 'DELETE FROM cache WHERE bank = %s AND expires_at <= NOW() AND expires_at IS NOT NULL'
    log.trace("pgjsonb removing expired keys at bank %s", bank)
    try:
        with _exec_pg(autocommit=False) as cur:
            cur.execute(expire_sql, (bank,))
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not clean up expired tokens with postgres cache: {}'.format(err))


def maintenance():
    '''
    if any maintenance is required, do it here
    for pg, this means refresh the materialized view
    '''
    lock_id = __opts__.get('cache.pgjsonb.lock_id', 12953546)
    if not isinstance(lock_id, six.integer_types):
        lock_id = int(lock_id)
    with _exec_pg(autocommit=False) as cur:
        try:
            # try to obtain exclusive transaction level advisory lock if available
            cur.execute('SELECT pg_try_advisory_xact_lock({})'.format(lock_id))
            ret_lock = cur.fetchone()
            if ret_lock and ret_lock[0]:
                # refresh view and sleep 30s
                cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY "cache_grains_ipv4_view"')
                log.debug('cache_grains_ipv4_view has been refreshed')
                time.sleep(30)
                return True
        except salt.exceptions.SaltMasterError as err:
            raise salt.exceptions.SaltCacheError('Could not execute cache with postgres cache: {}'.format(err))

        log.debug('Could not acquire advisory lock to refresh materialized view. no-op')
        return False

def query(sql, bind=None, autocommit=True):
    '''
    execute a sql/bind and return results
    todo: named cursor/scroll?
    '''
    try:
        with _exec_pg(autocommit=autocommit) as cur:
            cur.execute(sql, bind)
            return cur.fetchall()
    except salt.exceptions.SaltMasterError as err:
        raise salt.exceptions.SaltCacheError('Could not fetch cache with postgres cache: {}'.format(err))
