"""Explicit trusted proxy addresses for the container entry point.

Forwarded headers remain Uvicorn's responsibility. Never infer HTTPS from Host
or a client-supplied header inside a sensitive route.
"""
import ipaddress
import os


def forwarded_allow_ips(environ=None):
    raw = (os.environ if environ is None else environ).get('FORWARDED_ALLOW_IPS', '127.0.0.1')
    if not raw.strip():
        return ''
    values = []
    for entry in raw.split(','):
        try:
            value = entry.strip()
            network = ipaddress.ip_network(value, strict=False)
            if not network.prefixlen:
                raise ValueError()
        except ValueError:
            raise ValueError('FORWARDED_ALLOW_IPS deve conter IPs/CIDRs explícitos do proxy confiável; curinga e rede global são recusados.') from None
        values.append(str(network) if '/' in value else str(network.network_address))
    return ','.join(values)
