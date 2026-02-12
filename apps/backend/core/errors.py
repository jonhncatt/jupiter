class JupiterError(Exception):
    pass


class ConfigError(JupiterError):
    pass


class ZeusDownloadError(JupiterError):
    pass


class DifyError(JupiterError):
    pass
