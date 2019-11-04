# -*- coding: utf-8 -*-
"""
Environments Pillar
=================

Introspection: to which environments does my minion belong?
Provides a pillar with the default name of `environments`
which contains a list of environments which match for a given minion.
This pillar doesnt just _emit_ which environments are associated with a
minion, it actually fully overrides the default behavior of evaluating
all top files of all environments to determine this, allowing you to support
many environments that define their own topfiles without collisions.

.. versionadded:: xxx

Command Line
------------

.. code-block:: bash

    salt-call pillar.get environment
    local:
        - foo
        - bar
        - baz

Configuring Environemnts Pillar
-----------------------------

.. code-block:: yaml

    ext_pillar:
      - environments:
          pillar_name: 'environments'

"""

# Import futures
from __future__ import absolute_import, print_function, unicode_literals

import os.path
import logging
import os
import os.path
from datetime import datetime

# Import Salt libs
import salt.utils.json

# Import 3rd-party libs
from salt.ext import six
from boltons.setutils import IndexedSet
import requests

__version__ = '0.0.1'

try:
    import hostinfo

    HAS_HOSTINFO = True
except ImportError:
    HAS_HOSTINFO = False


log = logging.getLogger(__name__)


def __virtual__():
    return HAS_HOSTINFO


# Implement a partial subclass that fetches from sor on HostLookupFailure
# unclear if this is necessary, the only things needing to be mapped at
# provision time are global (salt-core, lifecycle)
if HAS_HOSTINFO:

    class SorFallbackCache(hostinfo.HostCache):
        def __get_by_name(self, name_or_alias):
            try:
                return super(SorFallbackCache, self).__get_by_name(
                    name_or_alias
                )
            except HostLookupFailure:
                # we must simulate a bbcpu.lst line for HostEntry
                # TODO implement
                # ret = __salt__['bb_sor.query'](name_or_alias, key='hostname')
                raise HostLookupFailure

        def __get_by_node(self, node):
            try:
                return super(SorFallbackCache, self).__get_by_name(
                    name_or_alias
                )
            except HostLookupFailure:
                # we must simulate a bbcpu.lst line for HostEntry
                # TODO implement
                raise HostLookupFailure

    # we want to attempt a sor lookup if a node is missing from flat files
    setattr(hostinfo, '__cache', SorFallbackCache())

    # fix upstream bug that can trigger RecursionError
    def make_accessor(attr):
        def accessor(self):
            _attr = '_HostEntry__{}'.format(attr)
            value = getattr(self, _attr, None)
            if not value:
                updated_host = hostinfo._reload_host_with_jsons(self._HostEntry__name)
                if getattr(updated_host, _attr, None):
                    self.update(updated_host)

                    return getattr(self, _attr)

            return value

        return accessor

    for attr in ['cluster', 'parentcluster', 'stage', 'substage']:
        setattr(hostinfo.HostEntry, attr, make_accessor(attr))


def tenancy_groups_set(node):
    groups = IndexedSet()

    for tenancy in __opts__['evaporator']['tenancies']:
        try:
            if node.groups_set() & set(tenancy['groups']):
                groups.add(tenancy['name'])
        except KeyError:
            pass

    return groups


def global_tenancy_groups_set():
    groups = IndexedSet()

    for tenancy in __opts__['evaporator']['tenancies']:
        if tenancy['global']:
          try:
              groups.add(tenancy['name'])
          except KeyError:
              pass

    return groups


def resolve_node(minion_id):
    try:
        return hostinfo.host(minion_id)
    except hostinfo.HostLookupError:
        log.debug('%s minion not found via minion-id.', minion_id)

    # if we've gotten this far its an unknown node
    return None

def stage_envs(stage, envs):
    """
    Takes in an iterable of env names and prepends a stage to the beginning.
    Example:
        env = [salt-core, natm]
        stage = 'sn2'

        >> {'environments': ['salt-core-sn2', 'natm-sn2']}
    """
    stage = stage.lower() # stage must be lowercase
    staged_envs = ['{}-{}'.format(env, stage) for env in envs]
    return {'environments': staged_envs, 'tenancies': list(envs)}


# the goal here is to
# 1. if a local top for the given repo exists, include it
# 2. if not, include at minimum an empty dict/key so the node is considered in the environment
# all multitenancies are assumed to exist by /{base-path}/{name}-{stage}/ for SN2..S4
# file_roots mapping {name-stage} environment to the above roots exists
def ext_pillar(minion_id, pillar=None, *args):
    """
    A salt external pillar which provides the list of nodegroups of which the minion is a member.

    :param minion_id: used for compound matching nodegroups
    :param pillar: provided by salt in some contexts, but not used by environments ext_pillar
    :param pillar_name: optional name to use for the pillar, defaults to 'environments'
    :return: a dictionary which is included by the salt master in the pillars returned to the minion
    """
    global_tenancy_groups = global_tenancy_groups_set()

    # hostinfo resolving a node that is None will throw an error
    if not minion_id:
        return stage_envs('nostage', global_tenancy_groups)

    node = resolve_node(minion_id)

    if node is None:
        return stage_envs('nostage', global_tenancy_groups)

    node_stage = node.stage()
    
    if node_stage is None:
        return stage_envs('nostage', global_tenancy_groups)

    # any matching tenancy_group is a 1 to 1 association with environment
    # we use an IndexedSet to ensure global roots are always highest priority
    tenancies = IndexedSet(global_tenancy_groups | tenancy_groups_set(node))
    return stage_envs(node_stage, tenancies)
