# -*- coding: utf-8 -*-
'''
Helpful decorators for module writing
'''

# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import functools
import logging
import os.path
from boltons.funcutils import wraps

# Import salt libs
from salt.exceptions import CommandExecutionError, SaltConfigurationError
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

    def __init__(self, tag, item):
        # log.trace('Authorized decorator - tag %s applied', tag)
        log.debug('Authorized decorator - tag %s item %s applied', tag, item)
        self.tag = tag
        self.item = item

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # This is only for master side, will leave minions to be regulated by publisher_acl
            # if __grains__['id'] in __grains__['master']:
            if os.path.exists('/etc/salt/pki/master/minions'):
                log.debug('000000 salt/utils/decorators/acl.py on master, continue 000000')
            else:
                log.debug('000000 salt/utils/decorators/acl.py on minion, skip 000000')
                return f(*args, **kwargs)
            # if an auth_check is present, enforce it
            if 'auth_check' not in RequestContext.current:
                log.debug('auth_check not in RequestContext. no-op')
                return f(*args, **kwargs)

            auth_check = RequestContext.current['auth_check']
            # sample auth_check value:
            # auth_check: {
            #     'auth_list': ['@jobs', '@runner', 'test.ping'],
            #     'username': 'salt',
            #     'tags': ['states'], <== as set in salt/auth/__init__.py class LoadAuth def check_authentication
            #     'error': {}
            # }
            # RequestContext.current itself contains the current salt env
            log.debug('000000 Checked tags are: %s 000000', auth_check['tags'])
            log.debug('000000 auth list is: %s 000000', auth_check['auth_list'])

            if not self.ckminions:
                # late import to avoid circular dependencies
                import salt.utils.minions
                self.ckminions = salt.utils.minions.CkMinions(RequestContext.current['opts'])

            # only apply acl if it is listed in auth_list tag set
            if self.tag not in auth_check.get('tags', []):
                log.debug('loader tag %s not in auth_check tags enforcement list. noop', self.tag)
                return f(*args, **kwargs)

            if self.tag == 'runners':
                # return f(*args, **kwargs)
                runner_check = self.ckminions.runner_check(
                    auth_check.get('auth_list', []),
                    self.item,
                    {'arg': args, 'kwargs': kwargs},
                )

                log.debug('000000 tag: runners item: %s args: %s kwargs: %s runner_check result: %s 000000', self.item, args, kwargs, runner_check)

                if not runner_check:
                    return {'error': {'name': 'EauthAuthenticationError',
                                       'message': 'Authentication failure of type "eauth" occurred for '
                                                 'user {0}.'.format(auth_check['user'])}}
                elif isinstance(runner_check, dict) and 'error' in runner_check:
                    # A dictionary with an error name/message was handled by ckminions.runner_check
                    return runner_check

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            if self.tag == 'module':
                module_check = self.ckminions.spec_check(
                    auth_check.get('auth_list', []),
                    self.item,
                    {'arg': args, 'kwargs': kwargs},
                    'module',
                )

                log.debug('000000 tag: module item: %s args: %s kwargs: %s spec_check result: %s 000000', self.item, args, kwargs, module_check)

                if not module_check:
                    return {'error': {'name': 'EauthAuthenticationError',
                                       'message': 'Authentication failure of type "eauth" occurred for '
                                                 'user {0}.'.format(auth_check['user'])}}
                elif isinstance(module_check, dict) and 'error' in module_check:
                    # A dictionary with an error name/message was handled by ckminions.runner_check
                    return module_check

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            if self.tag == 'module' and False:
                # do the same stuff as above for minion...  ckminion will
                # likely need to be modified to support running minino side, it
                # might make assumptions about being on the master
                # also need to account for master and minion side minionmod invocation
                # return f(*args, **kwargs)
                minion_check = self.ckminions.auth_check(
                    auth_list,
                    clear_load['fun'],
                    clear_load['arg'],
                    clear_load['tgt'],
                    clear_load.get('tgt_type', 'glob'),
                    minions=minions,
                    # always accept find_job
                    whitelist=['saltutil.find_job'],
                )

                if not authorized:
                    # Authorization error occurred. Do not continue.
                    if auth_type == 'eauth' and not auth_list and 'username' in extra and 'eauth' in extra:
                        log.debug('Auth configuration for eauth "%s" and user "%s" is empty', extra['eauth'], extra['username'])
                    log.warning(err_msg)
                    return {'error': {'name': 'AuthorizationError',
                                      'message': 'Authorization error occurred.'}}

                elif isinstance(runner_check, dict) and 'error' in minion_check:
                    # A dictionary with an error name/message was handled by ckminions.runner_check
                    return minion_check

                # if we've made it here, we are good. call the func
                return f(*args, **kwargs)

            return f(*args, **kwargs)

        return wrapper

authorize = Authorize

"""
def authorize_runner(self, clear_load):
        '''
        Send a master control function back to the runner system
        '''
        # All runner ops pass through eauth
        auth_type, err_name, key, sensitive_load_keys = self._prep_auth_info(clear_load)

        # Authenticate
        auth_check = self.loadauth.check_authentication(clear_load, auth_type, key=key)
        error = auth_check.get('error')

        if error:
            # Authentication error occurred: do not continue.
            return {'error': error}

        # Authorize
        username = auth_check.get('username')
        if auth_type != 'user':
            runner_check = self.ckminions.runner_check(
                auth_check.get('auth_list', []),
                clear_load['fun'],
                clear_load.get('kwarg', {})
            )
            if not runner_check:
                return {'error': {'name': err_name,
                                   'message': 'Authentication failure of type "{0}" occurred for '
                                             'user {1}.'.format(auth_type, username)}}
            elif isinstance(runner_check, dict) and 'error' in runner_check:
                # A dictionary with an error name/message was handled by ckminions.runner_check
                return runner_check

            # No error occurred, consume sensitive settings from the clear_load if passed.
            for item in sensitive_load_keys:
                clear_load.pop(item, None)
        else:
            if 'user' in clear_load:
                username = clear_load['user']
                if salt.auth.AuthUser(username).is_sudo():
                    username = self.opts.get('user', 'root')
            else:
                username = salt.utils.user.get_user()

        # Authorized. Do the job!
        try:
            fun = clear_load.pop('fun')
            runner_client = salt.runner.RunnerClient(self.opts)
            return runner_client.asynchronous(fun,
                                              clear_load.get('kwarg', {}),
                                              username)
        except Exception as exc:
            log.error('Exception occurred while introspecting %s: %s', fun, exc)
            return {'error': {'name': exc.__class__.__name__,
                              'args': exc.args,
                              'message': six.text_type(exc)}}

    def wheel(self, clear_load):
        '''
        Send a master control function back to the wheel system
        '''
        # All wheel ops pass through eauth
        auth_type, err_name, key, sensitive_load_keys = self._prep_auth_info(clear_load)

        # Authenticate
        auth_check = self.loadauth.check_authentication(clear_load, auth_type, key=key)
        error = auth_check.get('error')

        if error:
            # Authentication error occurred: do not continue.
            return {'error': error}

        # Authorize
        username = auth_check.get('username')
        if auth_type != 'user':
            wheel_check = self.ckminions.wheel_check(
                auth_check.get('auth_list', []),
                clear_load['fun'],
                clear_load.get('kwarg', {})
            )
            if not wheel_check:
                return {'error': {'name': err_name,
                                  'message': 'Authentication failure of type "{0}" occurred for '
                                             'user {1}.'.format(auth_type, username)}}
            elif isinstance(wheel_check, dict) and 'error' in wheel_check:
                # A dictionary with an error name/message was handled by ckminions.wheel_check
                return wheel_check

            # No error occurred, consume sensitive settings from the clear_load if passed.
            for item in sensitive_load_keys:
                clear_load.pop(item, None)
        else:
            if 'user' in clear_load:
                username = clear_load['user']
                if salt.auth.AuthUser(username).is_sudo():
                    username = self.opts.get('user', 'root')
            else:
                username = salt.utils.user.get_user()

        # Authorized. Do the job!
        try:
            jid = salt.utils.jid.gen_jid(self.opts)
            fun = clear_load.pop('fun')
            tag = tagify(jid, prefix='wheel')
            data = {'fun': "wheel.{0}".format(fun),
                    'jid': jid,
                    'tag': tag,
                    'user': username}

            self.event.fire_event(data, tagify([jid, 'new'], 'wheel'))
            ret = self.wheel_.call_func(fun, full_return=True, **clear_load)
            data['return'] = ret['return']
            data['success'] = ret['success']
            self.event.fire_event(data, tagify([jid, 'ret'], 'wheel'))
            return {'tag': tag,
                    'data': data}
        except Exception as exc:
            log.error('Exception occurred while introspecting %s: %s', fun, exc)
            data['return'] = 'Exception occurred in wheel {0}: {1}: {2}'.format(
                             fun,
                             exc.__class__.__name__,
                             exc,
            )
            data['success'] = False
            self.event.fire_event(data, tagify([jid, 'ret'], 'wheel'))
            return {'tag': tag,
                    'data': data}


    def publish(self, clear_load):
        '''
        This method sends out publications to the minions, it can only be used
        by the LocalClient.
        '''
        extra = clear_load.get('kwargs', {})

        publisher_acl = salt.acl.PublisherACL(self.opts['publisher_acl_blacklist'])

        if publisher_acl.user_is_blacklisted(clear_load['user']) or \
                publisher_acl.cmd_is_blacklisted(clear_load['fun']):
            log.error(
                '%s does not have permissions to run %s. Please contact '
                'your local administrator if you believe this is in '
                'error.\n', clear_load['user'], clear_load['fun']
            )
            return {'error': {'name': 'AuthorizationError',
                              'message': 'Authorization error occurred.'}}

        # Retrieve the minions list
        delimiter = clear_load.get('kwargs', {}).get('delimiter', DEFAULT_TARGET_DELIM)
        _res = self.ckminions.check_minions(
            clear_load['tgt'],
            clear_load.get('tgt_type', 'glob'),
            delimiter
        )
        minions = _res.get('minions', list())
        missing = _res.get('missing', list())
        ssh_minions = _res.get('ssh_minions', False)

        # Check for external auth calls and authenticate
        auth_type, err_name, key, sensitive_load_keys = self._prep_auth_info(extra)
        if auth_type == 'user':
            auth_check = self.loadauth.check_authentication(clear_load, auth_type, key=key)
        else:
            auth_check = self.loadauth.check_authentication(extra, auth_type)

        # Setup authorization list variable and error information
        auth_list = auth_check.get('auth_list', [])
        err_msg = 'Authentication failure of type "{0}" occurred.'.format(auth_type)

        if auth_check.get('error'):
            # Authentication error occurred: do not continue.
            log.warning(err_msg)
            return {'error': {'name': 'AuthenticationError',
                              'message': 'Authentication error occurred.'}}

        # All Token, Eauth, and non-root users must pass the authorization check
        if auth_type != 'user' or (auth_type == 'user' and auth_list):
            # Authorize the request
            authorized = self.ckminions.auth_check(
                auth_list,
                clear_load['fun'],
                clear_load['arg'],
                clear_load['tgt'],
                clear_load.get('tgt_type', 'glob'),
                minions=minions,
                # always accept find_job
                whitelist=['saltutil.find_job'],
            )

            if not authorized:
                # Authorization error occurred. Do not continue.
                if auth_type == 'eauth' and not auth_list and 'username' in extra and 'eauth' in extra:
                    log.debug('Auth configuration for eauth "%s" and user "%s" is empty', extra['eauth'], extra['username'])
                log.warning(err_msg)
                return {'error': {'name': 'AuthorizationError',
                                  'message': 'Authorization error occurred.'}}

            # Perform some specific auth_type tasks after the authorization check
            if auth_type == 'token':
                username = auth_check.get('username')
                clear_load['user'] = username
                log.debug('Minion tokenized user = "%s"', username)
            elif auth_type == 'eauth':
                # The username we are attempting to auth with
                clear_load['user'] = self.loadauth.load_name(extra)

        # If we order masters (via a syndic), don't short circuit if no minions
        # are found
        if not self.opts.get('order_masters'):
            # Check for no minions
            if not minions:
                return {
                    'enc': 'clear',
                    'load': {
                        'jid': None,
                        'minions': minions,
                        'error': 'Master could not resolve minions for target {0}'.format(clear_load['tgt'])
                    }
                }
        if extra.get('batch', None):
            return self.publish_batch(clear_load, extra, minions, missing)

        jid = self._prep_jid(clear_load, extra)
        if jid is None:
            return {'enc': 'clear',
                    'load': {'error': 'Master failed to assign jid'}}
        payload = self._prep_pub(minions, jid, clear_load, extra, missing)

        # Send it!
        self._send_ssh_pub(payload, ssh_minions=ssh_minions)
        self._send_pub(payload)

        return {
            'enc': 'clear',
            'load': {
                'jid': clear_load['jid'],
                'minions': minions,
                'missing': missing
            }
        }

    def _prep_auth_info(self, clear_load):
        sensitive_load_keys = []
        key = None
        if 'token' in clear_load:
            auth_type = 'token'
            err_name = 'TokenAuthenticationError'
            sensitive_load_keys = ['token']
        elif 'eauth' in clear_load:
            auth_type = 'eauth'
            err_name = 'EauthAuthenticationError'
            sensitive_load_keys = ['username', 'password']
        else:
            auth_type = 'user'
            err_name = 'UserAuthenticationError'
            key = self.key

        return auth_type, err_name, key, sensitive_load_keys

    def _prep_jid(self, clear_load, extra):
        '''
        Return a jid for this publication
        '''
        # the jid in clear_load can be None, '', or something else. this is an
        # attempt to clean up the value before passing to plugins
        passed_jid = clear_load['jid'] if clear_load.get('jid') else None
        nocache = extra.get('nocache', False)

        # Retrieve the jid
        fstr = '{0}.prep_jid'.format(self.opts['master_job_cache'])
        try:
            # Retrieve the jid
            jid = self.mminion.returners[fstr](nocache=nocache,
                                               passed_jid=passed_jid)
        except (KeyError, TypeError):
            # The returner is not present
            msg = (
                'Failed to allocate a jid. The requested returner \'{0}\' '
                'could not be loaded.'.format(fstr.split('.')[0])
            )
            log.error(msg)
            return {'error': msg}
        return jid

"""
