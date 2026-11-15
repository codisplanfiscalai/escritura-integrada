"""Supported Prosoft record selections; deliberately independent of SPED tooling."""
from .core import DomainError

FISCAL_TYPES = ('incoming_notes', 'outgoing_notes')
ACCOUNTING_TYPES = ('LC1', 'LC2', 'CTA')


def selected_types(mode, value=None):
    supported = FISCAL_TYPES if mode == 'fiscal' else ACCOUNTING_TYPES
    if value is None: return list(supported)  # Preserve PR40's explicit API behavior.
    if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value) or len(set(value)) != len(value) or not set(value) <= set(supported):
        raise DomainError('Selecione somente os tipos de registro Prosoft disponíveis neste perfil.')
    if mode == 'accounting' and not {'LC1', 'LC2'} <= set(value):
        raise DomainError('LC1 e LC2 formam o perfil de lançamentos; CTA é complemento opcional.')
    return [kind for kind in supported if kind in value]
