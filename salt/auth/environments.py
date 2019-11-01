# -*- coding: utf-8 -*-
'''
BLP INTERNAL
leverage salt.pillar.environments to attempt to infer a non-default acl profile
if configured
'''

# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import logging

# Import salt libs
import salt.loader

log = logging.getLogger(__name__)

def acl(id=None, grains=None, **kwargs):
    pillars = salt.loader.pillars(__opts__, __salt__)
    # we have to fetch the environments mapped to a node indirectly like this
    # because we are in a chicken-egg situation of trying to figure out what ACL
    # is needed to RENDER the pillar
    #
    # we will return an amalgamation of all acl profiles that match unstaged environments
    # if they exist for the backend defined by the 'never' backend.

    ext = pillars['environments'](id, pillar=None)
    tenancies = ext.get('tenancies', [])

    acl = []

    for tenancy in tenancies:
        if tenancy in __opts__['external_auth']['never']:
            acl = acl + __opts__['external_auth']['never'][tenancy]

    # we dont want to return an empty list as there is an upstream 'is None' check
    # to use the defaults, [] would override that.
    return acl or None
