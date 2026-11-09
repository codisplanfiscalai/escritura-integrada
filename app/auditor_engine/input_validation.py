class FiscalInputError(ValueError):
    def __init__(self,error_code:str,detail:str,technical_message:str):
        super().__init__(technical_message)
        self.error_code=error_code
        self.detail=detail
        self.technical_message=technical_message


class CompanyDocumentMismatch(FiscalInputError):
    def __init__(self):
        super().__init__(
            'XML_COMPANY_MISMATCH',
            'O XML não pertence ao cliente auditado selecionado.',
            'O CNPJ do cliente selecionado não consta como emitente nem destinatário da NF-e. Selecione o cliente correto ou remova o XML do lote.',
        )


class DuplicateItemNumber(FiscalInputError):
    def __init__(self):
        super().__init__(
            'XML_DUPLICATE_ITEM_NUMBER',
            'O XML contém itens com numeração duplicada.',
            'A NF-e repete o atributo nItem e foi recusada para impedir colisão e totalização incorreta no banco de dados.',
        )


class InvalidItemNumber(FiscalInputError):
    def __init__(self):
        super().__init__(
            'XML_INVALID_ITEM_NUMBER',
            'O XML contém um item com numeração inválida.',
            'A NF-e possui atributo nItem ausente, não numérico ou menor que 1 e foi recusada antes da persistência.',
        )
