class JupiterError(Exception):
    pass


class ConfigError(JupiterError):
    pass


class ZeusDownloadError(JupiterError):
    pass


class DifyError(JupiterError):
    pass


class InputValidationError(JupiterError):
    pass


class LogFetchError(JupiterError):
    pass
