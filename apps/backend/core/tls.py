import logging
import os
from pathlib import Path

from apps.backend.core.config import settings

logger = logging.getLogger(__name__)


def tls_verify() -> bool | str:
    """
    Return verify target for httpx:
    - True: default system/ca bundle
    - str path: custom company root CA
    """
    ca_path = (settings.officetool_ca_cert_path or settings.offciatool_ca_cert_path or "").strip()
    if not ca_path:
        return True
    path = Path(ca_path)
    if not path.exists():
        logger.warning("OFFICETOOL_CA_CERT_PATH not found: %s; fallback to default TLS verify", ca_path)
        return True
    return str(path)


def apply_tls_env() -> None:
    """
    Keep behavior close to curl --cacert and offciatool runtime:
    propagate CA path to SSL_CERT_FILE / REQUESTS_CA_BUNDLE.
    """
    verify = tls_verify()
    if isinstance(verify, str):
        os.environ.setdefault("SSL_CERT_FILE", verify)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", verify)
