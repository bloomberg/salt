# -*- coding: utf-8 -*-
'''
An "Always Disapproved" eauth interface, intended to stop you from authentication.
There is no reason to use this outside of multitenancy.

The goal is to have an auth interface where you cannot authenticate via the api.
Authenticating outside of api may allow you to have extra priviledges, that we want to lock down.
'''


def auth(username, password):  # pylint: disable=unused-argument
    '''
    Authenticate!
    '''
    return False
