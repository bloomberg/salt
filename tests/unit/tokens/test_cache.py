# -*- coding: utf-8 -*-
'''
tests.unit.tokens.test_cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the tokens cache interface
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
import salt.cache
import salt.tokens.cache as cache
import salt.exceptions

log = logging.getLogger(__name__)

@skipIf(NO_MOCK, NO_MOCK_REASON)
class CacheTokenTestCase(TestCase, LoaderModuleMockMixin):

    def setup_loader_modules(self):
        return {
            cache: {
                '__opts__': { }
            }
        }

    @patch("salt.cache.Cache")
    def test_mk_token(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.store.return_value = None 
        res = cache.mk_token({}, {'test': 'test'})
        self.assertTrue('token' in res)

    @patch("salt.cache.Cache")
    def test_mk_token_raise(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.store.side_effect = MagicMock(side_effect=salt.exceptions.SaltCacheError)
        self.assertEqual(cache.mk_token({}, {'test': 'tests'}), {})

    @patch("salt.cache.Cache")
    def test_rm_token(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.flush.return_value = {}
        self.assertEqual(cache.rm_token({},'tacos'), {})

    @patch("salt.cache.Cache")
    def test_rm_token_raise(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.flush.side_effect = MagicMock(side_effect=salt.exceptions.SaltCacheError)
        self.assertEqual(cache.rm_token({}, 'tacos'), {})

    @patch("salt.cache.Cache")
    def test_get_token(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.fetch.return_value = 'are good'
        self.assertEqual(cache.get_token({},'tacos'), 'are good')

    @patch("salt.cache.Cache")
    def test_get_token_raise(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.fetch.side_effect = MagicMock(side_effect=salt.exceptions.SaltCacheError)
        self.assertEqual(cache.get_token({}, 'tacos'), {})

    @patch("salt.cache.Cache")
    def test_list_tokens(self, mock_cache):
        expect = ['tacos', 'are', 'good']
        mocked = mock_cache.return_value
        mocked.list.return_value = expect
        self.assertEqual(cache.list_tokens({}), expect)

    @patch("salt.cache.Cache")
    def test_list_tokens_raise(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.list.side_effect = MagicMock(side_effect=salt.exceptions.SaltCacheError)
        self.assertEqual(cache.list_tokens({}), [])

    @patch("salt.cache.Cache")
    def test_clean_expired_raise_saltcacheerror(self, mock_cache):
        mocked = mock_cache.return_value
        mocked.clean_expired.side_effect = MagicMock(side_effect=salt.exceptions.SaltCacheError)
        self.assertEqual(cache.clean_expired_tokens({}), None)
