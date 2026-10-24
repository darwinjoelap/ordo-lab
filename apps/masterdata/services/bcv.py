"""Tasa oficial del BCV: descarga, lectura y registro (global, esquema `public`).

Portado del mecanismo ya probado en producción en Ordo (`apps/tasas/servicios.py`),
con una diferencia: aquí la tasa es global y vive en `masterdata.OfficialRate`, no en
un modelo por empresa. Cada laboratorio la sobrescribe con su propia
`billing.ExchangeRate` si lo necesita.
"""
from __future__ import annotations

import datetime
import logging
import os
import ssl
import tempfile
import warnings
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from apps.masterdata.models import OfficialRate

log = logging.getLogger("apps.masterdata")

BCV_URL = "https://www.bcv.org.ve/"
USER_AGENT = "Mozilla/5.0 (Ordo Lab)"
TIMEOUT = 20


def read_rate_from_html(html: str) -> Decimal:
    """Extrae la tasa USD del HTML del BCV (bloque con id="dolar")."""
    soup = BeautifulSoup(html, "lxml")
    block = soup.find(id="dolar")
    strong = block.find("strong") if block else None
    if not strong:
        raise ValueError("No se encontró el bloque del dólar en la página del BCV.")
    # Formato venezolano: punto de miles, coma decimal.
    text = strong.get_text(strip=True).replace(".", "").replace(",", ".")
    try:
        value = Decimal(text).quantize(Decimal("0.00000001"))
    except InvalidOperation:
        raise ValueError(f"Valor de tasa no numérico: {text!r}") from None
    if value <= 0:
        raise ValueError("La tasa debe ser mayor que cero.")
    return value


# --- Certificado incompleto del BCV ---------------------------------------------------
# El servidor del BCV no envía el certificado intermedio, así que la verificación TLS
# falla con "unable to get local issuer certificate". NO se desactiva la verificación:
# se descarga el intermedio desde la URL que el propio certificado declara (extensión
# AIA, "CA Issuers") y se verifica contra las raíces de certifi más ese intermedio.
# Nunca se agregan raíces descargadas: una raíz de origen desconocido permitiría que
# cualquiera suplantara al BCV.

def _pem(cert) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding

    return cert.public_bytes(Encoding.PEM).decode()


def _sha256():
    from cryptography.hazmat.primitives import hashes

    return hashes.SHA256()


def _ca_issuer_urls(cert) -> list[str]:
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    try:
        aia = cert.extensions.get_extension_for_oid(
            ExtensionOID.AUTHORITY_INFORMATION_ACCESS
        ).value
    except x509.ExtensionNotFound:
        return []
    return [
        d.access_location.value
        for d in aia
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS
    ]


def _load_certs(data: bytes, url: str = ""):
    """Certificados de una descarga AIA: DER, PEM o PKCS#7 (.p7c/.p7b), en DER o PEM."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs7

    attempts = (
        lambda d: [x509.load_der_x509_certificate(d)],
        lambda d: x509.load_pem_x509_certificates(d),
        lambda d: pkcs7.load_der_pkcs7_certificates(d),
        lambda d: pkcs7.load_pem_pkcs7_certificates(d),
    )
    for load in attempts:
        try:
            with warnings.catch_warnings():
                # El PKCS#7 del BCV viene en BER (no DER estricto): se lee igual, pero avisa.
                warnings.simplefilter("ignore", UserWarning)
                certs = load(data)
            if certs:
                return certs
        except Exception:  # noqa: BLE001 - se prueba el siguiente formato
            continue
    raise ValueError(
        f"Formato de certificado no reconocido en {url} "
        f"({len(data)} bytes, inicio {data[:40]!r})."
    )


def intermediates_by_aia(host: str, port: int = 443, max_levels: int = 3) -> list[str]:
    """PEM de los intermedios del servidor, por AIA. No devuelve raíces autofirmadas."""
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(
        ssl.get_server_certificate((host, port), timeout=TIMEOUT).encode()
    )
    intermediates: list[str] = []
    seen: set = set()
    for _ in range(max_levels):
        urls = _ca_issuer_urls(cert)
        if not urls:
            break
        response = requests.get(urls[0], timeout=TIMEOUT,
                                headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        following = None
        for c in _load_certs(response.content, urls[0]):
            if c.issuer == c.subject or c.fingerprint(_sha256()) in seen:
                continue  # raíz: no se agrega, debe estar ya en certifi
            seen.add(c.fingerprint(_sha256()))
            intermediates.append(_pem(c))
            if c.subject == cert.issuer:
                following = c
        if following is None:
            break
        cert = following
    return intermediates


def _ca_bundle_with_intermediates(host: str, port: int = 443) -> str:
    """Ruta a un archivo CA temporal = certifi + los intermedios del host."""
    import certifi

    intermediates = intermediates_by_aia(host, port)
    if not intermediates:
        raise ValueError(f"No se pudo obtener el certificado intermedio de {host}.")
    with open(certifi.where()) as f:
        roots = f.read()
    fd, path = tempfile.mkstemp(prefix="ordolab-ca-", suffix=".pem")
    with os.fdopen(fd, "w") as f:
        f.write(roots + "\n" + "\n".join(intermediates))
    return path


def download_bcv(url: str | None = None):
    url = url or BCV_URL
    headers = {"User-Agent": USER_AGENT}
    try:
        return requests.get(url, timeout=TIMEOUT, headers=headers)
    except requests.exceptions.SSLError:
        log.info("BCV sin certificado intermedio: se completa la cadena por AIA.")
        parsed = urlparse(url)
        bundle = _ca_bundle_with_intermediates(parsed.hostname, parsed.port or 443)
        try:
            return requests.get(url, timeout=TIMEOUT, headers=headers, verify=bundle)
        finally:
            os.remove(bundle)


def register_official_rate(
    *, rate: Decimal, effective_date: datetime.date | None = None,
    source: str = OfficialRate.Source.BCV, from_code: str = "USD",
    to_code: str = "VES", notes: str = "",
) -> OfficialRate:
    """Registra (o corrige) la tasa global de una fecha.

    No cambia el esquema de la conexión: `OfficialRate` es un modelo compartido y su
    tabla sólo existe en `public`, que django-tenants siempre deja en el `search_path`.
    Forzar aquí `set_schema_to_public()` dejaría la conexión apuntando a `public` para
    todo lo que viniera después —incluido el resto de la petición o del test.
    """
    if rate <= 0:
        raise ValueError("La tasa debe ser mayor que cero.")
    official_rate, _ = OfficialRate.objects.update_or_create(
        from_code=from_code, to_code=to_code,
        effective_date=effective_date or timezone.localdate(),
        defaults={"rate": rate, "source": source, "notes": notes},
    )
    return official_rate


def update_from_bcv() -> OfficialRate:
    """Consulta el BCV y registra la tasa del día. Devuelve la fila o lanza excepción."""
    response = download_bcv()
    response.raise_for_status()
    return register_official_rate(rate=read_rate_from_html(response.text))
