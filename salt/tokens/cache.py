# -*- coding: utf-8 -*-
'''
Provide token storage using the salt.cache interface

The token data is pretty simple and can be stored using any key value pair system.
Therefore, we can leverage the known salt.cache backends to store that data instead
of having to continuously write new salt.token backends that use similar backend data stores and
configurations.

To use the salt.token.cache interface, set `eauth_token: cache` in the master config. Specify
the cache backend by updating `eauth_cache_driver`. The example below uses the salt.cache.pg_cache
interface.

.. code-block:: yaml

    eauth_tokens: cache
    eauth_cache_driver: pg_cache

If the cache backend needs extra configurations, set them as you would normally for the
targeted salt.cache interface.
'''
from __future__ import absolute_import, print_function, unicode_literals

import os
import logging
import hashlib

import salt.cache
import salt.exceptions

from salt.ext import six

log = logging.getLogger(__name__)

__virtualname__ = 'cache'


def mk_token(opts, tdata):
    '''
    Mint a new token using the config option hash_type and store tdata with
    'token' attribute set to the token.

    This module uses the hash of random 512 bytes as a token.

    :param opts: Salt master config options
    :param tdata: token data
    :returns: Token data with new token
    '''

    # TODO
    #   This should be moved to a util that allows more
    #   hash type control and centrally managed.
    hash_type = getattr(hashlib, opts.get('hash_type', 'md5'))
    new_token = six.text_type(hash_type(os.urandom(512)).hexdigest())
    tdata['token'] = new_token

    driver = opts.get('eauth_cache_driver', __opts__.get('eauth_cache_driver'))
    log.debug("mk_token using %s storing %s", driver, new_token)
    try:
        cache = salt.cache.Cache(opts, driver=driver)
        cache.store('tokens', new_token, tdata)
    except salt.exceptions.SaltCacheError as err:
        log.error(
            'Cannot mk_token from tokens cache using %s: %s',
            driver, err
        )
        return {}

    return tdata


def get_token(opts, token):
    '''
    Fetch the token data from the store.

    :param opts: Salt master config options
    :param token: Token value
    :returns: Token data if successful. Empty dict if failed.
    '''
    driver = opts.get('eauth_cache_driver', __opts__.get('eauth_cache_driver'))
    try:
        cache = salt.cache.Cache(opts, driver=driver)
        token = cache.fetch('tokens', token)
    except salt.exceptions.SaltCacheError as err:
        log.error(
            'Cannot get token %s from tokens cache using %s: %s',
            token, driver, err
        )
        return {}

    log.debug("get_token using %s returned %s", driver, token)
    return token


def rm_token(opts, token):
    '''
    Remove token from the store.

    :param opts: Salt master config options
    :param token: Token to remove
    '''
    driver = opts.get('eauth_cache_driver', __opts__.get('eauth_cache_driver'))
    log.debug("rm_token flushing using %s token %s", driver, token)
    try:
        cache = salt.cache.Cache(opts, driver=driver)
        cache.flush('tokens', token)
    except salt.exceptions.SaltCacheError as err:
        log.error(
            'Cannot rm token %s from tokens cache using %s: %s',
            token, driver, err
        )
    return {}


def list_tokens(opts):
    '''
    List all tokens in the store.

    :param opts: Salt master config options
    :returns: List of dicts (token_data)
    '''
    driver = opts.get('eauth_cache_driver', __opts__.get('eauth_cache_driver'))
    try:
        cache = salt.cache.Cache(opts, driver=driver)
        tokens = cache.list('tokens')
    except salt.exceptions.SaltCacheError as err:
        log.error(
            'Cannot list tokens from tokens cache using %s: %s',
            driver, err
        )
        return []

    log.debug("list_tokens using %s returned %s", driver, tokens)
    return tokens


def clean_expired_tokens(opts):
    '''
    Clean expired tokens

    :param opts:
        Salt master config options
    '''
    driver = opts.get('eauth_cache_driver', __opts__.get('eauth_cache_driver'))
    try:
        cache = salt.cache.Cache(opts, driver=driver)
        cache.clean_expired('tokens')
    except salt.exceptions.SaltCacheError as err:
        log.error(
            'Cannot clean expired tokens using %s: %s',
            driver, err
        )
