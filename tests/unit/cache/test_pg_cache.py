# -*- coding: utf-8 -*-
'''
tests.unit.cache.test_pg_cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the Postgres Cache interface
'''

# Import Python libs
from __future__ import absolute_import, print_function, unicode_literals
import logging

# Import Salt Testing libs
from tests.support.mixins import LoaderModuleMockMixin
from tests.support.unit import TestCase, skipIf
from tests.support.mock import (
    MagicMock,
    NO_MOCK,
    NO_MOCK_REASON,
    patch
)

# Import Salt libs
import salt.cache.pg_cache as pg_cache
from salt.exceptions import SaltMasterError, SaltCacheError

import psycopg2

log = logging.getLogger(__name__)


@skipIf(NO_MOCK, NO_MOCK_REASON)
class PgCacheTestCase(TestCase, LoaderModuleMockMixin):

    def setup_loader_modules(self):
        return {
            pg_cache: {}
        }

    def test_store_value(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.execute.return_value = None
            self.assertEqual(pg_cache.store('x', 'y', 'z'), None)

    def test_store_raise(self):
        with patch('psycopg2.connect', MagicMock(side_effect=psycopg2.OperationalError)):
            with patch('salt.cache.pg_cache._exec_pg', MagicMock(side_effect=SaltMasterError)):
                with self.assertRaises(SaltCacheError):
                    pg_cache.store('i', 'like', 'tacos')

    def test_fetch_empty(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.fetchone.return_value = []
            self.assertEqual(pg_cache.fetch('x', 'y'), {})

    def test_fetch_value(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.fetchone.return_value = ['somedata']
            self.assertEqual(pg_cache.fetch('x', 'y'), 'somedata')

    def test_fetch_raise(self):
        with patch('psycopg2.connect', MagicMock(side_effect=psycopg2.OperationalError)):
            with patch('salt.cache.pg_cache._exec_pg', MagicMock(side_effect=SaltMasterError)):
                with self.assertRaises(SaltCacheError):
                    pg_cache.fetch('like', 'tacos')

    def test_flush_value(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):

            db_mock.return_value.__enter__.return_value.execute.return_value = None

            self.assertEqual(pg_cache.flush('x', 'y'), None)
            call_args, call_kwargs = db_mock.return_value.__enter__.return_value.execute.call_args
            expect_call_sql = 'DELETE FROM cache\n                 WHERE bank=%s AND key=%s'
            self.assertEqual(call_args[0], expect_call_sql)

            self.assertEqual(pg_cache.flush('x'), None)
            call_args, call_kwargs = db_mock.return_value.__enter__.return_value.execute.call_args
            expect_call_sql = 'DELETE FROM cache\n                 WHERE bank=%s'
            self.assertEqual(call_args[0], expect_call_sql)

    def test_flush_raise(self):
        with patch('psycopg2.connect', MagicMock(side_effect=psycopg2.OperationalError)):
            with patch('salt.cache.pg_cache._exec_pg', MagicMock(side_effect=SaltMasterError)):
                with self.assertRaises(SaltCacheError):
                    pg_cache.flush('surfs', 'up')
                with self.assertRaises(SaltCacheError):
                    pg_cache.flush('LHC')

    def test_contains_value(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.fetchone.return_value = [1]
            self.assertEqual(pg_cache.contains('x', 'y'), True)

    def test_does_not_contain_value(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.fetchone.return_value = []
            self.assertEqual(pg_cache.contains('x', 'y'), False)

    def test_contains_mulitple_values(self):
        db_mock = MagicMock()
        with patch.object(pg_cache, '_exec_pg', db_mock):
            db_mock.return_value.__enter__.return_value.fetchone.return_value = [2]
            self.assertEqual(pg_cache.contains('x', 'y'), False)

    def test_flush_raise(self):
        with patch('psycopg2.connect', MagicMock(side_effect=psycopg2.OperationalError)):
            with patch('salt.cache.pg_cache._exec_pg', MagicMock(side_effect=SaltMasterError)):
                with self.assertRaises(SaltCacheError):
                    pg_cache.contains('surfs', 'up')

    def test_clean_expires_raise(self):
        with patch('psycopg2.connect', MagicMock(side_effect=psycopg2.OperationalError)):
            with patch('salt.cache.pg_cache._exec_pg', MagicMock(side_effect=SaltMasterError)):
                with self.assertRaises(SaltCacheError):
                    pg_cache.clean_expired('gnarly')

    @patch('psycopg2.connect')
    def test_exec_pg_raise_op_error(self, mock_connect):
        mock_connect.side_effect = MagicMock(side_effect=psycopg2.OperationalError)
        with self.assertRaises(SaltMasterError):
            with pg_cache._exec_pg() as cur:
                pass

    @patch('psycopg2.connect')
    def test_exec_pg_rollback(self, mock_connect):
        mock_cur = mock_connect.return_value
        mock_cur.execute.side_effect = MagicMock(side_effect=psycopg2.DatabaseError)
        with pg_cache._exec_pg() as x:
            x.execute("failme")
            x.called_with("ROLLBACK")

    @patch('psycopg2.connect')
    def test_exec_pg_commit(self, mock_connect):
        mock_cur = mock_connect.return_value
        mock_cur.execute.return_value = None
        with pg_cache._exec_pg(commit=True) as x:
            x.execute("an insert statement")
            x.called_with("COMMIT")
