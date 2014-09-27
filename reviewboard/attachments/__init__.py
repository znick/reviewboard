from __future__ import unicode_literals

from reviewboard.signals import initializing


def _register_mimetype_handlers(**kwargs):
    """Registers all bundled Mimetype Handlers."""
    from reviewboard.attachments.mimetypes import (ImageMimetype,
                                                   MarkDownMimetype,
                                                   MimetypeHandler,
                                                   register_mimetype_handler,
                                                   ReStructuredTextMimetype,
                                                   TextMimetype)

    register_mimetype_handler(ImageMimetype)
    register_mimetype_handler(MarkDownMimetype)
    register_mimetype_handler(MimetypeHandler)
    register_mimetype_handler(ReStructuredTextMimetype)
    register_mimetype_handler(TextMimetype)


initializing.connect(_register_mimetype_handlers)
