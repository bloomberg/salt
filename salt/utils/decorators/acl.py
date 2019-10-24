# -*- coding: utf-8 -*-
'''
Helpful decorators for module writing
'''

# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import functools
import logging
from boltons.funcutils import wraps

# Import salt libs
from salt.exceptions import CommandExecutionError, SaltConfigurationError, AuthorizationError
from salt.utils.ctx import RequestContext
from salt.log import LOG_LEVELS

# Import 3rd-party libs
from salt.ext import six

log = logging.getLogger(__name__)

class Authorize(object):
    '''
    This decorator will check if a given call is permitted based on the calling
    user and acl in place (if any).
    '''
    # we need to lazy-init ckminions via opts passed on from RequestContext, as
    # we don't have access to it here
    ckminions = None

    def __init__(self, tag, item, opts, pack):
        log.trace('Authorized decorator - tag %s applied', tag)
        self.tag = tag
        self.item = item
        self.opts = opts
        self.pack = pack

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # if an auth_check is present, enforce it
            if 'auth_check' not in RequestContext.current:
                log.trace('auth_check not in RequestContext. no-op')
                return f(*args, **kwargs)

            if RequestContext.current['auth_check'].get('auth_type') == 'user':
                log.trace('auth_check executing from user context. assuming root')
                return f(*args, **kwargs)

            auth_check = RequestContext.current['auth_check']
            auth_list = auth_check.get('auth_list', [])

            # a user auth type is implicitly root as such is not held to a auth_list
            if auth_check.get('auth_type') == 'user':
                log.trace('auth_type of user, permitting')
                return f(*args, **kwargs)

            # a user auth type is implicitly root as such is not held to a auth_list
            if RequestContext.current.get('recursive'):
                log.trace('auth_check is recursive, permitting')
                return f(*args, **kwargs)

            if not self.ckminions:
                # late import to avoid circular dependencies
                import salt.utils.minions
                self.ckminions = salt.utils.minions.CkMinions.factory(self.opts)

            # only apply acl if it is listed in auth_list tag set
            if self.tag not in auth_check.get('tags', []):
                log.trace('loader tag %s not in auth_check tags enforcement list. noop', self.tag)
                return f(*args, **kwargs)

            if self.tag == 'render':
                (render_check, recursive) = self.ckminions.render_check(auth_list, self.item)

                if not render_check or isinstance(render_check, dict) and 'error' in render_check:
                    log.error("current auth_check profile: %s", auth_check)
                    raise AuthorizationError('User \'{0}\' is not permissioned to execute renderer \'{1}\''.format(auth_check.get('username', 'UNKNOWN'), self.item))

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            # borrowed from salt.utils.decorators.Depends
            if self.tag == 'runners':
                (runner_check, recursive) = self.ckminions.runner_check(
                    auth_list,
                    self.item,
                    {'arg': args, 'kwargs': kwargs},
                )
                if not runner_check or isinstance(runner_check, dict) and 'error' in runner_check:
                    log.error("current auth_check profile: %s", auth_check)
                    raise AuthorizationError('User \'{0}\' is not permissioned to execute runner \'{1}\''.format(auth_check.get('username', 'UNKNOWN'), self.item))

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            if self.tag == 'module':
                # minion loader covers two usecases:
                # 1) master side orchestrations, including salutil.cmd special-cases for salt.state/salt.function
                # 2) minion side re-enforcment of provided authlist
                # orchestration enforcement is equivalent to minion side enforcement, as we know minion being acted on
                # is strictly equivalent to opts['id']. for saltutil.cmd we do not duplicate the work done by the master,
                # if a user is authorized to run saltutil.cmd he/she must still meet the equivalent acl work being done
                # in done in salt.master.Master.publish to successfully publish to those minions
                # chop off the _master masterminion id append, we treat real minion and master minion equivalently for acl purposes
                if self.opts.get('__role') == 'master' and self.opts['id'].endswith('_master'):
                    _id = self.opts['id'][0:-7]
                else:
                    _id = self.opts['id']
                (minion_check, recursive) = self.ckminions.auth_check(
                    auth_list,
                    self.item,
                    [args, kwargs],
                    _id,
                    'list',
                    minions=[_id],
                    # always accept find_job
                    whitelist=['saltutil.find_job', 'saltutil.is_running', 'grains.get', 'config.get', 'config.option'],
                )

                if not minion_check or isinstance(minion_check, dict) and 'error' in minion_check:
                    # Authorization error occurred. Do not continue.
                    if auth_check == 'eauth' and not auth_list and 'username' in extra and 'eauth' in extra:
                        log.debug('Auth configuration for eauth "%s" and user "%s" is empty', extra['eauth'], extra['username'])
                    log.error("current auth_check profile: %s", auth_check)
                    raise AuthorizationError('User \'{0}\' is not permissioned to execute module function \'{1}\' on minion \'{2}\''.format(auth_check.get('username', 'UNKNOWN'), self.item, _id))

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            # this invocation is the default for lazyloader tags that are unenforced, i.e. no-op
            return f(*args, **kwargs)

        # proxy some values from the real loader
        for (dunder, func)  in self.pack.items():
            wrapper.__globals__[dunder] = func

        wrapper.__globals__['__opts__'] = self.opts

        return wrapper

authorize = Authorize
