class ProtectedDataError(Exception):
    """A request the stores cannot honour. `status` is the HTTP status the API answers with."""

    status = 400


class NotFoundError(ProtectedDataError):
    status = 404


class ConflictError(ProtectedDataError):
    status = 409


class TooLargeError(ProtectedDataError):
    status = 413


class UnsupportedFileError(ProtectedDataError):
    status = 415


class InvalidInputError(ProtectedDataError):
    status = 422


class SourceUnavailableError(ProtectedDataError):
    status = 502
