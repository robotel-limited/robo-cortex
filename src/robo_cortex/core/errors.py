class RoboCortexError(Exception):
    """Base error carrying the CLI exit code it should surface as."""

    exit_code = 1


class NotAGitRepoError(RoboCortexError):
    exit_code = 1


class AlreadyInitializedError(RoboCortexError):
    exit_code = 2


class BusyError(RoboCortexError):
    exit_code = 3


class NotInitializedError(RoboCortexError):
    exit_code = 1


class ValidationError(RoboCortexError):
    exit_code = 1


class NotFoundError(RoboCortexError):
    exit_code = 1


class IllegalTransitionError(RoboCortexError):
    exit_code = 1
