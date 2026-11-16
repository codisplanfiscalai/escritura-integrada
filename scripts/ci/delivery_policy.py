"""Política temporária versionada. Retomar desktop exige alterar e revisar este arquivo."""
# Pausa autorizada: develop entrega somente GHCR; main conserva todos os gates.
DEVELOP_DESKTOP_ENABLED = False


def delivery_mode(branch):
    return 'ghcr_only' if branch == 'develop' and not DEVELOP_DESKTOP_ENABLED else 'full'


def desktop_enabled(base_branch):
    return delivery_mode(base_branch) == 'full'


def validate_delivery(plan):
    mode = plan.get('delivery_mode', 'full')  # planos anteriores continuam completos
    if mode not in ('full', 'ghcr_only') or (mode == 'ghcr_only' and plan.get('branch') != 'develop'):
        raise ValueError('Entrega somente GHCR é permitida exclusivamente em develop.')
    return mode
