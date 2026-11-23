"""Errors that are safe to show to the frontend.

The API envelope carries a stable ``code`` so the interface can localise the
message instead of displaying an English sentence written at the call site.
"""


class ComicNestError(Exception):
    status = 500
    code = 1000
    message = "internal error"

    def __init__(self, message=None, *, code=None, status=None, detail=None):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self):
        payload = {"code": self.code, "message": self.message, "data": None}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class BadRequest(ComicNestError):
    status = 400
    code = 1400
    message = "invalid request"


class AuthRequired(ComicNestError):
    status = 401
    code = 1401
    message = "session expired, please sign in again"


class IdentityRequired(ComicNestError):
    status = 401
    code = 1402
    message = "your TOS user could not be determined"


class Forbidden(ComicNestError):
    status = 403
    code = 1403
    message = "you do not have permission for this action"


class NotFound(ComicNestError):
    status = 404
    code = 1404
    message = "resource not found"


class MethodNotAllowed(ComicNestError):
    status = 405
    code = 1405
    message = "method not allowed"


class Conflict(ComicNestError):
    status = 409
    code = 1409
    message = "the resource already exists"


class PayloadTooLarge(ComicNestError):
    status = 413
    code = 1413
    message = "the request is too large"


class UnsupportedMedia(ComicNestError):
    status = 415
    code = 1415
    message = "unsupported format"


class SourceUnavailable(ComicNestError):
    status = 503
    code = 3001
    message = "the comic source is not available"


class SourceDenied(ComicNestError):
    status = 403
    code = 3002
    message = "the comic source refused access"


class SourceInvalid(ComicNestError):
    status = 400
    code = 3003
    message = "the comic source configuration is invalid"


class ChapterNotFound(ComicNestError):
    status = 404
    code = 3101
    message = "chapter not found"


class PageNotFound(ComicNestError):
    status = 404
    code = 3102
    message = "page not found"


class ArchiveUnsupported(ComicNestError):
    status = 415
    code = 3103
    message = "this archive needs an extraction tool that is not installed"


class RemoteUnavailable(ComicNestError):
    status = 502
    code = 3201
    message = "the remote source could not be reached"


class RemoteAuthFailed(ComicNestError):
    status = 502
    code = 3202
    message = "the remote source rejected the stored credentials"
