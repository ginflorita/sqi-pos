"""Create a local TLS certificate; import the certificate on each trusted laptop."""
import argparse
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True, help='Reserved host LAN IPv4 address, e.g. 192.168.1.10')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / 'certs')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.ip)
    if not address.is_private or address.is_loopback:
        parser.error('Use the private LAN IP assigned to the host laptop.')
    args.output.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = args.output / 'pos.crt', args.output / 'pos.key'
    if cert_path.exists() or key_path.exists():
        parser.error('Certificate files already exist. Use a new output directory for renewal.')
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SQI POS local server')])
    current = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(minutes=5))
            .not_valid_after(current+timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.DNSName(socket.gethostname()),
                           x509.IPAddress(ipaddress.ip_address('127.0.0.1')),x509.IPAddress(address)]), critical=False)
            .sign(private, hashes.SHA256()))
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f'Certificate: {cert_path.resolve()}\nPrivate key: {key_path.resolve()}')
    print(f'SHA256 fingerprint: {cert.fingerprint(hashes.SHA256()).hex(":")}')
    print('Copy only pos.crt to the second laptop. Keep pos.key on the host with restricted permissions.')
    print(f'After trusting the certificate on both laptops, open https://{address}:8765')


if __name__ == '__main__':
    main()
