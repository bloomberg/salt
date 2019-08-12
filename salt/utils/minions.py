# -*- coding: utf-8 -*-
'''
This module contains routines used to verify the matcher against the minions
expected to return
'''

# Import python libs
from __future__ import absolute_import, unicode_literals
import os
import fnmatch
import re
import logging
import copy

# Import salt libs
import salt.payload
import salt.roster
import salt.utils.data
import salt.utils.files
import salt.utils.network
import salt.utils.stringutils
import salt.utils.versions
from salt.defaults import DEFAULT_TARGET_DELIM
from salt.exceptions import CommandExecutionError, SaltCacheError
import salt.auth.ldap
import salt.cache
from salt.ext import six

# Import 3rd-party libs
if six.PY3:
    import ipaddress
else:
    import salt.ext.ipaddress as ipaddress
HAS_RANGE = False
try:
    import seco.range  # pylint: disable=import-error
    HAS_RANGE = True
except ImportError:
    pass

log = logging.getLogger(__name__)

TARGET_REX = re.compile(
        r'''(?x)
        (
            (?P<engine>G|P|I|J|L|N|S|E|R)  # Possible target engines
            (?P<delimiter>(?<=G|P|I|J).)?  # Optional delimiter for specific engines
        @)?                                # Engine+delimiter are separated by a '@'
                                           # character and are optional for the target
        (?P<pattern>.+)$'''                # The pattern passed to the target engine
    )


def parse_target(target_expression):
    '''Parse `target_expressing` splitting it into `engine`, `delimiter`,
     `pattern` - returns a dict'''

    match = TARGET_REX.match(target_expression)
    if not match:
        log.warning('Unable to parse target "%s"', target_expression)
        ret = {
            'engine': None,
            'delimiter': None,
            'pattern': target_expression,
        }
    else:
        ret = match.groupdict()
    return ret


def get_minion_data(minion, opts):
    '''
    Get the grains/pillar for a specific minion.  If minion is None, it
    will return the grains/pillar for the first minion it finds.

    Return value is a tuple of the minion ID, grains, and pillar
    '''
    grains = None
    pillar = None
    if opts.get('minion_data_cache', False):
        cache = salt.cache.factory(opts)
        if minion is None:
            for id_ in cache.list('grains'):
                grains = cache.fetch('grains', id_)
                pillar = cache.fetch('pillar', id_)
                if grains is None:
                    continue
        else:
            grains = cache.fetch('grains', minion)
            pillar = cache.fetch('pillar', minion)
    return minion if minion else None, grains, pillar


def nodegroup_comp(nodegroup, nodegroups, skip=None, first_call=True):
    '''
    Recursively expand ``nodegroup`` from ``nodegroups``; ignore nodegroups in ``skip``

    If a top-level (non-recursive) call finds no nodegroups, return the original
    nodegroup definition (for backwards compatibility). Keep track of recursive
    calls via `first_call` argument
    '''
    expanded_nodegroup = False
    if skip is None:
        skip = set()
    elif nodegroup in skip:
        log.error('Failed nodegroup expansion: illegal nested nodegroup "%s"', nodegroup)
        return ''

    if nodegroup not in nodegroups:
        log.error('Failed nodegroup expansion: unknown nodegroup "%s"', nodegroup)
        return ''

    nglookup = nodegroups[nodegroup]
    if isinstance(nglookup, six.string_types):
        words = nglookup.split()
    elif isinstance(nglookup, (list, tuple)):
        words = nglookup
    else:
        log.error('Nodegroup \'%s\' (%s) is neither a string, list nor tuple',
                  nodegroup, nglookup)
        return ''

    skip.add(nodegroup)
    ret = []
    opers = ['and', 'or', 'not', '(', ')']
    for word in words:
        if not isinstance(word, six.string_types):
            word = six.text_type(word)
        if word in opers:
            ret.append(word)
        elif len(word) >= 3 and word.startswith('N@'):
            expanded_nodegroup = True
            ret.extend(nodegroup_comp(word[2:], nodegroups, skip=skip, first_call=False))
        else:
            ret.append(word)

    if ret:
        ret.insert(0, '(')
        ret.append(')')

    skip.remove(nodegroup)

    log.debug('nodegroup_comp(%s) => %s', nodegroup, ret)
    # Only return list form if a nodegroup was expanded. Otherwise return
    # the original string to conserve backwards compat
    if expanded_nodegroup or not first_call:
        return ret
    else:
        opers_set = set(opers)
        ret = words
        if (set(ret) - opers_set) == set(ret):
            # No compound operators found in nodegroup definition. Check for
            # group type specifiers
            group_type_re = re.compile('^[A-Z]@')
            regex_chars = ['(', '[', '{', '\\', '?''}])']
            if not [x for x in ret if '*' in x or group_type_re.match(x)]:
                # No group type specifiers and no wildcards.
                # Treat this as an expression.
                if [x for x in ret if x in [x for y in regex_chars if y in x]]:
                    joined = 'E@' + ','.join(ret)
                    log.debug(
                        'Nodegroup \'%s\' (%s) detected as an expression. '
                        'Assuming compound matching syntax of \'%s\'',
                        nodegroup, ret, joined
                    )
                else:
                    # Treat this as a list of nodenames.
                    joined = 'L@' + ','.join(ret)
                    log.debug(
                        'Nodegroup \'%s\' (%s) detected as list of nodenames. '
                        'Assuming compound matching syntax of \'%s\'',
                        nodegroup, ret, joined
                    )
                # Return data must be a list of compound matching components
                # to be fed into compound matcher. Enclose return data in list.
                return [joined]

        log.debug(
            'No nested nodegroups detected. Using original nodegroup '
            'definition: %s', nodegroups[nodegroup]
        )
        return ret


def mine_get(tgt, fun, tgt_type='glob', opts=None):
    '''
    Gathers the data from the specified minions' mine, pass in the target,
    function to look up and the target type
    '''
    ret = {}
    serial = salt.payload.Serial(opts)
    checker = CkMinions(opts)
    _res = checker.check_minions(
            tgt,
            tgt_type)
    minions = _res['minions']
    cache = salt.cache.factory(opts)
    for minion in minions:
        mdata = cache.fetch('mine', minion)
        if mdata is None:
            continue
        fdata = mdata.get(fun)
        if fdata:
            ret[minion] = fdata
    return ret


class CkMinions(object):
    '''
    Used to check what minions should respond from a target

    Note: This is a best-effort set of the minions that would match a target.
    Depending on master configuration (grains caching, etc.) and topology (syndics)
    the list may be a subset-- but we err on the side of too-many minions in this
    class.
    '''
    def __init__(self, opts):
        self.opts = opts
        self.serial = salt.payload.Serial(opts)
        self.cache = salt.cache.factory(opts)
        # TODO: this is actually an *auth* check
        if self.opts.get('transport', 'zeromq') in ('zeromq', 'tcp'):
            self.acc = 'minions'
        else:
            self.acc = 'accepted'

    @staticmethod
    def factory(opts):
        if opts['__role'] == 'minion':
            return RemoteCkMinions(opts)
        else:
            if opts['cache'] == 'pgjsonb':
                return PgJsonbCkMinions(opts)
            else:
                return CkMinions(opts)

    def _check_nodegroup_minions(self, expr, greedy):  # pylint: disable=unused-argument
        '''
        Return minions found by looking at nodegroups
        '''
        return self._check_compound_minions(nodegroup_comp(expr, self.opts['nodegroups']),
            DEFAULT_TARGET_DELIM,
            greedy)

    def _check_glob_minions(self, expr, greedy):  # pylint: disable=unused-argument
        '''
        Return the minions found by looking via globs
        '''
        return {'minions': fnmatch.filter(self._pki_minions(), expr),
                'missing': []}

    def _check_list_minions(self, expr, greedy):  # pylint: disable=unused-argument
        '''
        Return the minions found by looking via a list
        '''
        if isinstance(expr, six.string_types):
            expr = [m for m in expr.split(',') if m]
        minions = self._pki_minions()
        return {'minions': [x for x in expr if x in minions],
                'missing': [x for x in expr if x not in minions]}

    def _check_pcre_minions(self, expr, greedy):  # pylint: disable=unused-argument
        '''
        Return the minions found by looking via regular expressions
        '''
        reg = re.compile(expr)
        return {'minions': [m for m in self._pki_minions() if reg.match(m)],
                'missing': []}

    def _all_minions(self, expr=None):
        '''
        Return a list of all minions that have auth'd
        '''
        return {'minions': self._pki_minions(), 'missing': []}

    def _pki_minions(self):
        '''
        Retrieve complete minion list from PKI dir.
        Respects cache if configured
        '''
        # we include self.opts['id'] here as a special case to pick up the masterminion _master id
        minions = [self.opts['id']]
        pki_cache_fn = os.path.join(self.opts['pki_dir'], self.acc, '.key_cache')
        try:
            os.makedirs(os.path.dirname(pki_cache_fn))
        except OSError:
            pass
        try:
            if self.opts['key_cache'] and os.path.exists(pki_cache_fn):
                log.debug('Returning cached minion list')
                if six.PY2:
                    with salt.utils.files.fopen(pki_cache_fn) as fn_:
                        return self.serial.load(fn_)
                else:
                    with salt.utils.files.fopen(pki_cache_fn, mode='rb') as fn_:
                        return self.serial.load(fn_)
            else:
                for fn_ in salt.utils.data.sorted_ignorecase(os.listdir(os.path.join(self.opts['pki_dir'], self.acc))):
                    if not fn_.startswith('.') and os.path.isfile(os.path.join(self.opts['pki_dir'], self.acc, fn_)):
                        minions.append(fn_)
            return minions
        except OSError as exc:
            log.error(
                'Encountered OSError while evaluating minions in PKI dir: %s',
                exc
            )
            return minions

    def _check_cache_minions(self,
                             expr,
                             delimiter,
                             greedy,
                             search_type,
                             regex_match=False,
                             exact_match=False):
        '''
        Helper function to search for minions in master caches
        If 'greedy' return accepted minions that matched by the condition or absend in the cache.
        If not 'greedy' return the only minions have cache data and matched by the condition.
        '''
        cache_enabled = self.opts.get('minion_data_cache', False)

        def list_cached_minions():
            # we use grains as a equivalent for minion list
            return self.cache.list('grains')

        if greedy:
            minions = self._pki_minions()
        elif cache_enabled:
            minions = list_cached_minions()
        else:
            return {'minions': [],
                    'missing': []}

        if cache_enabled:
            if greedy:
                cminions = list_cached_minions()
            else:
                cminions = minions

            if not cminions:
                return {'minions': minions,
                        'missing': []}
            minions = set(minions)
            for id_ in cminions:

                if greedy and id_ not in minions:
                    continue
                mdata = self.cache.fetch(search_type, id_)
                if mdata is None:
                    if not greedy:
                        minions.remove(id_)
                    continue
                if not salt.utils.data.subdict_match(mdata,
                                                     expr,
                                                     delimiter=delimiter,
                                                     regex_match=regex_match,
                                                     exact_match=exact_match):
                    minions.remove(id_)
            minions = list(minions)
        return {'minions': minions,
                'missing': []}

    def _check_grain_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via grains
        '''
        return self._check_cache_minions(expr, delimiter, greedy, 'grains')

    def _check_grain_pcre_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via grains with PCRE
        '''
        return self._check_cache_minions(expr,
                                         delimiter,
                                         greedy,
                                         'grains',
                                         regex_match=True)

    def _check_pillar_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via pillar
        '''
        return self._check_cache_minions(expr, delimiter, greedy, 'pillar')

    def _check_pillar_pcre_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via pillar with PCRE
        '''
        return self._check_cache_minions(expr,
                                         delimiter,
                                         greedy,
                                         'pillar',
                                         regex_match=True)

    def _check_pillar_exact_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via pillar
        '''
        return self._check_cache_minions(expr,
                                         delimiter,
                                         greedy,
                                         'pillar',
                                         exact_match=True)

    def _check_ipcidr_minions(self, expr, greedy):
        '''
        Return the minions found by looking via ipcidr
        '''
        cache_enabled = self.opts.get('minion_data_cache', False)

        if greedy:
            minions = self._pki_minions()
        elif cache_enabled:
            minions = self.cache.list('grains')
        else:
            return {'minions': [],
                    'missing': []}

        if cache_enabled:
            if greedy:
                cminions = self.cache.list('grains')
            else:
                cminions = minions
            if cminions is None:
                return {'minions': minions,
                        'missing': []}

            tgt = expr
            try:
                # Target is an address?
                tgt = ipaddress.ip_address(tgt)
            except:  # pylint: disable=bare-except
                try:
                    # Target is a network?
                    tgt = ipaddress.ip_network(tgt)
                except:  # pylint: disable=bare-except
                    log.error('Invalid IP/CIDR target: %s', tgt)
                    return {'minions': [],
                            'missing': []}
            proto = 'ipv{0}'.format(tgt.version)

            minions = set(minions)
            for id_ in cminions:
                grains = self.cache.fetch('grains', id_)
                if grains is None:
                    if not greedy:
                        minions.remove(id_)
                    continue
                if grains is None or proto not in grains:
                    match = False
                elif isinstance(tgt, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
                    match = six.text_type(tgt) in grains[proto]
                else:
                    match = salt.utils.network.in_subnet(tgt, grains[proto])

                if not match and id_ in minions:
                    minions.remove(id_)

        return {'minions': list(minions),
                'missing': []}

    def _check_range_minions(self, expr, greedy):
        '''
        Return the minions found by looking via range expression
        '''
        if not HAS_RANGE:
            raise CommandExecutionError(
                'Range matcher unavailable (unable to import seco.range, '
                'module most likely not installed)'
            )
        if not hasattr(self, '_range'):
            self._range = seco.range.Range(self.opts['range_server'])
        try:
            return self._range.expand(expr)
        except seco.range.RangeException as exc:
            log.error(
                'Range exception in compound match: %s', exc
            )
            cache_enabled = self.opts.get('minion_data_cache', False)
            if greedy:
                return self._all_minions()
            elif cache_enabled:
                return {'minions': self.cache.list('grains'),
                        'missing': []}
            else:
                return {'minions': [],
                        'missing': []}

    def _check_compound_pillar_exact_minions(self, expr, delimiter, greedy):
        '''
        Return the minions found by looking via compound matcher

        Disable pillar glob matching
        '''
        return self._check_compound_minions(expr,
                                            delimiter,
                                            greedy,
                                            pillar_exact=True)

    def _check_compound_minions(self,
                                expr,
                                delimiter,
                                greedy,
                                pillar_exact=False):  # pylint: disable=unused-argument
        '''
        Return the minions found by looking via compound matcher
        '''
        if not isinstance(expr, six.string_types) and not isinstance(expr, (list, tuple)):
            log.error('Compound target that is neither string, list nor tuple')
            return {'minions': [], 'missing': []}
        minions = set(self._pki_minions())
        log.debug('expr: %s, delimiter: %s, minions: %s', expr, delimiter, minions)

        nodegroups = self.opts.get('nodegroups', {})

        if self.opts.get('minion_data_cache', False) or self.opts.get('__role') == 'minion':
            ref = {'G': self._check_grain_minions,
                   'P': self._check_grain_pcre_minions,
                   'I': self._check_pillar_minions,
                   'J': self._check_pillar_pcre_minions,
                   'L': self._check_list_minions,
                   'N': None,    # nodegroups should already be expanded
                   'S': self._check_ipcidr_minions,
                   'E': self._check_pcre_minions,
                   'R': self._all_minions}
            if pillar_exact:
                ref['I'] = self._check_pillar_exact_minions
                ref['J'] = self._check_pillar_exact_minions

            results = []
            unmatched = []
            opers = ['and', 'or', 'not', '(', ')']
            missing = []

            if isinstance(expr, six.string_types):
                words = expr.split()
            else:
                # we make a shallow copy in order to not affect the passed in arg
                words = expr[:]

            while words:
                word = words.pop(0)
                target_info = parse_target(word)

                # Easy check first
                if word in opers:
                    if results:
                        if results[-1] == '(' and word in ('and', 'or'):
                            log.error('Invalid beginning operator after "(": %s', word)
                            return {'minions': [], 'missing': []}
                        if word == 'not':
                            if not results[-1] in ('&', '|', '('):
                                results.append('&')
                            results.append('(')
                            results.append(six.text_type(set(minions)))
                            results.append('-')
                            unmatched.append('-')
                        elif word == 'and':
                            results.append('&')
                        elif word == 'or':
                            results.append('|')
                        elif word == '(':
                            results.append(word)
                            unmatched.append(word)
                        elif word == ')':
                            if not unmatched or unmatched[-1] != '(':
                                log.error('Invalid compound expr (unexpected '
                                          'right parenthesis): %s',
                                          expr)
                                return {'minions': [], 'missing': []}
                            results.append(word)
                            unmatched.pop()
                            if unmatched and unmatched[-1] == '-':
                                results.append(')')
                                unmatched.pop()
                        else:  # Won't get here, unless oper is added
                            log.error('Unhandled oper in compound expr: %s',
                                      expr)
                            return {'minions': [], 'missing': []}
                    else:
                        # seq start with oper, fail
                        if word == 'not':
                            results.append('(')
                            results.append(six.text_type(set(minions)))
                            results.append('-')
                            unmatched.append('-')
                        elif word == '(':
                            results.append(word)
                            unmatched.append(word)
                        else:
                            log.error(
                                'Expression may begin with'
                                ' binary operator: %s', word
                            )
                            return {'minions': [], 'missing': []}

                elif target_info and target_info['engine']:
                    if 'N' == target_info['engine']:
                        # if we encounter a node group, just evaluate it in-place
                        decomposed = nodegroup_comp(target_info['pattern'], nodegroups)
                        if decomposed:
                            words = decomposed + words
                        continue

                    engine = ref.get(target_info['engine'])
                    if not engine:
                        # If an unknown engine is called at any time, fail out
                        log.error(
                            'Unrecognized target engine "%s" for'
                            ' target expression "%s"',
                            target_info['engine'],
                            word,
                        )
                        return {'minions': [], 'missing': []}

                    engine_args = [target_info['pattern']]
                    if target_info['engine'] in ('G', 'P', 'I', 'J'):
                        engine_args.append(target_info['delimiter'] or ':')
                    engine_args.append(greedy)

                    _results = engine(*engine_args)
                    results.append(six.text_type(set(_results['minions'])))
                    missing.extend(_results['missing'])
                    if unmatched and unmatched[-1] == '-':
                        results.append(')')
                        unmatched.pop()

                else:
                    # The match is not explicitly defined, evaluate as a glob
                    _results = self._check_glob_minions(word, True)
                    results.append(six.text_type(set(_results['minions'])))
                    if unmatched and unmatched[-1] == '-':
                        results.append(')')
                        unmatched.pop()

            # Add a closing ')' for each item left in unmatched
            results.extend([')' for item in unmatched])

            results = ' '.join(results)
            log.debug('Evaluating final compound matching expr: %s',
                      results)
            try:
                minions = list(eval(results))  # pylint: disable=W0123
                return {'minions': minions, 'missing': missing}
            except Exception:
                log.error('Invalid compound target: %s', expr)
                return {'minions': [], 'missing': []}

        return {'minions': list(minions),
                'missing': []}

    def connected_ids(self, subset=None, show_ipv4=False, include_localhost=False):
        '''
        Return a set of all connected minion ids, optionally within a subset
        '''
        minions = set()
        if self.opts.get('minion_data_cache', False):
            search = self.cache.list('grains')
            if search is None:
                return minions
            addrs = salt.utils.network.local_port_tcp(int(self.opts['publish_port']))
            if '127.0.0.1' in addrs:
                # Add in the address of a possible locally-connected minion.
                addrs.discard('127.0.0.1')
                addrs.update(set(salt.utils.network.ip_addrs(include_loopback=include_localhost)))
            if subset:
                search = subset
            for id_ in search:
                try:
                    grains = self.cache.fetch('grains', id_)
                except SaltCacheError:
                    # If a SaltCacheError is explicitly raised during the fetch operation,
                    # permission was denied to open the cached data.p file. Continue on as
                    # in the releases <= 2016.3. (An explicit error raise was added in PR
                    # #35388. See issue #36867 for more information.
                    continue
                if grains is None:
                    continue
                for ipv4 in grains.get('ipv4', []):
                    if ipv4 == '127.0.0.1' and not include_localhost:
                        continue
                    if ipv4 == '0.0.0.0':
                        continue
                    if ipv4 in addrs:
                        if show_ipv4:
                            minions.add((id_, ipv4))
                        else:
                            minions.add(id_)
                        break
        return minions

    def check_minions(self,
                      expr,
                      tgt_type='glob',
                      delimiter=DEFAULT_TARGET_DELIM,
                      greedy=True):
        '''
        Check the passed regex against the available minions' public keys
        stored for authentication. This should return a set of ids which
        match the regex, this will then be used to parse the returns to
        make sure everyone has checked back in.
        '''

        try:
            if expr is None:
                expr = ''
            check_func = getattr(self, '_check_{0}_minions'.format(tgt_type), None)
            if tgt_type in ('grain',
                             'grain_pcre',
                             'pillar',
                             'pillar_pcre',
                             'pillar_exact',
                             'compound',
                             'compound_pillar_exact'):
                _res = check_func(expr, delimiter, greedy)
            else:
                _res = check_func(expr, greedy)
            _res['ssh_minions'] = False
            if self.opts.get('enable_ssh_minions', False) is True and isinstance('tgt', six.string_types):
                roster = salt.roster.Roster(self.opts, self.opts.get('roster', 'flat'))
                ssh_minions = roster.targets(expr, tgt_type)
                if ssh_minions:
                    _res['minions'].extend(ssh_minions)
                    _res['ssh_minions'] = True
        except Exception:
            log.exception(
                    'Failed matching available minions with %s pattern: %s',
                    tgt_type, expr)
            _res = {'minions': [], 'missing': []}
        return _res

    def _expand_matching(self, auth_entry):
        ref = {'G': 'grain',
               'P': 'grain_pcre',
               'I': 'pillar',
               'J': 'pillar_pcre',
               'L': 'list',
               'S': 'ipcidr',
               'E': 'pcre',
               'N': 'node',
               None: 'compound'}

        target_info = parse_target(auth_entry)
        if not target_info:
            log.error('Failed to parse valid target "%s"', auth_entry)

        v_matcher = ref.get(target_info['engine'])
        v_expr = target_info['pattern']

        _res = self.check_minions(v_expr, v_matcher)
        log.debug('_expand_matching v_expr: %s v_matcher: %s', v_expr, v_matcher)
        return set(_res['minions'])

    def validate_tgt(self, valid, expr, tgt_type, minions=None, expr_form=None):
        '''
        Return a Bool. This function returns if the expression sent in is
        within the scope of the valid expression
        '''
        # remember to remove the expr_form argument from this function when
        # performing the cleanup on this deprecation.
        if expr_form is not None:
            salt.utils.versions.warn_until(
                'Fluorine',
                'the target type should be passed using the \'tgt_type\' '
                'argument instead of \'expr_form\'. Support for using '
                '\'expr_form\' will be removed in Salt Fluorine.'
            )
            tgt_type = expr_form

        v_minions = self._expand_matching(valid)
        if minions is None:
            _res = self.check_minions(expr, tgt_type)
            minions = set(_res['minions'])
        else:
            minions = set(minions)
        d_bool = not bool(minions.difference(v_minions))
        log.debug("validate_tgt: valid: %s expr: %s tgt_type: %s minions: %s v_minons: %s d_bool: %s", valid, expr, tgt_type, minions, v_minions, d_bool)
        if len(v_minions) == len(minions) and d_bool:
            return True
        return d_bool

    def match_check(self, regex, fun):
        '''
        Validate a single regex to function comparison, the function argument
        can be a list of functions. It is all or nothing for a list of
        functions
        '''
        vals = []
        if isinstance(fun, six.string_types):
            fun = [fun]
        for func in fun:
            try:
                if re.match(regex, func):
                    vals.append(True)
                else:
                    vals.append(False)
            except Exception:
                log.error('Invalid regular expression: %s', regex)
        return vals and all(vals)

    def any_auth(self, form, auth_list, fun, arg, tgt=None, tgt_type='glob'):
        '''
        Read in the form and determine which auth check routine to execute
        '''
        # This function is only called from salt.auth.Authorize(), which is also
        # deprecated and will be removed in Neon.
        salt.utils.versions.warn_until(
            'Neon',
            'The \'any_auth\' function has been deprecated. Support for this '
            'function will be removed in Salt {version}.'
        )
        if form == 'publish':
            return self.auth_check(
                    auth_list,
                    fun,
                    arg,
                    tgt,
                    tgt_type)
        return self.spec_check(
                auth_list,
                fun,
                arg,
                form)

    def auth_check_expanded(self,
                            auth_list,
                            funs,
                            args,
                            tgt,
                            tgt_type='glob',
                            groups=None,
                            publish_validate=False):

        # Here's my thinking
        # 1. Retrieve anticipated targeted minions
        # 2. Iterate through each entry in the auth_list
        # 3. If it is a minion_id, check to see if any targeted minions match.
        #    If there is a match, check to make sure funs are permitted
        #    (if it's not a match we don't care about this auth entry and can
        #     move on)
        #    a. If funs are permitted, Add this minion_id to a new set of allowed minion_ids
        #       If funs are NOT permitted, can short-circuit and return FALSE
        #    b. At the end of the auth_list loop, make sure all targeted IDs
        #       are in the set of allowed minion_ids.  If not, return FALSE
        # 4. If it is a target (glob, pillar, etc), retrieve matching minions
        #    and make sure that ALL targeted minions are in the set.
        #    then check to see if the funs are permitted
        #    a. If ALL targeted minions are not in the set, then return FALSE
        #    b. If the desired fun doesn't mass the auth check with any
        #       auth_entry's fun, then return FALSE

        # NOTE we are not going to try to allow functions to run on partial
        # sets of minions.  If a user targets a group of minions and does not
        # have access to run a job on ALL of these minions then the job will
        # fail with 'Eauth Failed'.

        # The recommended workflow in that case will be for the user to narrow
        # his target.

        # This should cover adding the AD LDAP lookup functionality while
        # preserving the existing auth behavior.

        # Recommend we config-get this behind an entry called
        # auth.enable_expanded_auth_matching
        # and default to False
        v_tgt_type = tgt_type
        if tgt_type.lower() in ('pillar', 'pillar_pcre'):
            v_tgt_type = 'pillar_exact'
        elif tgt_type.lower() == 'compound':
            v_tgt_type = 'compound_pillar_exact'
        _res = self.check_minions(tgt, v_tgt_type)
        v_minions = set(_res['minions'])

        _res = self.check_minions(tgt, tgt_type)
        minions = set(_res['minions'])

        mismatch = bool(minions.difference(v_minions))
        # If the non-exact match gets more minions than the exact match
        # then pillar globbing or PCRE is being used, and we have a
        # problem
        if publish_validate:
            if mismatch:
                return False
        # compound commands will come in a list so treat everything as a list
        if not isinstance(funs, list):
            funs = [funs]
            args = [args]

        # Take the auth list and get all the minion names inside it
        allowed_minions = set()

        auth_dictionary = {}

        # Make a set, so we are guaranteed to have only one of each minion
        # Also iterate through the entire auth_list and create a dictionary
        # so it's easy to look up what functions are permitted
        for auth_list_entry in auth_list:
            if isinstance(auth_list_entry, six.string_types):
                for fun in funs:
                    # represents toplevel auth entry is a function.
                    # so this fn is permitted by all minions
                    if self.match_check(auth_list_entry, fun):
                        return True
                continue
            if isinstance(auth_list_entry, dict):
                if len(auth_list_entry) != 1:
                    log.info('Malformed ACL: %s', auth_list_entry)
                    continue
            allowed_minions.update(set(auth_list_entry.keys()))
            for key in auth_list_entry:
                for match in self._expand_matching(key):
                    if match in auth_dictionary:
                        auth_dictionary[match].extend(auth_list_entry[key])
                    else:
                        auth_dictionary[match] = auth_list_entry[key]

        allowed_minions_from_auth_list = set()
        for next_entry in allowed_minions:
            allowed_minions_from_auth_list.update(self._expand_matching(next_entry))
        # 'minions' here are all the names of minions matched by the target
        # if we take out all the allowed minions, and there are any left, then
        # the target includes minions that are not allowed by eauth
        # so we can give up here.
        if len(minions - allowed_minions_from_auth_list) > 0:
            return False

        try:
            for minion in minions:
                results = []
                for num, fun in enumerate(auth_dictionary[minion]):
                    results.append(self.match_check(fun, funs))
                if not any(results):
                    return False
            return True

        except TypeError:
            return False
        return False

    def auth_check(self,
                   auth_list,
                   funs,
                   args,
                   tgt,
                   tgt_type='glob',
                   groups=None,
                   publish_validate=False,
                   minions=None,
                   whitelist=None):
        '''
        Returns a bool which defines if the requested function is authorized.
        Used to evaluate the standard structure under external master
        authentication interfaces, like eauth, peer, peer_run, etc.
        '''
        if self.opts.get('auth.enable_expanded_auth_matching', False):
            return self.auth_check_expanded(auth_list, funs, args, tgt, tgt_type, groups, publish_validate)
        if publish_validate:
            v_tgt_type = tgt_type
            if tgt_type.lower() in ('pillar', 'pillar_pcre'):
                v_tgt_type = 'pillar_exact'
            elif tgt_type.lower() == 'compound':
                v_tgt_type = 'compound_pillar_exact'
            _res = self.check_minions(tgt, v_tgt_type)
            v_minions = set(_res['minions'])

            _res = self.check_minions(tgt, tgt_type)
            minions = set(_res['minions'])

            mismatch = bool(minions.difference(v_minions))
            # If the non-exact match gets more minions than the exact match
            # then pillar globbing or PCRE is being used, and we have a
            # problem
            if mismatch:
                return False
        # compound commands will come in a list so treat everything as a list
        if not isinstance(funs, list):
            funs = [funs]
            args = [args]
        try:
            for num, fun in enumerate(funs):
                if whitelist and fun in whitelist:
                    return True
                for ind in auth_list:
                    if isinstance(ind, six.string_types):
                        # Allowed for all minions
                        if self.match_check(ind, fun):
                            return True
                    elif isinstance(ind, dict):
                        if len(ind) != 1:
                            # Invalid argument
                            continue
                        valid = next(six.iterkeys(ind))
                        # Check if minions are allowed
                        if self.validate_tgt(
                            valid,
                            tgt,
                            tgt_type,
                            minions=minions):
                            # Minions are allowed, verify function in allowed list
                            fun_args = args[num]
                            fun_kwargs = fun_args[-1] if fun_args else None
                            if isinstance(fun_kwargs, dict) and '__kwarg__' in fun_kwargs:
                                fun_args = list(fun_args)  # copy on modify
                                del fun_args[-1]
                            else:
                                fun_kwargs = None
                            log.debug("auth_check: ind: %s fun: %s fun_args: %s fun_kwargs: %s", ind[valid], fun, fun_args, fun_kwargs)
                            if self.__fun_check(ind[valid], fun, fun_args, fun_kwargs):
                                return True
        except TypeError:
            return False
        return False

    def fill_auth_list_from_groups(self, auth_provider, user_groups, auth_list):
        '''
        Returns a list of authorisation matchers that a user is eligible for.
        This list is a combination of the provided personal matchers plus the
        matchers of any group the user is in.
        '''
        group_names = [item for item in auth_provider if item.endswith('%')]
        if group_names:
            for group_name in group_names:
                if group_name.rstrip("%") in user_groups:
                    for matcher in auth_provider[group_name]:
                        auth_list.append(matcher)
        return auth_list

    def fill_auth_list(self, auth_provider, name, groups, auth_list=None, permissive=None):
        '''
        Returns a list of authorisation matchers that a user is eligible for.
        This list is a combination of the provided personal matchers plus the
        matchers of any group the user is in.
        '''
        # we are making modifications, make sure we arent accidentally
        # introducing side effects
        auth_provider = copy.deepcopy(auth_provider)
        if auth_list is None:
            auth_list = []
        if permissive is None:
            permissive = self.opts.get('permissive_acl')
        name_matched = False
        for match in auth_provider:
            if match == '*' and not permissive:
                continue

            if match.endswith('%'):
                if match.rstrip('%') in groups:
                    auth_list.extend(auth_provider[match])
            else:
                if salt.utils.stringutils.expr_match(match, name):
                    name_matched = True
                    auth_list.extend(auth_provider[match])
        if not permissive and not name_matched and '*' in auth_provider:
            auth_list.extend(auth_provider['*'])
        # we special case @master to symbolically mean the current master
        # for minion mods rather then allowing $foo_master explicit node
        # assignment by id since the masterminion doesnt publish grains to cache
        for acl in auth_list:
            if isinstance(acl, dict) and '@master' in acl:
                acl[self.opts['id']] = acl['@master']
                del acl['@master']

        return auth_list

    def wheel_check(self, auth_list, fun, args):
        '''
        Check special API permissions
        '''
        return self.spec_check(auth_list, fun, args, 'wheel')

    def runner_check(self, auth_list, fun, args):
        '''
        Check special API permissions
        '''
        return self.spec_check(auth_list, fun, args, 'runner')

    def spec_check(self, auth_list, fun, args, form):
        '''
        Check special API permissions
        '''
        if not auth_list:
            return False
        if form != 'cloud':
            comps = fun.split('.')
            if len(comps) != 2:
                # Hint at a syntax error when command is passed improperly,
                # rather than returning an authentication error of some kind.
                # See Issue #21969 for more information.
                return {'error': {'name': 'SaltInvocationError',
                                  'message': 'A command invocation error occurred: Check syntax.'}}
            mod_name = comps[0]
            fun_name = comps[1]
        else:
            fun_name = mod_name = fun
        for ind in auth_list:
            if isinstance(ind, six.string_types):
                if ind[0] == '@':
                    if ind[1:] == mod_name or ind[1:] == form or ind == '@{0}s'.format(form):
                        return True
            elif isinstance(ind, dict):
                if len(ind) != 1:
                    continue
                valid = next(six.iterkeys(ind))
                if valid[0] == '@':
                    if valid[1:] == mod_name:
                        if self.__fun_check(ind[valid], fun_name, args.get('arg'), args.get('kwarg')):
                            return True
                    if valid[1:] == form or valid == '@{0}s'.format(form):
                        if self.__fun_check(ind[valid], fun, args.get('arg'), args.get('kwarg')):
                            return True
        return False

    def __fun_check(self, valid, fun, args=None, kwargs=None):
        '''
        Check the given function name (fun) and its arguments (args) against the list of conditions.
        '''
        if not isinstance(valid, list):
            valid = [valid]
        for cond in valid:
            # Function name match
            if isinstance(cond, six.string_types):
                if self.match_check(cond, fun):
                    return True
            # Function and args match
            elif isinstance(cond, dict):
                if len(cond) != 1:
                    # Invalid argument
                    continue
                fname_cond = next(six.iterkeys(cond))
                if self.match_check(fname_cond, fun):  # check key that is function name match
                    if self.__args_check(cond[fname_cond], args, kwargs):
                        return True
        return False

    def __args_check(self, valid, args=None, kwargs=None):
        '''
        valid is a dicts: {'args': [...], 'kwargs': {...}} or a list of such dicts.
        '''
        if not isinstance(valid, list):
            valid = [valid]
        for cond in valid:
            if not isinstance(cond, dict):
                # Invalid argument
                continue
            # whitelist args, kwargs
            cond_args = cond.get('args', [])
            good = True
            for i, cond_arg in enumerate(cond_args):
                if args is None or len(args) <= i:
                    good = False
                    break
                if cond_arg is None:  # None == '.*' i.e. allow any
                    continue
                if not self.match_check(cond_arg, six.text_type(args[i])):
                    good = False
                    break
            if not good:
                continue
            # Check kwargs
            cond_kwargs = cond.get('kwargs', {})
            for k, v in six.iteritems(cond_kwargs):
                if kwargs is None or k not in kwargs:
                    good = False
                    break
                if v is None:  # None == '.*' i.e. allow any
                    continue
                if not self.match_check(v, six.text_type(kwargs[k])):
                    good = False
                    break
            if good:
                return True
        return False


class RemoteCkMinions(CkMinions):
    '''
    A remote subclass of CkMinions that can act in the context of a minion;
    i.e. does the given minion itself match each matcher
    '''
    def _pki_minions(self):
        '''
        stub _pki_minions to only be self
        '''
        return [self.opts['id']]

    def _check_cache_minions(self,
                             expr,
                             delimiter,
                             greedy,
                             search_type,
                             regex_match=False,
                             exact_match=False):

        mdata = self.opts.get('grains', {})

        if mdata is None:
            return {'minions': [],
                    'missing': []}

        search_results = mdata.get(search_type)
        if salt.utils.data.subdict_match(search_results,
                                         expr,
                                         delimiter=delimiter,
                                         regex_match=regex_match,
                                         exact_match=exact_match):
            minions = [self.opts['id']]

        return {'minions': minions,
                'missing': []}


class PgJsonbCkMinions(CkMinions):
    '''
    A jsonb optimized subclass of CkMinions to leverage postgres speed.
    '''
    def __init__(self, opts):
        super(PgJsonbCkMinions, self).__init__(opts)

    def _check_cache_minions(self,
                             expr,
                             delimiter,
                             greedy,
                             search_type,
                             regex_match=False,
                             exact_match=False):
        '''
        Helper function to search for minions in master caches
        If 'greedy' return accepted minions that matched by the condition or absend in the cache.
        If not 'greedy' return the only minions have cache data and matched by the condition.
        '''
        # we can convert the first N non-glob/non-regex tokens into a set of contains queries
        # if a glob or regex exists its simpler to fetch the data first then use subdict_match
        # rather than deconstruct and re-implement inside pg. This could have a pathological worst
        # case but generally I expect 99% of queries to be exact match foo:bar:baz queries.
        # we have to generate many contains for a given set of tokens because subdict_match
        # looks into arrays
        # something more intelligent will probably be possible in pg12 but thats not on the table
        # at the moment
        def _gen_query(tokens=None, fetch_value=False):
            from psycopg2 import sql
            from psycopg2.extras import Json

            assert len(tokens) >= 1

            # contains
            fragments = _recurse_contains(tokens=tokens)

            if fetch_value:
                columns = sql.SQL(', ').join([sql.Identifier('key'),sql.Identifier('data')])
            else:
                columns = sql.Identifier('key')

            # we use pg_hint_plan to force BitMapScan, as a seq scan takes
            # about 5-10seconds on prod 50gb dataset, and due to lack of
            # statistics pg isn't always smart enough to know this is going to
            # be immensely faster
            query = sql.SQL('/*+ BitmapScan(cache idx_cache_data) */ '
                          'SELECT {0} FROM {1} WHERE {2} @> '
                          'ANY(ARRAY[' + (','.join(['%s'] * len(fragments))) + ']::jsonb[])').format(
                              columns,
                              sql.Identifier('cache'),
                              sql.Identifier('data'),
                          )

            # path check, contains cant test for presence of a key
            return (query, [Json(fragment) for fragment in fragments])

        # the basic idea here is to generate every contains @> operand we can to approximate
        # salt.utils.data.subdict_match exact_match behavior, which matches foo:bar
        # to {foo: bar}, {foo: {bar: true}}, { foo: [{bar: true]}, etc.
        # the only case that isnt back-compatible is {foo:{bar:$something}}, as ? operator
        # in pg cannot leverage the gin index at present day so is too slow to run.
        def _recurse_contains(lhs=None, tokens=None):
            fragments = []

            if not tokens:
                return fragments

            tokens = tokens[:]

            if not lhs and len(tokens) == 1:
                rhs = tokens[0]
                fragments.append({rhs: True})
                fragments.append({rhs: {}})
            elif len(tokens) == 2:
                lhs = tokens.pop(0)
                rhs = tokens.pop(0)
                fragments.append({lhs: rhs})
                fragments.append({lhs: {rhs: True}})
                fragments.append({lhs: {rhs: {}}})

                fragments.append({lhs: [rhs] })
                fragments.append({lhs: [{rhs: True}]})
                fragments.append({lhs: [{rhs: {}}]})
            else:
                lhs = tokens.pop(0)
                for fragment in _recurse_contains(lhs=lhs, tokens=tokens):
                    fragments.append({lhs: fragment})
                    fragments.append({lhs: [fragment]})

            return fragments

        # if its an exact match with no globs, we can just use a rough equivalent
        # jsonb query and let posgres do the work. if its a regex or glob we
        # do the work in python instead because pg isn't smart enough
        raw_tokens = expr.split(delimiter)
        exact_tokens = []
        while len(raw_tokens):
            token = raw_tokens.pop(0)
            if regex_match and re.escape(token) != token:
                break
            if not exact_match and '*' in token:
                break
            exact_tokens.append(token)

        if not exact_tokens:
            log.error('Someone is running a query across the full cache, this is going to be very slow: expr %s, search_type: %s', expr, search_type)
            raise CommandExecutionError('Too computationally expensive to compute this cache minion check')

        sql, bind = _gen_query(tokens=exact_tokens, fetch_value=len(raw_tokens) > 0)
        results = self.cache.query(sql, bind)

        pki_minions     = set(self._pki_minions())
        cache_minions   = set(self.cache.list(search_type))
        not_in_cache    = pki_minions - cache_minions
        unknown_minions = cache_minions - pki_minions
        cache_hits      = set([tup[0] for tup in results])

        # if raw tokens are left over, it means some were glob/regex, so we
        # do a second pass with subdict_match
        if raw_tokens:
            for (id_, mdata) in results:
                if not salt.utils.data.subdict_match(mdata,
                                                     expr,
                                                     delimiter=delimiter,
                                                     regex_match=regex_match,
                                                     exact_match=exact_match):
                    cache_hits.remove(id_)

        if greedy:
            # minions absent from the cache union results, minus minions unknown to master
            return {'minions': list((not_in_cache | cache_hits) - unknown_minions),
                    'missing': []}
        else:
            # cache hits that are also in pki list
            return {'minions': list(pki_minions & cache_hits),
                    'missing': []}

    def connected_ids(self, subset=None, show_ipv4=False, include_localhost=False):
        '''
        Return a set of all connected minion ids, optionally within a subset
        '''
        minions = set()

        all_ipv4 = self.cache.query('SELECT key, ipv4 FROM cache_grains_ipv4_view')

        if all_ipv4 is None:
            return minions

        addrs = salt.utils.network.local_port_tcp(int(self.opts['publish_port']))
        if '127.0.0.1' in addrs:
            # Add in the address of a possible locally-connected minion.
            addrs.discard('127.0.0.1')
            addrs.update(set(salt.utils.network.ip_addrs(include_loopback=include_localhost)))

        for id_, ipv4_addrs in all_ipv4:
            if subset and id_ not in subset:
                continue
            for ipv4 in ipv4_addrs:
                if ipv4 == '127.0.0.1' and not include_localhost:
                    continue
                if ipv4 == '0.0.0.0':
                    continue
                if ipv4 in addrs:
                    if show_ipv4:
                        minions.add((id_, ipv4))
                    else:
                        minions.add(id_)
                    break
        return minions
