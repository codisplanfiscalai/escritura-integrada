"""Mensagens operacionais das críticas do livro; códigos preservados na API."""
MESSAGES = {
    'FISCAL_TREATMENT_REQUIRED': (
        'Tratamento fiscal do livro não definido.',
        'Revise o perfil de escrituração do documento antes de concluir os valores fiscais do livro.'),
    'INVALID_FISCAL_TREATMENT': (
        'Tratamento fiscal inválido ou fora da vigência.',
        'Confira o perfil, a vigência e a data de escrituração.'),
    'DECLARED_ICMS_MISSING': (
        'Base ou ICMS declarado sem informação completa.',
        'Confira o documento de origem. Valor ausente não representa imposto zero.'),
    'OTHER_IPI_TREATMENT_REQUIRED': (
        'Tratamento de Outras ou do IPI ainda não definido.',
        'Revise essas parcelas separadamente; a decisão sobre ICMS não define o IPI.'),
    'CFOP_REQUIRED': (
        'CFOP da linha não definido.',
        'Confira a natureza da operação e a classificação da linha.'),
    'INVALID_POSTING_GROUP_REVIEW': (
        'Agrupamento revisado precisa de nova conferência.',
        'Confira todos os itens e a evidência da divisão ou consolidação, sem forçar valores.'),
    'C190_TOTAL_MISMATCH': (
        'Total dos registros analíticos difere do cabeçalho.',
        'Confira a composição dos registros C190 e as parcelas do documento.'),
    'HEADER_COMPONENT_ALLOCATED': (
        'Parcela do cabeçalho foi distribuída entre as linhas.',
        'Confira o rateio de frete, desconto e demais componentes na origem.'),
    'TOTAL_ALLOCATION_REVIEW': (
        'Composição do valor contábil precisa de conferência.',
        'Confira itens, frete, desconto e demais componentes, sem alterar o total para forçar coincidência.'),
    'NO_CONTRIBUTING_ITEMS': (
        'Não há itens contribuintes para distribuir o valor.',
        'Confira itens e composição do documento antes de definir o rateio.'),
    'NEGATIVE_ALLOCATION_REVIEW': (
        'Uma parcela distribuída ficou negativa.',
        'Confira descontos, componentes e grupos da escrituração.'),
}


def fiscal_review(code):
    code = str(code)
    if code.startswith('DECLARED_') and code.endswith('_INCOMPLETE'):
        name = code[len('DECLARED_'):-len('_INCOMPLETE')]
        label = {'ICMS': 'ICMS', 'ICMS_BASE': 'base do ICMS', 'IPI': 'IPI', 'IPI_BASE': 'base do IPI'}.get(name)
        if label:
            return {'code': code, 'message': f'Informação declarada de {label} incompleta.',
                    'next_step': 'Confira a cobertura dos itens na origem; a soma conhecida é parcial.'}
    message, action = MESSAGES.get(code, (
        'Pendência fiscal não reconhecida; revise o registro.',
        'Abra a origem para conferir a evidência e o código da ocorrência.'))
    return {'code': code, 'message': message, 'next_step': action}


def pending_message(code):
    return fiscal_review(code)['message']
