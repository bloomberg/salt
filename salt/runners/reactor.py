# -*- coding: utf-8 -*-
'''
A convenience system to manage reactors

Beginning in the 2017.7 release, the reactor runner requires that the reactor
system is running.  This is accomplished one of two ways, either
by having reactors configured or by including ``reactor`` in the
engine configuration for the Salt master.

    .. code-block:: yaml

    engines:
        - reactor

'''
# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import logging

# Import salt libs
import salt.config
import salt.utils.master
import salt.utils.reactor
import salt.syspaths
import salt.utils.event
import salt.utils.process
import salt.transport
from salt.ext.six import string_types

log = logging.getLogger(__name__)

__func_alias__ = {
    'list_': 'list',
}


def list_(saltenv='base', test=None):
    '''
    List currently configured reactors

    CLI Example:

    .. code-block:: bash

        salt-run reactor.list
    '''
    sevent = salt.utils.event.get_event(
            'master',
            __opts__['sock_dir'],
            __opts__['transport'],
            opts=__opts__,
            listen=True)

    master_key = salt.utils.master.get_master_key('root', __opts__)
    sevent.fire_event({'key': master_key}, 'salt/reactors/manage/list')

    results = sevent.get_event(wait=30, tag='salt/reactors/manage/list-results')

    reactors = results['reactors']
    return reactors


def add(event, reactors, saltenv='base', test=None):
    '''
    Add a new reactor

    CLI Example:

    .. code-block:: bash

        salt-run reactor.add 'salt/cloud/*/destroyed' reactors='/srv/reactor/destroy/*.sls'
    '''
    if isinstance(reactors, string_types):
        reactors = [reactors]

    sevent = salt.utils.event.get_event(
            'master',
            __opts__['sock_dir'],
            __opts__['transport'],
            opts=__opts__,
            listen=True)

    master_key = salt.utils.master.get_master_key('root', __opts__)
    sevent.fire_master({'event': event,
                        'reactors': reactors,
                        'key': master_key},
                        'salt/reactors/manage/add')

    res = sevent.get_event(wait=30, tag='salt/reactors/manage/add-complete')
    return res['result']


def delete(event, saltenv='base', test=None):
    '''
    Delete a reactor

    CLI Example:

    .. code-block:: bash

        salt-run reactor.delete 'salt/cloud/*/destroyed'
    '''
    sevent = salt.utils.event.get_event(
            'master',
            __opts__['sock_dir'],
            __opts__['transport'],
            opts=__opts__,
            listen=True)

    master_key = salt.utils.master.get_master_key('root', __opts__)
    sevent.fire_event({'event': event, 'key': master_key}, 'salt/reactors/manage/delete')

    res = sevent.get_event(wait=30, tag='salt/reactors/manage/delete-complete')
    return res['result']
