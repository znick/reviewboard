from __future__ import unicode_literals

import logging
import pkg_resources
import re
import sre_constants
import sys
from warnings import warn

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.contrib.auth import get_backends
from django.contrib.auth import hashers
from django.utils import six
from django.utils.translation import ugettext_lazy as _
from djblets.db.query import get_object_or_none
from djblets.siteconfig.models import SiteConfiguration
try:
    from ldap.filter import filter_format
except ImportError:
    pass

from reviewboard.accounts.forms.auth import (ActiveDirectorySettingsForm,
                                             LDAPSettingsForm,
                                             NISSettingsForm,
                                             StandardAuthSettingsForm,
                                             X509SettingsForm)
from reviewboard.accounts.models import LocalSiteProfile
from reviewboard.site.models import LocalSite


_registered_auth_backends = {}
_enabled_auth_backends = []
_auth_backend_setting = None
_populated = False


INVALID_USERNAME_CHAR_REGEX = re.compile(r'[^\w.@+-]')


class AuthBackend(object):
    """The base class for Review Board authentication backends."""
    backend_id = None
    name = None
    settings_form = None
    supports_anonymous_user = True
    supports_object_permissions = True
    supports_registration = False
    supports_change_name = False
    supports_change_email = False
    supports_change_password = False
    login_instructions = None

    def authenticate(self, username, password):
        raise NotImplementedError

    def get_or_create_user(self, username, request):
        raise NotImplementedError

    def get_user(self, user_id):
        return get_object_or_none(User, pk=user_id)

    def update_password(self, user, password):
        """Updates the user's password on the backend.

        Authentication backends can override this to update the password
        on the backend. This will only be called if
        :py:attr:`supports_change_password` is ``True``.

        By default, this will raise NotImplementedError.
        """
        raise NotImplementedError

    def update_name(self, user):
        """Updates the user's name on the backend.

        The first name and last name will already be stored in the provided
        ``user`` object.

        Authentication backends can override this to update the name
        on the backend based on the values in ``user``. This will only be
        called if :py:attr:`supports_change_name` is ``True``.

        By default, this will do nothing.
        """
        pass

    def update_email(self, user):
        """Updates the user's e-mail address on the backend.

        The e-mail address will already be stored in the provided
        ``user`` object.

        Authentication backends can override this to update the e-mail
        address on the backend based on the values in ``user``. This will only
        be called if :py:attr:`supports_change_email` is ``True``.

        By default, this will do nothing.
        """
        pass

    def query_users(self, query, request):
        """Searches for users on the back end.

        This call is executed when the User List web API resource is called,
        before the database is queried.

        Authentication backends can override this to perform an external
        query. Results should be written to the database as standard
        Review Board users, which will be matched and returned by the web API
        call.

        The ``query`` parameter contains the value of the ``q`` search
        parameter of the web API call (e.g. /users/?q=foo), if any.

        Errors can be passed up to the web API layer by raising a
        reviewboard.accounts.errors.UserQueryError exception.

        By default, this will do nothing.
        """
        pass

    def search_users(self, query, request):
        """Custom user-database search.

        This call is executed when the User List web API resource is called
        and the ``q`` search parameter is provided, indicating a search
        query.

        It must return either a django.db.models.Q object or None.  All
        enabled backends are called until a Q object is returned.  If one
        isn't returned, a default search is executed.
        """
        return None


class StandardAuthBackend(AuthBackend, ModelBackend):
    """Authenticates users against the local database.

    This will authenticate a user against their entry in the database, if
    the user has a local password stored. This is the default form of
    authentication in Review Board.

    This backend also handles permission checking for users on LocalSites.
    In Django, this is the responsibility of at least one auth backend in
    the list of configured backends.

    Regardless of the specific type of authentication chosen for the
    installation, StandardAuthBackend will always be provided in the list
    of configured backends. Because of this, it will always be able to
    handle authentication against locally added users and handle
    LocalSite-based permissions for all configurations.
    """
    backend_id = 'builtin'
    name = _('Standard Registration')
    settings_form = StandardAuthSettingsForm
    supports_registration = True
    supports_change_name = True
    supports_change_email = True
    supports_change_password = True

    _VALID_LOCAL_SITE_PERMISSIONS = [
        'hostingsvcs.change_hostingserviceaccount',
        'hostingsvcs.create_hostingserviceaccount',
        'reviews.add_group',
        'reviews.can_change_status',
        'reviews.can_edit_reviewrequest',
        'reviews.can_submit_as_another_user',
        'reviews.change_default_reviewer',
        'reviews.change_group',
        'reviews.delete_file',
        'reviews.delete_screenshot',
        'scmtools.add_repository',
        'scmtools.change_repository',
    ]

    def authenticate(self, username, password):
        return ModelBackend.authenticate(self, username, password)

    def get_or_create_user(self, username, request):
        return ModelBackend.get_or_create_user(self, username, request)

    def update_password(self, user, password):
        user.password = hashers.make_password(password)

    def get_all_permissions(self, user, obj=None):
        """Returns a list of all permissions for a user.

        If a LocalSite instance is passed as ``obj``, then the permissions
        returned will be those that the user has on that LocalSite. Otherwise,
        they will be their global permissions.

        It is not legal to pass any other object.
        """
        if obj is not None and not isinstance(obj, LocalSite):
            logging.error('Unexpected object %r passed to '
                          'StandardAuthBackend.get_all_permissions. '
                          'Returning an empty list.',
                          obj)

            if settings.DEBUG:
                raise ValueError('Unexpected object %r' % obj)

            return set()

        if user.is_anonymous():
            return set()

        # First, get the list of all global permissions.
        #
        # Django's ModelBackend doesn't support passing an object, and will
        # return an empty set, so don't pass an object for this attempt.
        permissions = \
            super(StandardAuthBackend, self).get_all_permissions(user)

        if obj is not None:
            # We know now that this is a LocalSite, due to the assertion
            # above.
            if not hasattr(user, '_local_site_perm_cache'):
                user._local_site_perm_cache = {}

            if obj.pk not in user._local_site_perm_cache:
                perm_cache = set()

                try:
                    site_profile = user.get_site_profile(obj)
                    site_perms = site_profile.permissions or {}

                    if site_perms:
                        perm_cache = set([
                            key
                            for key, value in six.iteritems(site_perms)
                            if value
                        ])
                except LocalSiteProfile.DoesNotExist:
                    pass

                user._local_site_perm_cache[obj.pk] = perm_cache

            permissions = permissions.copy()
            permissions.update(user._local_site_perm_cache[obj.pk])

        return permissions

    def has_perm(self, user, perm, obj=None):
        """Returns whether a user has the given permission.

        If a LocalSite instance is passed as ``obj``, then the permissions
        checked will be those that the user has on that LocalSite. Otherwise,
        they will be their global permissions.

        It is not legal to pass any other object.
        """
        if obj is not None and not isinstance(obj, LocalSite):
            logging.error('Unexpected object %r passed to has_perm. '
                          'Returning False.', obj)

            if settings.DEBUG:
                raise ValueError('Unexpected object %r' % obj)

            return False

        if not user.is_active:
            return False

        if obj is not None:
            if not hasattr(user, '_local_site_admin_for'):
                user._local_site_admin_for = {}

            if obj.pk not in user._local_site_admin_for:
                user._local_site_admin_for[obj.pk] = obj.is_mutable_by(user)

            if user._local_site_admin_for[obj.pk]:
                return perm in self._VALID_LOCAL_SITE_PERMISSIONS

        return super(StandardAuthBackend, self).has_perm(user, perm, obj)


class NISBackend(AuthBackend):
    """Authenticate against a user on an NIS server."""
    backend_id = 'nis'
    name = _('NIS')
    settings_form = NISSettingsForm
    login_instructions = \
        _('Use your standard NIS username and password.')

    def authenticate(self, username, password):
        import crypt
        import nis

        username = username.strip()

        try:
            passwd = nis.match(username, 'passwd').split(':')
            original_crypted = passwd[1]
            new_crypted = crypt.crypt(password, original_crypted)

            if original_crypted == new_crypted:
                return self.get_or_create_user(username, None, passwd)
        except nis.error:
            # FIXME I'm not sure under what situations this would fail (maybe
            # if their NIS server is down), but it'd be nice to inform the
            # user.
            pass

        return None

    def get_or_create_user(self, username, request, passwd=None):
        import nis

        username = username.strip()

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                if not passwd:
                    passwd = nis.match(username, 'passwd').split(':')

                names = passwd[4].split(',')[0].split(' ', 1)
                first_name = names[0]
                last_name = None
                if len(names) > 1:
                    last_name = names[1]

                email = '%s@%s' % (username, settings.NIS_EMAIL_DOMAIN)

                user = User(username=username,
                            password='',
                            first_name=first_name,
                            last_name=last_name or '',
                            email=email)
                user.is_staff = False
                user.is_superuser = False
                user.set_unusable_password()
                user.save()
            except nis.error:
                pass
        return user


class LDAPBackend(AuthBackend):
    """Authenticate against a user on an LDAP server."""
    backend_id = 'ldap'
    name = _('LDAP')
    settings_form = LDAPSettingsForm
    login_instructions = \
        _('Use your standard LDAP username and password.')

    def authenticate(self, username, password):
        username = username.strip()

        uidfilter = "(%(userattr)s=%(username)s)" % {
                    'userattr': settings.LDAP_UID,
                    'username': username
        }

        # If the UID mask has been explicitly set, override
        # the standard search filter
        if settings.LDAP_UID_MASK:
            uidfilter = settings.LDAP_UID_MASK % username

        if len(password) == 0:
            # Don't try to bind using an empty password; the server will
            # return success, which doesn't mean we have authenticated.
            # http://tools.ietf.org/html/rfc4513#section-5.1.2
            # http://tools.ietf.org/html/rfc4513#section-6.3.1
            logging.warning("Empty password for: %s", username)
            return None

        if isinstance(username, six.text_type):
            username_bytes = username.encode('utf-8')

        if isinstance(password, six.text_type):
            password = password.encode('utf-8')

        try:
            import ldap
            ldapo = ldap.initialize(settings.LDAP_URI)
            ldapo.set_option(ldap.OPT_REFERRALS, 0)
            ldapo.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
            if settings.LDAP_TLS:
                ldapo.start_tls_s()

            if settings.LDAP_ANON_BIND_UID:
                # Log in as the service account before searching.
                ldapo.simple_bind_s(settings.LDAP_ANON_BIND_UID,
                                    settings.LDAP_ANON_BIND_PASSWD)
            else:
                # Bind anonymously to the server
                ldapo.simple_bind_s()

            # Search for the user with the given base DN and uid. If the user
            # is found, a fully qualified DN is returned. Authentication is
            # then done with bind using this fully qualified DN.
            search = ldapo.search_s(settings.LDAP_BASE_DN,
                                    ldap.SCOPE_SUBTREE,
                                    uidfilter)
            if not search:
                # No such user, return early, no need for bind attempts
                logging.warning("LDAP error: The specified object does "
                                "not exist in the Directory: %s",
                                username)
                return None
            else:
                userdn = search[0][0]

            # Now that we have the user, attempt to bind to verify
            # authentication
            logging.debug("Attempting to authenticate as %s" % userdn.decode('utf-8'))
            ldapo.bind_s(userdn, password)

            return self.get_or_create_user(username_bytes, None, ldapo, userdn)

        except ImportError:
            pass
        except ldap.INVALID_CREDENTIALS:
            logging.warning("LDAP error: The specified object does not exist "
                            "in the Directory or provided invalid "
                            "credentials: %s",
                            username)
        except ldap.LDAPError as e:
            logging.warning("LDAP error: %s", e)
        except:
            # Fallback exception catch because
            # django.contrib.auth.authenticate() (our caller) catches only
            # TypeErrors
            logging.warning("An error while LDAP-authenticating: %r" %
                            sys.exc_info()[1])

        return None

    def get_or_create_user(self, username, request, ldapo, userdn):
        username = re.sub(INVALID_USERNAME_CHAR_REGEX, '', username).lower()

        try:
            user = User.objects.get(username=username)
            return user
        except User.DoesNotExist:
            try:
                import ldap

                # Perform a BASE search since we already know the DN of
                # the user
                search_result = ldapo.search_s(userdn,
                                               ldap.SCOPE_BASE)
                user_info = search_result[0][1]

                given_name_attr = getattr(
                    settings, 'LDAP_GIVEN_NAME_ATTRIBUTE', 'givenName')
                first_name = user_info.get(given_name_attr, [username])[0]

                surname_attr = getattr(
                    settings, 'LDAP_SURNAME_ATTRIBUTE', 'sn')
                last_name = user_info.get(surname_attr, [''])[0]

                # If a single ldap attribute is used to hold the full name of
                # a user, split it into two parts.  Where to split was a coin
                # toss and I went with a left split for the first name and
                # dumped the remainder into the last name field.  The system
                # admin can handle the corner cases.
                try:
                    if settings.LDAP_FULL_NAME_ATTRIBUTE:
                        full_name = \
                            user_info[settings.LDAP_FULL_NAME_ATTRIBUTE][0]
                        first_name, last_name = full_name.split(' ', 1)
                except AttributeError:
                    pass

                if settings.LDAP_EMAIL_DOMAIN:
                    email = '%s@%s' % (username, settings.LDAP_EMAIL_DOMAIN)
                elif settings.LDAP_EMAIL_ATTRIBUTE:
                    try:
                        email = user_info[settings.LDAP_EMAIL_ATTRIBUTE][0]
                    except KeyError:
                        logging.error('LDAP: could not get e-mail address for '
                                      'user %s using attribute %s',
                                      username, settings.LDAP_EMAIL_ATTRIBUTE)
                        email = ''
                else:
                    logging.warning(
                        'LDAP: e-mail for user %s is not specified',
                        username)
                    email = ''

                user = User(username=username,
                            password='',
                            first_name=first_name,
                            last_name=last_name,
                            email=email)
                user.is_staff = False
                user.is_superuser = False
                user.set_unusable_password()
                user.save()
                return user
            except ImportError:
                pass
            except ldap.INVALID_CREDENTIALS:
                # FIXME I'd really like to warn the user that their
                # ANON_BIND_UID and ANON_BIND_PASSWD are wrong, but I don't
                # know how
                pass
            except ldap.NO_SUCH_OBJECT as e:
                logging.warning("LDAP error: %s settings.LDAP_BASE_DN: %s "
                                "User DN: %s",
                                e, settings.LDAP_BASE_DN, userdn,
                                exc_info=1)
            except ldap.LDAPError as e:
                logging.warning("LDAP error: %s", e, exc_info=1)

        return None


class ActiveDirectoryBackend(AuthBackend):
    """Authenticate a user against an Active Directory server."""
    backend_id = 'ad'
    name = _('Active Directory')
    settings_form = ActiveDirectorySettingsForm
    login_instructions = \
        _('Use your standard Active Directory username and password.')

    def get_domain_name(self):
        return six.text_type(settings.AD_DOMAIN_NAME)

    def get_ldap_search_root(self, userdomain=None):
        if getattr(settings, "AD_SEARCH_ROOT", None):
            root = [settings.AD_SEARCH_ROOT]
        else:
            if userdomain is None:
                userdomain = self.get_domain_name()

            root = ['dc=%s' % x for x in userdomain.split('.')]

            if settings.AD_OU_NAME:
                root = ['ou=%s' % settings.AD_OU_NAME] + root

        return ','.join(root)

    def search_ad(self, con, filterstr, userdomain=None):
        import ldap
        search_root = self.get_ldap_search_root(userdomain)
        logging.debug('Search root ' + search_root)
        return con.search_s(search_root, scope=ldap.SCOPE_SUBTREE,
                            filterstr=filterstr)

    def find_domain_controllers_from_dns(self, userdomain=None):
        import DNS
        DNS.Base.DiscoverNameServers()
        q = '_ldap._tcp.%s' % (userdomain or self.get_domain_name())
        req = DNS.Base.DnsRequest(q, qtype='SRV').req()
        return [x['data'][-2:] for x in req.answers]

    def can_recurse(self, depth):
        return (settings.AD_RECURSION_DEPTH == -1 or
                depth <= settings.AD_RECURSION_DEPTH)

    def get_member_of(self, con, search_results, seen=None, depth=0):
        depth += 1
        if seen is None:
            seen = set()

        for name, data in search_results:
            if name is None:
                continue
            member_of = data.get('memberOf', [])
            new_groups = [x.split(',')[0].split('=')[1] for x in member_of]
            old_seen = seen.copy()
            seen.update(new_groups)

            # collect groups recursively
            if self.can_recurse(depth):
                for group in new_groups:
                    if group in old_seen:
                        continue

                    # Search for groups with the specified CN. Use the CN
                    # rather than The sAMAccountName so that behavior is
                    # correct when the values differ (e.g. if a
                    # "pre-Windows 2000" group name is set in AD)
                    group_data = self.search_ad(
                        con,
                        filter_format('(&(objectClass=group)(cn=%s))',
                                      (group,)))
                    seen.update(self.get_member_of(con, group_data,
                                                   seen=seen, depth=depth))
            else:
                logging.warning('ActiveDirectory recursive group check '
                                'reached maximum recursion depth.')

        return seen

    def get_ldap_connections(self, userdomain=None):
        import ldap
        if settings.AD_FIND_DC_FROM_DNS:
            dcs = self.find_domain_controllers_from_dns(userdomain)
        else:
            dcs = []

            for dc_entry in settings.AD_DOMAIN_CONTROLLER.split():
                if ':' in dc_entry:
                    host, port = dc_entry.split(':')
                else:
                    host = dc_entry
                    port = '389'

                dcs.append([port, host])

        for dc in dcs:
            port, host = dc
            ldap_uri = 'ldap://%s:%s' % (host, port)
            con = ldap.initialize(ldap_uri)

            if settings.AD_USE_TLS:
                try:
                    con.start_tls_s()
                except ldap.UNAVAILABLE:
                    logging.warning('Active Directory: Domain controller '
                                    '%s:%d for domain %s unavailable',
                                    host, int(port), userdomain)
                    continue
                except ldap.CONNECT_ERROR:
                    logging.warning("Active Directory: Could not connect "
                                    "to domain controller %s:%d for domain "
                                    "%s, possibly the certificate wasn't "
                                    "verifiable",
                                    host, int(port), userdomain)
                    continue

            con.set_option(ldap.OPT_REFERRALS, 0)
            yield con

    def authenticate(self, username, password):
        import ldap

        username = username.strip()

        user_subdomain = ''

        if '@' in username:
            username, user_subdomain = username.split('@', 1)
        elif '\\' in username:
            user_subdomain, username = username.split('\\', 1)

        userdomain = self.get_domain_name()

        if user_subdomain:
            userdomain = "%s.%s" % (user_subdomain, userdomain)

        connections = self.get_ldap_connections(userdomain)
        required_group = settings.AD_GROUP_NAME

        if isinstance(username, six.text_type):
            username_bytes = username.encode('utf-8')

        if isinstance(user_subdomain, six.text_type):
            user_subdomain = user_subdomain.encode('utf-8')

        if isinstance(password, six.text_type):
            password = password.encode('utf-8')

        for con in connections:
            try:
                bind_username = b'%s@%s' % (username_bytes, userdomain)
                logging.debug("User %s is trying to log in via AD",
                              bind_username.decode('utf-8'))
                con.simple_bind_s(bind_username, password)
                user_data = self.search_ad(
                    con,
                    filter_format('(&(objectClass=user)(sAMAccountName=%s))',
                                  (username_bytes,)),
                    userdomain)

                if not user_data:
                    return None

                if required_group:
                    try:
                        group_names = self.get_member_of(con, user_data)
                    except Exception as e:
                        logging.error("Active Directory error: failed getting"
                                      "groups for user '%s': %s",
                                      username, e, exc_info=1)
                        return None

                    if required_group not in group_names:
                        logging.warning("Active Directory: User %s is not in "
                                        "required group %s",
                                        username, required_group)
                        return None

                return self.get_or_create_user(username, None, user_data)
            except ldap.SERVER_DOWN:
                logging.warning('Active Directory: Domain controller is down')
                continue
            except ldap.INVALID_CREDENTIALS:
                logging.warning('Active Directory: Failed login for user %s',
                                username)
                return None

        logging.error('Active Directory error: Could not contact any domain '
                      'controller servers')
        return None

    def get_or_create_user(self, username, request, ad_user_data):
        username = re.sub(INVALID_USERNAME_CHAR_REGEX, '', username).lower()

        try:
            user = User.objects.get(username=username)
            return user
        except User.DoesNotExist:
            try:
                user_info = ad_user_data[0][1]

                first_name = user_info.get('givenName', [username])[0]
                last_name = user_info.get('sn', [""])[0]
                email = user_info.get(
                    'mail',
                    ['%s@%s' % (username, settings.AD_DOMAIN_NAME)])[0]

                user = User(username=username,
                            password='',
                            first_name=first_name,
                            last_name=last_name,
                            email=email)
                user.is_staff = False
                user.is_superuser = False
                user.set_unusable_password()
                user.save()
                return user
            except:
                return None


class X509Backend(AuthBackend):
    """
    Authenticate a user from a X.509 client certificate passed in by the
    browser. This backend relies on the X509AuthMiddleware to extract a
    username field from the client certificate.
    """
    backend_id = 'x509'
    name = _('X.509 Public Key')
    settings_form = X509SettingsForm
    supports_change_password = True

    def authenticate(self, x509_field=""):
        username = self.clean_username(x509_field)
        return self.get_or_create_user(username, None)

    def clean_username(self, username):
        username = username.strip()

        if settings.X509_USERNAME_REGEX:
            try:
                m = re.match(settings.X509_USERNAME_REGEX, username)
                if m:
                    username = m.group(1)
                else:
                    logging.warning("X509Backend: username '%s' didn't match "
                                    "regex.", username)
            except sre_constants.error as e:
                logging.error("X509Backend: Invalid regex specified: %s",
                              e, exc_info=1)

        return username

    def get_or_create_user(self, username, request):
        user = None
        username = username.strip()

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # TODO Add the ability to get the first and last names in a
            #      configurable manner; not all X.509 certificates will have
            #      the same format.
            if getattr(settings, 'X509_AUTOCREATE_USERS', False):
                user = User(username=username, password='')
                user.is_staff = False
                user.is_superuser = False
                user.set_unusable_password()
                user.save()

        return user


def _populate_defaults():
    """Populates the default list of authentication backends."""
    global _populated

    if not _populated:
        _populated = True

        # Always ensure that the standard built-in auth backend is included.
        register_auth_backend(StandardAuthBackend)

        entrypoints = \
            pkg_resources.iter_entry_points('reviewboard.auth_backends')

        for entry in entrypoints:
            try:
                cls = entry.load()

                # All backends should include an ID, but we need to handle
                # legacy modules.
                if not cls.backend_id:
                    logging.warning('The authentication backend %r did '
                                    'not provide a backend_id attribute. '
                                    'Setting it to the entrypoint name "%s".',
                                    cls, entry.name)
                    cls.backend_id = entry.name

                register_auth_backend(cls)
            except Exception as e:
                logging.error('Error loading authentication backend %s: %s',
                              entry.name, e, exc_info=1)


def get_registered_auth_backends():
    """Returns all registered Review Board authentication backends.

    This will return all backends provided both by Review Board and by
    third parties that have properly registered with the
    "reviewboard.auth_backends" entry point.
    """
    _populate_defaults()

    return six.itervalues(_registered_auth_backends)


def get_registered_auth_backend(backend_id):
    """Returns the authentication backends with the specified ID.

    If the authentication backend could not be found, this will return None.
    """
    _populate_defaults()

    try:
        return _registered_auth_backends[backend_id]
    except KeyError:
        return None


def register_auth_backend(backend_cls):
    """Registers an authentication backend.

    This backend will appear in the list of available backends.

    The backend class must have a backend_id attribute set, and can only
    be registerd once. A KeyError will be thrown if attempting to register
    a second time.
    """
    _populate_defaults()

    backend_id = backend_cls.backend_id

    if not backend_id:
        raise KeyError('The backend_id attribute must be set on %r'
                       % backend_cls)

    if backend_id in _registered_auth_backends:
        raise KeyError('"%s" is already a registered auth backend'
                       % backend_id)

    _registered_auth_backends[backend_id] = backend_cls


def unregister_auth_backend(backend_cls):
    """Unregisters a previously registered authentication backend."""
    _populate_defaults()

    backend_id = backend_cls.backend_id

    if backend_id not in _registered_auth_backends:
        logging.error('Failed to unregister unknown authentication '
                      'backend "%s".',
                      backend_id)
        raise KeyError('"%s" is not a registered authentication backend'
                       % backend_id)

    del _registered_auth_backends[backend_id]


def get_enabled_auth_backends():
    """Returns all authentication backends being used by Review Board.

    The returned list contains every authentication backend that Review Board
    will try, in order.
    """
    global _enabled_auth_backends
    global _auth_backend_setting

    if (not _enabled_auth_backends or
        _auth_backend_setting != settings.AUTHENTICATION_BACKENDS):
        _enabled_auth_backends = []

        for backend in get_backends():
            if not isinstance(backend, AuthBackend):
                warn('Authentication backends should inherit from '
                     'reviewboard.accounts.backends.AuthBackend. Please '
                     'update %s.' % backend.__class__)

                for field, default in (('name', None),
                                       ('supports_registration', False),
                                       ('supports_change_name', False),
                                       ('supports_change_email', False),
                                       ('supports_change_password', False)):
                    if not hasattr(backend, field):
                        warn("Authentication backends should define a '%s' "
                             "attribute. Please define it in %s or inherit "
                             "from AuthBackend." % (field, backend.__class__))
                        setattr(backend, field, False)

            _enabled_auth_backends.append(backend)

        _auth_backend_setting = settings.AUTHENTICATION_BACKENDS

    return _enabled_auth_backends


def set_enabled_auth_backend(backend_id):
    """Sets the authentication backend to be used."""
    siteconfig = SiteConfiguration.objects.get_current()
    siteconfig.set('auth_backend', backend_id)
