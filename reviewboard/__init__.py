from __future__ import unicode_literals


# The version of Review Board.
#
# This is in the format of:
#
#   (Major, Minor, Micro, Patch, alpha/beta/rc/final, Release Number, Released)
#
VERSION = (2, 1, 0, 0, 'alpha', 0, False)


# Required version of Django
django_version = 'Django>=1.6.7,<1.7'


def get_version_string():
    version = '%s.%s' % (VERSION[0], VERSION[1])

    if VERSION[2] or VERSION[3]:
        version += ".%s" % VERSION[2]

    if VERSION[3]:
        version += ".%s" % VERSION[3]

    if VERSION[4] != 'final':
        if VERSION[4] == 'rc':
            version += ' RC%s' % VERSION[5]
        else:
            version += ' %s %s' % (VERSION[4], VERSION[5])

    if not is_release():
        version += " (dev)"

    return version


def get_package_version():
    version = '%s.%s' % (VERSION[0], VERSION[1])

    if VERSION[2] or VERSION[3]:
        version += ".%s" % VERSION[2]

    if VERSION[3]:
        version += ".%s" % VERSION[3]

    if VERSION[4] != 'final':
        version += '%s%s' % (VERSION[4], VERSION[5])

    return version


def is_release():
    return VERSION[6]


def get_manual_url():
    if VERSION[4] == 'final' and is_release():
        manual_ver = '%s.%s' % (VERSION[0], VERSION[1])
    else:
        manual_ver = 'dev'

    return 'https://www.reviewboard.org/docs/manual/%s/' % manual_ver


def initialize():
    """Begins initialization of Review Board.

    This sets up the logging, generates cache serial numbers, and then
    fires an initializing signal that other parts of the codebase can
    connect to. This must be called for such features as e-mail notification
    to work.
    """
    import logging
    import os

    import settings_local

    # Set RBSITE_PYTHON_PATH to the path we need for any RB-bundled
    # scripts we may call.
    os.environ['RBSITE_PYTHONPATH'] = \
        os.path.dirname(settings_local.__file__)

    from django.conf import settings
    from django.db import DatabaseError
    from djblets import log
    from djblets.cache.serials import generate_ajax_serial

    from reviewboard import signals
    from reviewboard.admin.siteconfig import load_site_config
    from reviewboard.extensions.base import get_extension_manager

    # This overrides a default django templatetag (url), and we want to make
    # sure it will always get loaded in every python instance.
    import reviewboard.site.templatetags

    is_running_test = getattr(settings, 'RUNNING_TEST', False)

    if not is_running_test:
        # Set up logging.
        log.init_logging()

    load_site_config()

    if not is_running_test:
        if settings.DEBUG:
            logging.debug("Log file for Review Board v%s (PID %s)" %
                          (get_version_string(), os.getpid()))

        # Generate the AJAX serial, used for AJAX request caching.
        generate_ajax_serial()

        # Load all extensions
        try:
            get_extension_manager().load()
        except DatabaseError:
            # This database is from a time before extensions, so don't attempt
            # to load any extensions yet.
            pass

    signals.initializing.send(sender=None)


__version_info__ = VERSION[:-1]
__version__ = get_package_version()
