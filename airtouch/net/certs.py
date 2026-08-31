"""Certificado TLS propio para el servidor de AirLink.

Hace falta HTTPS por dos motivos que se combinan mal:

  * ``getUserMedia`` solo entrega la camara en un contexto seguro.
  * Una pagina HTTPS no puede abrir ``ws://`` contra una IP local; el navegador
    lo bloquea por contenido mixto.

Asi que el PC sirve la pagina por HTTPS y la senalizacion por ``wss://``, todo
en el mismo origen. El certificado lo genera el propio programa: no hay ninguna
autoridad que lo firme, por eso Safari avisa la primera vez.

El certificado incluye TODAS las direcciones IP del equipo como SAN, para que
valga sea cual sea la interfaz por la que entre el movil.
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import logging
import socket

from ..config import app_data_dir

log = logging.getLogger(__name__)

CERT_DIR = app_data_dir() / "cert"
CERT_FILE = CERT_DIR / "airlink-cert.pem"
KEY_FILE = CERT_DIR / "airlink-key.pem"

#: Los navegadores modernos rechazan certificados de mas de ~13 meses.
VALID_DAYS = 370


def route_ip() -> str:
    """IP de la interfaz por la que sale el trafico de verdad.

    Abrir un socket UDP "hacia fuera" no envia nada, pero obliga al sistema a
    elegir ruta y revela que interfaz usaria. Es la unica forma fiable de
    saberlo cuando hay Ethernet y WiFi conectados a la vez.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


def local_ips() -> list[str]:
    """Direcciones IPv4 del equipo, sin loopback ni link-local."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except Exception:
        pass
    ip = route_ip()
    if ip:
        found.add(ip)
    # 169.254.x.x son direcciones de "no hay red": no sirven para nada aqui
    return sorted(i for i in found
                  if not i.startswith("127.") and not i.startswith("169.254."))


def preferred_ip() -> str:
    """La IP que debe anunciarse al movil.

    Manda la de la ruta por defecto. Si se ordenaran las IPs sin mas, con
    Ethernet y WiFi a la vez el resultado podria cambiar de un arranque a otro
    y el QR dejaria de servir.
    """
    ip = route_ip()
    if ip and not ip.startswith("169.254."):
        return ip
    ips = local_ips()
    for prefix in ("192.168.", "10.", "172."):
        for candidate in ips:
            if candidate.startswith(prefix):
                return candidate
    return ips[0] if ips else "127.0.0.1"


def _covers_current_ips(cert_path) -> bool:
    """True si el certificado guardado ya incluye las IPs de ahora."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(data)
        if cert.not_valid_after_utc < _dt.datetime.now(_dt.timezone.utc):
            return False
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        have = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
        return set(local_ips()).issubset(have)
    except Exception:
        return False


def ensure_cert(force: bool = False) -> tuple[str, str]:
    """Devuelve (ruta_cert, ruta_clave), generandolos si hace falta."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if not force and CERT_FILE.exists() and KEY_FILE.exists() \
            and _covers_current_ips(CERT_FILE):
        return str(CERT_FILE), str(KEY_FILE)

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "AirTouch AirLink"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AirTouch"),
    ])

    alt: list[x509.GeneralName] = [x509.DNSName("localhost")]
    alt.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
    for ip in local_ips():
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    try:
        alt.append(x509.DNSName(socket.gethostname()))
    except Exception:
        pass

    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                       critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Certificado de AirLink generado para %s", local_ips())
    return str(CERT_FILE), str(KEY_FILE)


def ssl_context():
    """Contexto SSL listo para aiohttp."""
    import ssl

    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx
