"""Supported Prosoft record selections; deliberately independent of SPED tooling."""
import re
from .core import DomainError

FISCAL_TYPES = ('incoming_notes', 'outgoing_notes')
ACCOUNTING_TYPES = ('LC1', 'LC2', 'CTA', 'TRC')


def valid_fiscal_species(value):
    # Windows species fields are five positions (fiscal PDF pp.3/13).
    # Accept the two explicitly requested spellings without allowing arbitrary punctuation.
    # This validates representation only; destination registration still needs confirmation.
    return isinstance(value, str) and (value in ('NF-E', 'NFC-E') or re.fullmatch('[A-Z0-9]{1,5}', value) is not None)


def selected_types(mode, value=None):
    supported = FISCAL_TYPES if mode == 'fiscal' else ACCOUNTING_TYPES
    if value is None: return list(FISCAL_TYPES if mode == 'fiscal' else ('LC1', 'LC2', 'CTA'))  # TRC requires explicit opt-in.
    if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value) or len(set(value)) != len(value) or not set(value) <= set(supported):
        raise DomainError('Selecione somente os tipos de registro Prosoft disponíveis neste perfil.')
    if mode == 'accounting' and not {'LC1', 'LC2'} <= set(value):
        raise DomainError('LC1 e LC2 formam o perfil de lançamentos; CTA é complemento opcional.')
    return [kind for kind in supported if kind in value]
