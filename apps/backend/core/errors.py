class SequoiaError(Exception):
    pass


class ConfigError(SequoiaError):
    pass


class ZeusDownloadError(SequoiaError):
    pass


class DifyError(SequoiaError):
    pass


class InputValidationError(SequoiaError):
    pass


class LogFetchError(SequoiaError):
    pass


# Backward compatibility for older imports.
JupiterError = SequoiaError
