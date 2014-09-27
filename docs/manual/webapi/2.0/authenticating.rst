.. _2.0-authenticating:

==============
Authenticating
==============

Logging In
==========

As of Review Board 2.1, there are two methods available for authenticating
using the API: Token-based authentication, and password-based authentication.
Prior to 2.1, password-based authentication was required.

Token-based authentication is the preferred method, as it offers a safe,
secure way of providing an application or third-party service with a way to
access Review Board under your account without exposing your password. It also
offers policy-based access through
:ref:`API token policies <api-token-policies>`, which can restrict what a
client is able to do while authenticated with that token.

If not logged in, any request that requires authentication will fail with
an HTTP 403 Unauthorized status. This response will contain a
``WWW-Authenticate`` header to set ``Basic realm="Web API"``.

Some clients, such as browsers, may choose to respond to this with a
password-based authentication request, but custom clients may use either
method.

After a successful login, the client will receive a ``rbsessionid`` cookie
that the client should use for all further requests. The cookie will be valid
for one year.


Token-based Authentication
--------------------------

.. versionadded:: 2.1

Users will first need to create one or more tokens for their account. This is
done through the My Account -> API Tokens page. Simply click :guilabel:`Create
a new API token`, optionally set the policy and a description, and you're
done.

To authenticate with a token, the client must send an ``Authorization`` header
as part of its next API request. The contents of this will be
:samp:`token {token_value}`, where ``token_value`` is the token you've chosen
from your My Account page.

For example, if your auth token is
``8a6b5c6aa9e2f3f0a855b3275768c217b01c951c``, you would send::

    Authorization: token 8a6b5c6aa9e2f3f0a855b3275768c217b01c951c


Password-based Authentication
-----------------------------

Review Board makes use of Basic HTTP Authentication for logging in using a
user's username and password.

When authenticating with Review Board (either preemptively, or in response to
an HTTP 403 Unauthorized response), the client may send an ``Authorization``
header as part of its next API request. The contents of this will be
:samp:`Basic {base64-auth}`.  The ``base64-auth`` part is a base64-encoded
representation of the string :samp:`{username}:{password}`.

For example, for a username and password of ``joe`` and ``mypass``, you
will base64-encode the string ``joe:mypass`` to get the resulting string
``am9lOm15cGFzcw==``, which you would then send as
``Basic am9lOm15cGFzcw==``::

    Authorization: Basic am9lOm15cGFzcw==


Logging Out
===========

Basic HTTP Authentication doesn't really provide a way to log clients out,
so it's up to the client to simply stop storing the ``rbsessionid`` cookie
and stop sending a populated ``Authorization`` header. Nothing needs to be
done on the server to tell Review Board you're no longer logged in.
