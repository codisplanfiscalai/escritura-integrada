"""Serviços de domínio explícitos, sem regras tributárias presumidas.

Centavos inteiros na persistência; Decimal nas fronteiras. Todos os efeitos de
uma operação e suas verificações de competência pertencem à mesma transação.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .db import Database


class DomainError(Exception):
    def __init__(self, detail: str, status: int = 400, code: str = "invalid_input"):
        super().__init__(detail)
        self.detail, self.status, self.code = detail, status, code


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256((value if isinstance(value, bytes) else pack(value).encode())).hexdigest()


def semantic_value(value):
    """Exclude origin locators from equality; renaming a file is not a new invoice."""
    if isinstance(value, dict):
        return {key: semantic_value(item) for key, item in value.items() if key not in {"source", "source_hash"}}
    if isinstance(value, list):
        return [semantic_value(item) for item in value]
    return value


def text(value, label="Campo", required=False, maximum=500):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DomainError(f"{label}: informe texto.")
    value = value.strip()
    if required and not value:
        raise DomainError(f"{label} é obrigatório.")
    if len(value) > maximum:
        raise DomainError(f"{label} excede {maximum} caracteres.")
    return value


def boolean(value, default=False):
    if value is None:
        return default
    if not isinstance(value, bool):
        raise DomainError("Informe um valor booleano verdadeiro ou falso.")
    return value


def integer(value, label="Identificador", minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DomainError(f"{label} inválido.")
    return value


def iso_date(value, label="Data"):
    value = text(value, label, True, 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DomainError(f"{label}: use AAAA-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DomainError(f"{label} inválida.")
    return value


def period(value):
    value = text(value, "Competência", True, 7)
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise DomainError("Competência inválida; use AAAA-MM.")
    iso_date(value + "-01", "Competência")
    return value


def money(value, label="Valor", *, signed=False, positive=False):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise DomainError(f"{label}: use string decimal com ponto, sem separador de milhar.")
    raw = str(value)
    if not re.fullmatch(r"-?\d{1,13}(?:\.\d{1,8})?", raw):
        raise DomainError(f"{label}: valor decimal inválido.")
    number = Decimal(raw)
    cents = number * 100
    if cents != cents.to_integral_value():
        raise DomainError(f"{label}: informe no máximo duas casas decimais significativas.")
    cents = int(cents)
    if abs(cents) > 999_999_999_999_99:
        raise DomainError(f"{label} excede o limite suportado.")
    if (not signed and cents < 0) or (positive and cents <= 0):
        raise DomainError(f"{label} deve ser {'positivo' if positive else 'maior ou igual a zero'}.")
    return cents


def decimal_text(cents):
    return f"{Decimal(cents) / 100:.2f}"


def cnpj_digits(base):
    if not re.fullmatch(r"[A-Z0-9]{12}", base):
        raise DomainError("Base de CNPJ inválida.")
    values = [ord(char) - 48 for char in base]
    rest = sum(v * w for v, w in zip(values, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])) % 11
    first = 0 if rest < 2 else 11 - rest
    rest = sum(v * w for v, w in zip(values + [first], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])) % 11
    return str(first) + str(0 if rest < 2 else 11 - rest)


def normalize_cnpj(value):
    raw = text(value, "CNPJ", True, 30).upper()
    raw = re.sub(r"[.\s/\-]", "", raw)
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", raw):
        raise DomainError("CNPJ deve ter 12 posições numéricas/alfanuméricas e 2 dígitos verificadores.")
    if len(set(raw)) == 1 or cnpj_digits(raw[:12]) != raw[-2:]:
        raise DomainError("Dígitos verificadores do CNPJ inválidos.")
    return raw


def json_value(value, expected, label):
    if not isinstance(value, expected):
        raise DomainError(f"{label} tem formato inválido.")
    try:
        encoded = pack(value)
    except (ValueError, TypeError):
        raise DomainError(f"{label} contém valor inválido.")
    if len(encoded) > 2_000_000:
        raise DomainError(f"{label} excede o limite suportado.")
    return encoded


def select_one(conn, table, company_id, item_id):
    # Table names are constants in service code, never request values.
    row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND company_id=?", (item_id, company_id)).fetchone()
    if row is None:
        raise DomainError("Registro não encontrado nesta empresa.", 404, "not_found")
    return dict(row)


def company_row(conn, company_id):
    row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    if row is None:
        raise DomainError("Empresa não encontrada.", 404, "not_found")
    return dict(row) | {"profile": json.loads(row["profile_json"])}


def check_version(row, payload):
    version = integer(payload.get("version"), "Versão")
    if row["version"] != version:
        raise DomainError("Este registro foi alterado. Atualize os dados antes de salvar.", 409, "stale_version")


def audit(conn, company_id, actor, action, entity, entity_id, details=None):
    conn.execute("INSERT INTO audit(company_id,actor,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?)",
                 (company_id, actor, action, entity, str(entity_id), pack(details or {}), now()))


def ensure_open(conn, company_id, competence, module):
    lock = conn.execute("SELECT closed FROM period_locks WHERE company_id=? AND period=? AND module=?",
                        (company_id, competence, module)).fetchone()
    if lock and lock["closed"]:
        title = "fiscal" if module == "fiscal" else "contábil"
        raise DomainError(f"A competência {competence} está fechada no módulo {title}.", 409, "period_closed")


COMPANY_FIELDS = ("code", "name", "trade_name", "tax_id", "regime", "state", "city", "address", "number", "district", "postal_code", "ibge", "ie", "im", "cnae", "email", "phone", "prosoft_code", "profile_json")
REGIMES = {"simples_nacional", "lucro_presumido", "lucro_real", "outros"}


class Core:
    def __init__(self, db: Database, demo=False):
        self.db, self.demo = db, demo
        if demo:
            self.seed_demo()

    # Session state is per authenticated session; no process-global active company.
    def session(self, token):
        with self.db.read() as conn:
            setup_required = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
            row = None
            if token:
                row = conn.execute("SELECT s.*,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=? AND expires_at>? AND u.active=1", (digest(token.encode()), time.time())).fetchone()
            if row is None:
                return {"authenticated": False, "setup_required": setup_required, "demo": self.demo, "user": None, "csrf_token": None, "active_company_id": None, "period": "2026-11" if self.demo else date.today().strftime("%Y-%m")}
            return {"authenticated": True, "setup_required": False, "demo": self.demo, "user": {"id": row["user_id"], "username": row["username"], "role": row["role"]}, "csrf_token": row["csrf_token"], "active_company_id": row["active_company_id"], "period": row["period"]}

    def _new_session(self, conn, user_id):
        token = secrets.token_urlsafe(32)
        company_id = None
        if self.demo:
            row = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
            company_id = row["id"] if row else None
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,active_company_id,period,expires_at,created_at) VALUES(?,?,?,?,?,?,?)", (digest(token.encode()), user_id, secrets.token_urlsafe(32), company_id, "2026-11" if self.demo else date.today().strftime("%Y-%m"), time.time() + 43200, now()))
        return token

    @staticmethod
    def _password_hash(password):
        salt = secrets.token_hex(16)
        value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
        return f"pbkdf2_sha256$600000${salt}${value}"

    @staticmethod
    def _password_valid(password, stored):
        try:
            _, rounds, salt, expected = stored.split("$")
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    def setup(self, payload):
        username = text(payload.get("username"), "Usuário", True, 100)
        password = text(payload.get("password"), "Senha", True, 256)
        if len(password) < 12:
            raise DomainError("Use uma senha com pelo menos 12 caracteres.")
        hashed = self._password_hash(password)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise DomainError("A configuração inicial já foi concluída.", 409, "already_setup")
            user_id = conn.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)", (username, hashed, now())).lastrowid
            audit(conn, None, username, "setup", "user", user_id)
            return self._new_session(conn, user_id)

    def login(self, payload, remote=""):
        username = text(payload.get("username"), "Usuário", True, 100)
        password = text(payload.get("password"), "Senha", True, 256)
        key = digest([remote, username.casefold()])
        with self.db.read() as conn:
            attempt = conn.execute("SELECT * FROM login_attempts WHERE attempt_key=?", (key,)).fetchone()
            user = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if attempt and attempt["locked_until"] > time.time():
            raise DomainError("Muitas tentativas. Aguarde alguns minutos e tente novamente.", 429, "rate_limited")
        # A real KDF is also performed for unknown usernames.
        valid = self._password_valid(password, user["password_hash"] if user else "pbkdf2_sha256$600000$00000000000000000000000000000000$" + "0" * 64)
        if not valid or user is None or not user["active"]:
            with self.db.transaction() as conn:
                current = conn.execute("SELECT failures FROM login_attempts WHERE attempt_key=?", (key,)).fetchone()
                failures = (current["failures"] if current else 0) + 1
                conn.execute("INSERT INTO login_attempts VALUES(?,?,?) ON CONFLICT(attempt_key) DO UPDATE SET failures=excluded.failures,locked_until=excluded.locked_until", (key, failures, time.time() + 300 if failures >= 5 else 0))
            raise DomainError("Usuário ou senha inválidos.", 401, "invalid_credentials")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_attempts WHERE attempt_key=?", (key,))
            return self._new_session(conn, user["id"])

    def demo_login(self):
        if not self.demo:
            raise DomainError("Recurso disponível somente em demonstração.", 404, "not_found")
        with self.db.transaction() as conn:
            user = conn.execute("SELECT id FROM users WHERE username='demonstracao'").fetchone()
            if user is None:
                # Random unexposed password; this user cannot be used outside explicit demo mode.
                uid = conn.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)", ("demonstracao", self._password_hash(secrets.token_urlsafe(40)), now())).lastrowid
            else:
                uid = user["id"]
            return self._new_session(conn, uid)

    def logout(self, token):
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token.encode()),))

    def context(self, token, payload):
        cid = integer(payload.get("company_id"), "Empresa")
        competence = period(payload.get("period"))
        with self.db.transaction() as conn:
            company_row(conn, cid)
            conn.execute("UPDATE sessions SET active_company_id=?,period=? WHERE token_hash=?", (cid, competence, digest(token.encode())))
        return self.session(token)

    def companies(self):
        with self.db.read() as conn:
            return [dict(row) | {"profile": json.loads(row["profile_json"])} for row in conn.execute("SELECT * FROM companies ORDER BY code COLLATE NOCASE")]

    def _company_values(self, payload, previous=None):
        values = {key: text(payload.get(key, previous.get(key, "") if previous else ""), key, key in {"code", "name", "tax_id", "regime"}, 500) for key in COMPANY_FIELDS if key != "profile_json"}
        from .cadastros import profile_values
        values["profile_json"] = pack(profile_values(payload.get("profile", {}), json.loads(previous.get("profile_json", "{}")) if previous else {}))
        values["tax_id"] = normalize_cnpj(values["tax_id"])
        if values["regime"] not in REGIMES:
            raise DomainError("Regime deve ser simples_nacional, lucro_presumido, lucro_real ou outros.")
        values["state"] = values["state"].upper()
        if values["state"] and values["state"] not in set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO EX".split()):
            raise DomainError("UF inválida.")
        for key, length in (("postal_code", 8), ("ibge", 7), ("cnae", 7)):
            values[key] = re.sub(r"[.\-/ ]", "", values[key])
            if values[key] and not re.fullmatch(rf"\d{{{length}}}", values[key]):
                raise DomainError(f"{key} deve conter {length} dígitos.")
        if values["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"]):
            raise DomainError("E-mail inválido.")
        return values

    def create_company(self, payload, actor):
        values = self._company_values(payload)
        initial = boolean(payload.get("create_default_accounts"), False)
        with self.db.transaction() as conn:
            cid = conn.execute(f"INSERT INTO companies({','.join(COMPANY_FIELDS)},created_at,updated_at) VALUES({','.join('?' for _ in range(len(COMPANY_FIELDS)+2))})", (*values.values(), now(), now())).lastrowid
            if initial:
                self._default_accounts(conn, cid)
            audit(conn, cid, actor, "create", "company", cid, {"code": values["code"], "default_accounts": initial})
            return company_row(conn, cid)

    def update_company(self, company_id, payload, actor):
        with self.db.transaction() as conn:
            old = company_row(conn, company_id)
            check_version(old, payload)
            values = self._company_values(payload, old)
            if values["tax_id"] != old["tax_id"]:
                for table in ("journals", "documents", "titles", "bank_transactions", "imports"):
                    if conn.execute(f"SELECT 1 FROM {table} WHERE company_id=? LIMIT 1", (company_id,)).fetchone():
                        raise DomainError("O CNPJ não pode ser trocado após registrar movimentos ou importações. Cadastre a outra pessoa jurídica separadamente.", 409, "company_identity_in_use")
            conn.execute(f"UPDATE companies SET {','.join(key+'=?' for key in COMPANY_FIELDS)},version=version+1,updated_at=? WHERE id=?", (*values.values(), now(), company_id))
            changed = {k: {"before": old[k], "after": v} for k, v in values.items() if old[k] != v}
            audit(conn, company_id, actor, "update", "company", company_id, changed)
            return company_row(conn, company_id)

    def _default_accounts(self, conn, cid):
        for code, classifier, name, nature in [
            ("1", "1.1.01.001", "Caixa", "debit"), ("2", "1.1.02.001", "Bancos conta movimento", "debit"),
            ("3", "1.1.03.001", "Clientes", "debit"), ("4", "2.1.01.001", "Fornecedores", "credit"),
            ("5", "3.1.01.001", "Receitas operacionais", "credit"), ("6", "4.1.01.001", "Despesas operacionais", "debit")]:
            conn.execute("INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,requires_cost_center) VALUES(?,?,?,?,?,1,0)", (cid, code, classifier, name, nature))

    def accounts(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            rows = [dict(r) for r in conn.execute("SELECT * FROM accounts WHERE company_id=? ORDER BY classifier", (cid,))]
            for row in rows:
                for flag in ("analytical", "requires_cost_center", "active"):
                    row[flag] = bool(row[flag])
            return rows

    def save_account(self, cid, payload, actor, item_id=None):
        with self.db.transaction() as conn:
            company_row(conn, cid)
            old = select_one(conn, "accounts", cid, item_id) if item_id else {}
            if old:
                check_version(old, payload)
            values = {k: text(payload.get(k, old.get(k, "")), k, True, 200) for k in ("access_code", "classifier", "name", "nature")}
            values["report_group"] = text(payload.get("report_group", old.get("report_group", "")), "Grupo do demonstrativo", False, 30)
            values["prosoft_code"] = text(payload.get("prosoft_code", old.get("prosoft_code", "")), "Acesso Prosoft", False, 5)
            if values["report_group"] not in {"", "asset", "liability", "equity", "revenue", "expense"}:
                raise DomainError("Grupo do demonstrativo inválido.")
            if values["prosoft_code"] and (not values["prosoft_code"].isdigit() or int(values["prosoft_code"]) == 0):
                raise DomainError("Acesso Prosoft deve conter até cinco dígitos, maior que zero.")
            if values["nature"] not in {"debit", "credit"}:
                raise DomainError("Natureza deve ser debit ou credit.")
            for flag, default in (("analytical", True), ("requires_cost_center", False), ("active", True)):
                values[flag] = boolean(payload.get(flag), bool(old.get(flag, default)))
            if old and conn.execute("SELECT 1 FROM journal_lines WHERE company_id=? AND account_id=? LIMIT 1", (cid, item_id)).fetchone():
                if not values["analytical"] or values["nature"] != old["nature"] or values["requires_cost_center"] != bool(old["requires_cost_center"]):
                    raise DomainError("Conta utilizada: natureza, tipo e exigência de centro devem ser preservados. Crie uma nova conta para outra política.", 409, "account_in_use")
            if item_id:
                conn.execute(f"UPDATE accounts SET {','.join(k+'=?' for k in values)},version=version+1 WHERE id=? AND company_id=?", (*values.values(), item_id, cid))
            else:
                item_id = conn.execute(f"INSERT INTO accounts(company_id,{','.join(values)}) VALUES({','.join('?' for _ in range(len(values)+1))})", (cid, *values.values())).lastrowid
            audit(conn, cid, actor, "update" if old else "create", "account", item_id, values)
            return select_one(conn, "accounts", cid, item_id)

    def cost_centers(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            return [dict(r) | {"active": bool(r["active"])} for r in conn.execute("SELECT * FROM cost_centers WHERE company_id=? ORDER BY code", (cid,))]

    def save_cost_center(self, cid, payload, actor, item_id=None):
        with self.db.transaction() as conn:
            company_row(conn, cid)
            old = select_one(conn, "cost_centers", cid, item_id) if item_id else {}
            if old:
                check_version(old, payload)
            values = {k: text(payload.get(k, old.get(k, "")), k, True, 200) for k in ("code", "name")}
            values["active"] = boolean(payload.get("active"), bool(old.get("active", True)))
            if old:
                conn.execute("UPDATE cost_centers SET code=?,name=?,active=?,version=version+1 WHERE id=? AND company_id=?", (*values.values(), item_id, cid))
            else:
                item_id = conn.execute("INSERT INTO cost_centers(company_id,code,name,active) VALUES(?,?,?,?)", (cid, *values.values())).lastrowid
            audit(conn, cid, actor, "update" if old else "create", "cost_center", item_id, values)
            return select_one(conn, "cost_centers", cid, item_id)

    def _journal(self, conn, cid, item_id):
        result = select_one(conn, "journals", cid, item_id)
        result.pop("request_hash", None)
        result["status"] = "reversed" if result["reversed_by"] else "posted"
        result["lines"] = [dict(r) for r in conn.execute("SELECT l.*,a.access_code,a.classifier,a.name AS account_name,c.name AS cost_center_name FROM journal_lines l JOIN accounts a ON a.id=l.account_id LEFT JOIN cost_centers c ON c.id=l.cost_center_id WHERE l.journal_id=? AND l.company_id=? ORDER BY l.position", (item_id, cid))]
        return result

    def journals(self, cid, competence=None):
        with self.db.read() as conn:
            company_row(conn, cid)
            clause, params = (" AND period=?", (cid, period(competence))) if competence else ("", (cid,))
            ids = [r["id"] for r in conn.execute("SELECT id FROM journals WHERE company_id=?" + clause + " ORDER BY date DESC,id DESC", params)]
            return [self._journal(conn, cid, key) for key in ids]

    def _normalize_lines(self, conn, cid, lines, allow_inactive=False):
        if not isinstance(lines, list) or not 2 <= len(lines) <= 1000:
            raise DomainError("O lançamento deve conter de 2 a 1000 partidas.")
        result = []
        for position, line in enumerate(lines, 1):
            if not isinstance(line, dict):
                raise DomainError("Partida inválida.")
            aid = integer(line.get("account_id"), "Conta")
            account = select_one(conn, "accounts", cid, aid)
            if not account["analytical"] or (not account["active"] and not allow_inactive):
                raise DomainError("Selecione uma conta analítica ativa.")
            debit = money(line.get("debit", "0.00"), "Débito")
            credit = money(line.get("credit", "0.00"), "Crédito")
            if (debit > 0) == (credit > 0):
                raise DomainError(f"Partida {position}: informe somente débito ou crédito, maior que zero.")
            center = line.get("cost_center_id")
            if center is not None:
                center = integer(center, "Centro de custo")
                cc = select_one(conn, "cost_centers", cid, center)
                if not cc["active"] and not allow_inactive:
                    raise DomainError("Centro de custo inativo.")
            if account["requires_cost_center"] and center is None:
                raise DomainError(f"A conta {account['access_code']} exige centro de custo.")
            result.append({"account_id": aid, "debit_cents": debit, "credit_cents": credit, "cost_center_id": center})
        debit, credit = sum(x["debit_cents"] for x in result), sum(x["credit_cents"] for x in result)
        if debit != credit or debit <= 0:
            raise DomainError("Lançamento não balanceado: débitos e créditos devem ser iguais e maiores que zero.", 400, "unbalanced_journal")
        if debit > 999_999_999_999_99:
            raise DomainError("Total do lançamento excede o limite suportado.")
        return result, debit

    def _create_journal(self, conn, cid, payload, actor, reversal_of=None):
        company_row(conn, cid)
        day = iso_date(payload.get("date"))
        document = text(payload.get("document"), "Documento", False, 100)
        history = text(payload.get("history"), "Histórico", True, 2000)
        key = text(payload.get("idempotency_key"), "Chave de idempotência", True, 200)
        lines, total = self._normalize_lines(conn, cid, payload.get("lines"), allow_inactive=reversal_of is not None)
        hashed = digest({"date": day, "document": document, "history": history, "lines": lines, "reversal_of": reversal_of})
        existing = conn.execute("SELECT * FROM journals WHERE company_id=? AND idempotency_key=?", (cid, key)).fetchone()
        if existing:
            if existing["request_hash"] != hashed:
                raise DomainError("Chave de idempotência já utilizada com conteúdo diferente.", 409, "idempotency_conflict")
            return self._journal(conn, cid, existing["id"]) | {"duplicate": True}
        ensure_open(conn, cid, day[:7], "accounting")
        number = conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM journals WHERE company_id=?", (cid,)).fetchone()[0]
        jid = conn.execute("INSERT INTO journals(company_id,number,date,period,document,history,total_cents,idempotency_key,request_hash,reversal_of,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cid, number, day, day[:7], document, history, total, key, hashed, reversal_of, now(), actor)).lastrowid
        for index, line in enumerate(lines, 1):
            conn.execute("INSERT INTO journal_lines(company_id,journal_id,position,account_id,debit_cents,credit_cents,cost_center_id) VALUES(?,?,?,?,?,?,?)", (cid, jid, index, line["account_id"], line["debit_cents"], line["credit_cents"], line["cost_center_id"]))
        if reversal_of:
            conn.execute("UPDATE journals SET reversed_by=? WHERE id=? AND company_id=?", (jid, reversal_of, cid))
        audit(conn, cid, actor, "reverse" if reversal_of else "post", "journal", jid, {"period": day[:7], "total_cents": total, "reversal_of": reversal_of})
        return self._journal(conn, cid, jid)

    def create_journal(self, cid, payload, actor):
        with self.db.transaction() as conn:
            return self._create_journal(conn, cid, payload, actor)

    def reverse_journal(self, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Motivo do estorno", True, 1000)
        with self.db.transaction() as conn:
            original = self._journal(conn, cid, item_id)
            if conn.execute('SELECT 1 FROM documents WHERE company_id=? AND journal_id=?',(cid,item_id)).fetchone() or conn.execute('SELECT 1 FROM settlements WHERE company_id=? AND journal_id=?',(cid,item_id)).fetchone():
                raise DomainError('Estorne pelo documento ou pela baixa de origem para preservar a integração.',409,'linked_journal')
            if iso_date(payload.get('date')) < original['date']:
                raise DomainError('Estorno não pode anteceder o lançamento.')
            if original["reversal_of"]:
                raise DomainError("Um estorno não pode ser estornado por esta rotina.", 409, "invalid_reversal")
            if original["reversed_by"]:
                raise DomainError("O lançamento já possui estorno.", 409, "already_reversed")
            lines = [{"account_id": x["account_id"], "debit": decimal_text(x["credit_cents"]), "credit": decimal_text(x["debit_cents"]), "cost_center_id": x["cost_center_id"]} for x in original["lines"]]
            data = {"date": payload.get("date"), "document": original["document"], "history": f"Estorno do lançamento {original['number']}: {reason}", "idempotency_key": payload.get("idempotency_key") or f"reversal:{item_id}", "lines": lines}
            return self._create_journal(conn, cid, data, actor, reversal_of=item_id)

    def _document(self, conn, cid, item_id):
        result = select_one(conn, "documents", cid, item_id)
        for key in ("taxes", "items", "source"):
            result[key] = json.loads(result.pop(key + "_json"))
        result.update(json.loads(result.pop("extra_json", "{}")))
        result.pop("payload_hash", None)
        result.pop("business_key", None)
        result["sources"] = [{"source_hash": r["source_hash"], "source": json.loads(r["source_json"])} for r in conn.execute("SELECT * FROM document_sources WHERE company_id=? AND document_id=? ORDER BY id", (cid, item_id))]
        return result

    def documents(self, cid, competence=None):
        with self.db.read() as conn:
            company_row(conn, cid)
            clause, params = (" AND period=?", (cid, period(competence))) if competence else ("", (cid,))
            ids = [r["id"] for r in conn.execute("SELECT id FROM documents WHERE company_id=?" + clause + " ORDER BY posting_date DESC,id DESC", params)]
            return [self._document(conn, cid, key) for key in ids]

    def _create_document(self, conn, cid, payload, actor):
        company_row(conn, cid)
        direction = {"entrada": "incoming", "saida": "outgoing"}.get(payload.get("direction"), payload.get("direction"))
        if direction not in {"incoming", "outgoing"}:
            raise DomainError("Informe se o documento é de entrada ou saída.")
        values = {k: text(payload.get(k), k, k in {"number", "model", "partner_name"}, 250) for k in ("number", "series", "model", "partner_name", "partner_tax_id", "key", "cfop")}
        values.update(direction=direction, issue_date=iso_date(payload.get("issue_date"), "Emissão"), posting_date=iso_date(payload.get("posting_date"), "Escrituração"), total_cents=money(payload.get("total"), "Total"))
        if values["cfop"] and not re.fullmatch(r"\d{4}", values["cfop"]):
            raise DomainError("CFOP deve ter quatro dígitos; sua aplicabilidade exige conferência fiscal.")
        taxes = json_value(payload.get("taxes", {}), dict, "Tributos declarados")
        items = json_value(payload.get("items", []), list, "Itens")
        source = json_value(payload.get("source", {"type": "manual"}), dict, "Origem")
        source_hash = text(payload.get("source_hash", ""), "Hash de origem", False, 200)
        business_key = ("key:" + values["key"]) if values["key"] else digest({k: values[k] for k in ("direction", "model", "series", "number", "partner_tax_id", "partner_name", "issue_date")})
        hashed = digest(values | {"taxes": json.loads(taxes), "items": semantic_value(json.loads(items))})
        existing = conn.execute("SELECT * FROM documents WHERE company_id=? AND business_key=?", (cid, business_key)).fetchone()
        if existing:
            if existing["payload_hash"] != hashed:
                raise DomainError("Já existe documento com a mesma identidade e conteúdo diferente. Confira antes de escriturar.", 409, "document_conflict")
            conn.execute("INSERT OR IGNORE INTO document_sources(company_id,document_id,source_hash,source_json,created_at) VALUES(?,?,?,?,?)", (cid, existing["id"], source_hash, source, now()))
            return self._document(conn, cid, existing["id"]) | {"duplicate": True}
        ensure_open(conn, cid, values["posting_date"][:7], "fiscal")
        extras = {k: payload[k] for k in ("source_cfops", "cfop_perspective", "document_type", "issuer", "recipient", "environment", "signature_verified", "schema_validated", "authorization", "transport", "invoices", "analytics", "raw_fields", "posting_date_proposed", "declared_new_total", "participant_id", "establishment_id", "document_category") if k in payload}
        values.update(company_id=cid, period=values["posting_date"][:7], taxes_json=taxes, items_json=items, source_json=source, extra_json=pack(extras), source_hash=source_hash, business_key=business_key, payload_hash=hashed, status="pending", created_at=now())
        did = conn.execute(f"INSERT INTO documents({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values())).lastrowid
        conn.execute("INSERT INTO document_sources(company_id,document_id,source_hash,source_json,created_at) VALUES(?,?,?,?,?)", (cid, did, source_hash, source, now()))
        audit(conn, cid, actor, "create", "document", did, {"status": "pending", "source_hash": source_hash, "period": values["period"]})
        return self._document(conn, cid, did)

    def create_document(self, cid, payload, actor):
        with self.db.transaction() as conn:
            return self._create_document(conn, cid, payload, actor)

    def update_document(self, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Motivo da alteração", True, 1000)
        with self.db.transaction() as conn:
            old = select_one(conn, "documents", cid, item_id)
            check_version(old, payload)
            if hasattr(self, "_validate_document_links"):
                self._validate_document_links(conn, cid, {**self._document(conn,cid,item_id),**payload})
            if old["status"] == "booked":
                raise DomainError("Documento escriturado não pode ser editado por esta rotina.", 409, "document_booked")
            values = {k: text(payload.get(k, old[k]), k, k in {"number", "model", "partner_name"}, 250) for k in ("direction", "number", "series", "model", "partner_name", "partner_tax_id", "key", "cfop")}
            if values["direction"] not in {"incoming", "outgoing"}:
                raise DomainError("Informe entrada ou saída.")
            if values["cfop"] and not re.fullmatch(r"\d{4}", values["cfop"]):
                raise DomainError("CFOP deve ter quatro dígitos; confira sua aplicabilidade.")
            values.update(issue_date=iso_date(payload.get("issue_date", old["issue_date"]), "Emissão"), posting_date=iso_date(payload.get("posting_date", old["posting_date"]), "Escrituração"), total_cents=money(payload.get("total", decimal_text(old["total_cents"])), "Total"))
            ensure_open(conn, cid, old["period"], "fiscal")
            ensure_open(conn, cid, values["posting_date"][:7], "fiscal")
            taxes = json_value(payload.get("taxes", json.loads(old["taxes_json"])), dict, "Tributos declarados")
            items = json_value(payload.get("items", json.loads(old["items_json"])), list, "Itens")
            identity = "key:" + values["key"] if values["key"] else digest({k: values[k] for k in ("direction", "model", "series", "number", "partner_tax_id", "partner_name", "issue_date")})
            other = conn.execute("SELECT id FROM documents WHERE company_id=? AND business_key=? AND id<>?", (cid, identity, item_id)).fetchone()
            if other:
                raise DomainError("Já existe outro documento com essa identidade.", 409, "document_conflict")
            extras = json.loads(old["extra_json"])
            for key in ("participant_id", "establishment_id", "document_category"):
                if key in payload:
                    extras[key] = payload[key]
            values.update(payload_hash=digest(values | {"taxes": json.loads(taxes), "items": semantic_value(json.loads(items))}), business_key=identity, period=values["posting_date"][:7], taxes_json=taxes, items_json=items)
            values["extra_json"] = pack(extras)
            conn.execute(f"UPDATE documents SET {','.join(k+'=?' for k in values)},status='pending',reviewed_by=NULL,review_reason=NULL,version=version+1 WHERE id=? AND company_id=?", (*values.values(), item_id, cid))
            audit(conn, cid, actor, "update", "document", item_id, {"reason": reason, "previous_version": old["version"], "before": {k: old[k] for k in values}, "after": values, "review_invalidated": True})
            return self._document(conn, cid, item_id)

    def review_document(self, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Conferência", True, 1000)
        with self.db.transaction() as conn:
            doc = select_one(conn, "documents", cid, item_id)
            check_version(doc, payload)
            ensure_open(conn, cid, doc["period"], "fiscal")
            if doc["status"] != "pending":
                raise DomainError("Somente documento pendente pode ser conferido.", 409, "invalid_status")
            conn.execute("UPDATE documents SET status='reviewed',reviewed_by=?,review_reason=?,version=version+1 WHERE id=? AND company_id=?", (actor, reason, item_id, cid))
            audit(conn, cid, actor, "review", "document", item_id, {"reason": reason})
            return self._document(conn, cid, item_id)

    def book_document(self, cid, item_id, payload, actor):
        with self.db.transaction() as conn:
            return self._book_document(conn, cid, item_id, payload, actor)

    def _book_document(self, conn, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Confirmação de escrituração", True, 1000)
        doc = select_one(conn, "documents", cid, item_id)
        check_version(doc, payload)
        ensure_open(conn, cid, doc["period"], "fiscal")
        if doc["status"] != "reviewed":
            raise DomainError("Confira o documento antes de escriturá-lo.", 409, "invalid_status")
        if doc["model"] in {"55", "65", "57"}:
            items = json.loads(doc["items_json"])
            analytics = json.loads(doc["extra_json"]).get("analytics", [])
            classifications = items if items and doc["model"] in {"55", "65"} else analytics
            if classifications:
                if any(not isinstance(item, dict) or not re.fullmatch(r"\d{4}", str(item.get("cfop", ""))) for item in classifications):
                    raise DomainError("Confira e informe o CFOP de escrituração em cada item/registro analítico. O código do emitente não é convertido automaticamente.", 409, "cfop_required")
            elif not doc["cfop"]:
                raise DomainError("Informe e confira o CFOP de escrituração para este modelo. O código do emitente não é convertido automaticamente.", 409, "cfop_required")
        journal = None
        if payload.get("lines"):
            journal = self._create_journal(conn, cid, {"date": doc["posting_date"], "document": doc["number"], "history": reason, "idempotency_key": payload.get("idempotency_key") or f"fiscal-document:{item_id}", "lines": payload["lines"]}, actor)
        conn.execute("UPDATE documents SET status='booked',booked_by=?,book_reason=?,journal_id=?,version=version+1 WHERE id=? AND company_id=?", (actor, reason, journal["id"] if journal else None, item_id, cid))
        audit(conn, cid, actor, "book", "document", item_id, {"reason": reason, "journal_id": journal["id"] if journal else None})
        return {"document": self._document(conn, cid, item_id), "journal": journal}

    def _title(self, conn, cid, item_id):
        row = select_one(conn, "titles", cid, item_id)
        row["balance_cents"] = row["amount_cents"] - row["paid_cents"]
        row["status"] = "settled" if row["balance_cents"] == 0 else "partial" if row["paid_cents"] else "open"
        row["settlements"] = [dict(r) for r in conn.execute("SELECT id,date,amount_cents,reason,journal_id,created_at FROM settlements WHERE company_id=? AND title_id=? ORDER BY date,id", (cid, item_id))]
        return row

    def titles(self, cid, kind=None):
        if kind and kind not in {"payable", "receivable"}:
            raise DomainError("Tipo de título inválido.")
        with self.db.read() as conn:
            company_row(conn, cid)
            clause, params = (" AND kind=?", (cid, kind)) if kind else ("", (cid,))
            return [self._title(conn, cid, r["id"]) for r in conn.execute("SELECT id FROM titles WHERE company_id=?" + clause + " ORDER BY due_date,id", params)]

    def _create_title(self, conn, cid, payload, actor):
        company_row(conn, cid)
        kind = payload.get("kind")
        if kind not in {"payable", "receivable"}:
            raise DomainError("Tipo deve ser payable ou receivable.")
        values = {k: text(payload.get(k), k, k == "description", 500) for k in ("description", "partner_name", "document")}
        values.update(kind=kind, issue_date=iso_date(payload.get("issue_date"), "Emissão"), due_date=iso_date(payload.get("due_date"), "Vencimento"), amount_cents=money(payload.get("amount"), "Valor do título", positive=True), document_id=payload.get("document_id"))
        if values["document_id"] is not None:
            integer(values["document_id"], "Documento fiscal")
            doc = select_one(conn, "documents", cid, values["document_id"])
            expected = "payable" if doc["direction"] == "incoming" else "receivable"
            if kind != expected:
                raise DomainError("O sentido do título não corresponde ao documento fiscal vinculado.")
        values.update(company_id=cid, created_at=now())
        tid = conn.execute(f"INSERT INTO titles({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values())).lastrowid
        audit(conn, cid, actor, "create", "title", tid, {"amount_cents": values["amount_cents"], "kind": kind})
        return self._title(conn, cid, tid)

    def create_title(self, cid, payload, actor):
        with self.db.transaction() as conn:
            return self._create_title(conn, cid, payload, actor)

    def settle_title(self, cid, item_id, payload, actor):
        amount = money(payload.get("amount"), "Valor da baixa", positive=True)
        day = iso_date(payload.get("date"), "Data da baixa")
        reason = text(payload.get("reason"), "Histórico da baixa", True, 1000)
        key = text(payload.get("idempotency_key"), "Chave de idempotência", True, 200)
        hashed = digest({"title_id": item_id, "amount_cents": amount, "date": day, "reason": reason, "lines": payload.get("lines", [])})
        with self.db.transaction() as conn:
            title = self._title(conn, cid, item_id)
            existing = conn.execute("SELECT * FROM settlements WHERE company_id=? AND idempotency_key=?", (cid, key)).fetchone()
            if existing:
                if existing["request_hash"] != hashed:
                    raise DomainError("Chave de baixa já utilizada com conteúdo diferente.", 409, "idempotency_conflict")
                return {"title": title, "settlement": dict(existing), "journal": self._journal(conn, cid, existing["journal_id"]) if existing["journal_id"] else None, "duplicate": True}
            if amount > title["balance_cents"]:
                raise DomainError("A baixa excede o saldo do título.", 409, "overpayment")
            journal = None
            if payload.get("lines"):
                normalized, total = self._normalize_lines(conn, cid, payload["lines"])
                if total != amount:
                    raise DomainError("O total contábil da baixa deve corresponder ao valor baixado.")
                journal = self._create_journal(conn, cid, {"date": day, "document": title["document"], "history": reason, "idempotency_key": "settlement:" + key, "lines": payload["lines"]}, actor)
            sid = conn.execute("INSERT INTO settlements(company_id,title_id,date,amount_cents,reason,journal_id,idempotency_key,request_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (cid, item_id, day, amount, reason, journal["id"] if journal else None, key, hashed, now())).lastrowid
            conn.execute("UPDATE titles SET paid_cents=paid_cents+?,version=version+1 WHERE id=? AND company_id=?", (amount, item_id, cid))
            audit(conn, cid, actor, "settle", "title", item_id, {"amount_cents": amount, "settlement_id": sid, "journal_id": journal["id"] if journal else None})
            settlement = dict(conn.execute("SELECT id,title_id,date,amount_cents,reason,journal_id,created_at FROM settlements WHERE id=?", (sid,)).fetchone())
            return {"title": self._title(conn, cid, item_id), "settlement": settlement, "journal": journal}

    def _bank(self, conn, cid, item_id):
        result = select_one(conn, "bank_transactions", cid, item_id)
        result["source"] = json.loads(result.pop("source_json"))
        result.pop("payload_hash", None)
        result.pop("fingerprint", None)
        rec = conn.execute("SELECT r.*,t.description AS title_description FROM reconciliations r JOIN titles t ON t.id=r.title_id WHERE r.transaction_id=? AND r.company_id=?", (item_id, cid)).fetchone()
        result["reconciliation"] = dict(rec) if rec else None
        result["reconciled"] = bool(rec)
        return result

    def banks(self, cid, competence=None):
        with self.db.read() as conn:
            company_row(conn, cid)
            clause, params = (" AND substr(date,1,7)=?", (cid, period(competence))) if competence else ("", (cid,))
            return [self._bank(conn, cid, r["id"]) for r in conn.execute("SELECT id FROM bank_transactions WHERE company_id=?" + clause + " ORDER BY date DESC,id DESC", params)]

    def _create_bank(self, conn, cid, payload, bank_account, actor):
        day = iso_date(payload.get("date"), "Data bancária")
        amount = money(payload.get("amount"), "Movimentação bancária", signed=True)
        if amount == 0:
            raise DomainError("Movimentação bancária de valor zero não pode ser conciliada.")
        values = {k: text(payload.get(k), k, k == "description", 1000) for k in ("description", "reference", "external_id")}
        values.update(date=day, amount_cents=amount)
        source = json_value(payload.get("source", {}), dict, "Origem bancária")
        source_hash = text(payload.get("source_hash", ""), "Hash de origem", False, 200)
        # FITID is scoped to company + explicitly chosen bank account. Without a stable
        # bank ID preserve distinct source rows, and deduplicate repeat import of that row.
        fingerprint = "id:" + values["external_id"] if values["external_id"] else "source:" + digest([source_hash, json.loads(source), values])
        hashed = digest(values)
        existing = conn.execute("SELECT * FROM bank_transactions WHERE company_id=? AND bank_account=? AND fingerprint=?", (cid, bank_account, fingerprint)).fetchone()
        if existing:
            if existing["payload_hash"] != hashed:
                raise DomainError("Identificador bancário repetido com conteúdo diferente; confira o arquivo e a conta.", 409, "bank_conflict")
            return self._bank(conn, cid, existing["id"]) | {"duplicate": True}
        values.update(company_id=cid, bank_account=bank_account, source_json=source, source_hash=source_hash, fingerprint=fingerprint, payload_hash=hashed, created_at=now())
        bid = conn.execute(f"INSERT INTO bank_transactions({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values())).lastrowid
        audit(conn, cid, actor, "import", "bank_transaction", bid, {"source_hash": source_hash})
        return self._bank(conn, cid, bid)

    def bank_suggestions(self, cid, item_id):
        with self.db.read() as conn:
            bank = self._bank(conn, cid, item_id)
            if bank["reconciled"]:
                return []
            kind = "receivable" if bank["amount_cents"] > 0 else "payable"
            rows = conn.execute("SELECT t.* FROM titles t LEFT JOIN reconciliations r ON r.title_id=t.id WHERE t.company_id=? AND t.kind=? AND t.amount_cents=? AND r.id IS NULL ORDER BY ABS(julianday(t.due_date)-julianday(?)),t.id LIMIT 20", (cid, kind, abs(bank["amount_cents"]), bank["date"]))
            result = []
            for row in rows:
                difference = abs((date.fromisoformat(row["due_date"]) - date.fromisoformat(bank["date"])).days)
                if difference <= 7:
                    result.append({"title_id": row["id"], "description": row["description"], "amount_cents": row["amount_cents"], "date": row["due_date"], "difference_days": difference, "reason": "Mesmo valor e sentido; vencimento até 7 dias da movimentação. Conferência manual obrigatória."})
            return result

    def reconcile(self, cid, item_id, payload, actor):
        title_id = integer(payload.get("title_id"), "Título")
        reason = text(payload.get("reason"), "Conferência da conciliação", True, 1000)
        with self.db.transaction() as conn:
            bank = self._bank(conn, cid, item_id)
            title = self._title(conn, cid, title_id)
            if title.get('cancelled') or bank.get('allocations') or title.get('allocations'):
                raise DomainError('Título cancelado ou com rateio existente. Confira os vínculos.',409)
            expected = "receivable" if bank["amount_cents"] > 0 else "payable"
            if title["kind"] != expected or title["amount_cents"] != abs(bank["amount_cents"]):
                raise DomainError("Conciliação individual exige mesmo valor total e sentido. Use o rateio para conciliar valores parciais ou agrupados.")
            if bank["reconciled"] or conn.execute("SELECT 1 FROM reconciliations WHERE title_id=?", (title_id,)).fetchone():
                raise DomainError("Movimentação ou título já conciliado.", 409, "already_reconciled")
            rid = conn.execute("INSERT INTO reconciliations(company_id,transaction_id,title_id,reason,created_at,created_by) VALUES(?,?,?,?,?,?)", (cid, item_id, title_id, reason, now(), actor)).lastrowid
            audit(conn, cid, actor, "reconcile", "bank_transaction", item_id, {"title_id": title_id, "reason": reason})
            return dict(conn.execute("SELECT * FROM reconciliations WHERE id=?", (rid,)).fetchone())

    def unreconcile(self, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Motivo para desfazer", True, 1000)
        with self.db.transaction() as conn:
            bank = self._bank(conn, cid, item_id)
            if not bank["reconciliation"]:
                raise DomainError("Vínculo individual ausente. Desfaça os vínculos do rateio quando existentes.", 409, "not_reconciled")
            audit(conn, cid, actor, "unreconcile", "bank_transaction", item_id, {"reason": reason, "previous": bank["reconciliation"]})
            conn.execute("DELETE FROM reconciliations WHERE company_id=? AND transaction_id=?", (cid, item_id))
            return self._bank(conn, cid, item_id)

    def _periods(self, conn, cid, competence):
        result = {"period": competence}
        for module in ("fiscal", "accounting"):
            row = conn.execute("SELECT * FROM period_locks WHERE company_id=? AND period=? AND module=?", (cid, competence, module)).fetchone()
            state = dict(row) if row else {"module": module, "period": competence, "closed": False, "reason": "", "version": 0, "actor": "", "changed_at": None}
            state["closed"] = bool(state["closed"])
            state["status"] = "closed" if state["closed"] else "open"
            result[module] = state
        return result

    def periods(self, cid, competence):
        competence = period(competence)
        with self.db.read() as conn:
            company_row(conn, cid)
            return self._periods(conn, cid, competence)

    def set_period(self, cid, payload, actor, closed):
        competence = period(payload.get("period"))
        module = payload.get("module")
        reason = text(payload.get("reason"), "Motivo do fechamento/reabertura", True, 1000)
        if module not in {"fiscal", "accounting"}:
            raise DomainError("Módulo deve ser fiscal ou accounting.")
        with self.db.transaction() as conn:
            company_row(conn, cid)
            current = self._periods(conn, cid, competence)[module]
            if current["closed"] == closed:
                raise DomainError("A competência já está nesse estado.", 409, "period_state_conflict")
            if closed and module == "fiscal":
                count = conn.execute("SELECT COUNT(*) FROM documents WHERE company_id=? AND period=? AND status<>'booked'", (cid, competence)).fetchone()[0]
                if count:
                    raise DomainError(f"Há {count} documento(s) fiscal(is) sem escrituração concluída nesta competência.", 409, "pending_documents")
            if closed and module == "accounting":
                bad = conn.execute("SELECT j.id FROM journals j LEFT JOIN journal_lines l ON l.journal_id=j.id WHERE j.company_id=? AND j.period=? GROUP BY j.id HAVING COALESCE(SUM(l.debit_cents),0)<>COALESCE(SUM(l.credit_cents),0) OR COALESCE(SUM(l.debit_cents),0)=0 LIMIT 1", (cid, competence)).fetchone()
                if bad:
                    raise DomainError("Existem partidas inconsistentes; fechamento impedido.", 409, "unbalanced_journal")
            conn.execute("INSERT INTO period_locks(company_id,period,module,closed,reason,actor,changed_at,version) VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(company_id,period,module) DO UPDATE SET closed=excluded.closed,reason=excluded.reason,actor=excluded.actor,changed_at=excluded.changed_at,version=period_locks.version+1", (cid, competence, module, closed, reason, actor, now()))
            audit(conn, cid, actor, "close" if closed else "reopen", "period", competence + ":" + module, {"reason": reason, "module": module})
            return self._periods(conn, cid, competence)

    def catalogs(self, cid, kind=None):
        if kind and kind not in {"cfop", "ncm", "revenue", "service"}:
            raise DomainError("Tipo de cadastro fiscal inválido.")
        with self.db.read() as conn:
            company_row(conn, cid)
            clause, params = (" AND kind=?", (cid, kind)) if kind else ("", (cid,))
            return [dict(r) | {"active": bool(r["active"])} for r in conn.execute("SELECT * FROM catalogs WHERE company_id=?" + clause + " ORDER BY kind,code", params)]

    def save_catalog(self, cid, payload, actor, item_id=None):
        with self.db.transaction() as conn:
            company_row(conn, cid)
            old = select_one(conn, "catalogs", cid, item_id) if item_id else {}
            if old:
                check_version(old, payload)
            values = {k: text(payload.get(k, old.get(k, "")), k, k in {"kind", "code", "description"}, 1000) for k in ("kind", "code", "description", "direction", "valid_from", "valid_to", "source")}
            if values["kind"] not in {"cfop", "ncm", "revenue", "service"}:
                raise DomainError("Tipo de cadastro fiscal inválido.")
            values["direction"] = values["direction"] or "both"
            if values["direction"] not in {"incoming", "outgoing", "both"}:
                raise DomainError("Direção deve ser incoming, outgoing ou both.")
            expected = {"cfop": 4, "ncm": 8}.get(values["kind"])
            if expected and not re.fullmatch(rf"\d{{{expected}}}", values["code"]):
                raise DomainError(f"O código deve conter {expected} dígitos. Sua validade legal não é inferida.")
            self._validity(values, required=False)
            values["active"] = boolean(payload.get("active"), bool(old.get("active", True)))
            if old:
                conn.execute(f"UPDATE catalogs SET {','.join(k+'=?' for k in values)},version=version+1 WHERE id=? AND company_id=?", (*values.values(), item_id, cid))
            else:
                item_id = conn.execute(f"INSERT INTO catalogs(company_id,{','.join(values)}) VALUES({','.join('?' for _ in range(len(values)+1))})", (cid, *values.values())).lastrowid
            audit(conn, cid, actor, "update" if old else "create", "catalog", item_id, {"before": old, "after": values})
            return select_one(conn, "catalogs", cid, item_id)

    @staticmethod
    def _validity(values, required=True):
        if required or values.get("valid_from"):
            values["valid_from"] = iso_date(values.get("valid_from"), "Início da vigência")
        if values.get("valid_to"):
            values["valid_to"] = iso_date(values["valid_to"], "Fim da vigência")
            if values.get("valid_from") and values["valid_to"] < values["valid_from"]:
                raise DomainError("Fim da vigência anterior ao início.")

    def rules(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            return [dict(r) | {"active": bool(r["active"]), "rate": format(Decimal(r["rate"]), "f") if r["rate"] is not None else None} for r in conn.execute("SELECT * FROM rules WHERE company_id=? AND superseded_by IS NULL ORDER BY name,id", (cid,))]

    def rule_versions(self, cid, item_id):
        with self.db.read() as conn:
            rule = select_one(conn, "rules", cid, item_id)
            return [dict(r) | {"rate": format(Decimal(r["rate"]), "f") if r["rate"] is not None else None} for r in conn.execute("SELECT * FROM rules WHERE company_id=? AND family_id=? ORDER BY version DESC", (cid, rule["family_id"]))]

    def _save_rule(self, conn, cid, payload, actor, item_id=None):
        company_row(conn, cid)
        old = select_one(conn, "rules", cid, item_id) if item_id else {}
        if old:
            check_version(old, payload)
            if old["superseded_by"]:
                raise DomainError("Esta versão já foi substituída. Edite a versão atual.", 409, "stale_version")
        values = {k: text(payload.get(k, old.get(k, "")), k, k in {"name", "tax"}, 1000) for k in ("name", "tax", "direction", "cfop", "ncm", "valid_from", "valid_to", "source", "responsible", "status")}
        values["status"] = values["status"] or "draft"
        values["direction"] = values["direction"] or "both"
        if values["status"] not in {"draft", "validated"} or values["direction"] not in {"incoming", "outgoing", "both"}:
            raise DomainError("Status ou direção de regra inválido.")
        self._validity(values)
        for code, size in (("cfop", 4), ("ncm", 8)):
            if values[code] and not re.fullmatch(rf"\d{{{size}}}", values[code]):
                raise DomainError(f"{code.upper()} deve conter {size} dígitos.")
        raw_rate = payload.get("rate", old.get("rate"))
        if old and raw_rate is not None and raw_rate == old.get("rate"):
            # Early development data may contain Decimal's scientific notation.
            raw_rate = format(Decimal(raw_rate), "f")
        if raw_rate in (None, ""):
            values["rate"] = None
        else:
            raw_rate = text(raw_rate, "Alíquota declarada", True, 30)
            if not re.fullmatch(r"\d{1,3}(?:\.\d{1,6})?", raw_rate) or Decimal(raw_rate) > 100:
                raise DomainError("Alíquota declarada deve estar entre 0 e 100, com até seis casas decimais.")
            values["rate"] = format(Decimal(raw_rate).normalize(), "f")
        if values["status"] == "validated" and (not values["source"] or not values["responsible"] or values["rate"] is None):
            raise DomainError("Regra marcada como conferida exige fonte, responsável e alíquota declarada. A conferência é do escritório.")
        values.update(company_id=cid, family_id=old.get("family_id", str(uuid.uuid4())), version=old.get("version", 0) + 1, active=boolean(payload.get("active"), bool(old.get("active", True))), created_at=now(), created_by=actor)
        rid = conn.execute(f"INSERT INTO rules({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values())).lastrowid
        if old:
            conn.execute("UPDATE rules SET superseded_by=? WHERE id=? AND company_id=?", (rid, item_id, cid))
        audit(conn, cid, actor, "version" if old else "create", "rule", rid, {"previous_id": item_id, "version": values["version"], "source": values["source"]})
        return select_one(conn, "rules", cid, rid)

    def save_rule(self, cid, payload, actor, item_id=None):
        with self.db.transaction() as conn:
            return self._save_rule(conn, cid, payload, actor, item_id)

    def simulate_rule(self, cid, item_id, payload, actor):
        day = iso_date(payload.get("date"), "Data de referência")
        base = money(payload.get("base"), "Base declarada")
        with self.db.transaction() as conn:
            rule = select_one(conn, "rules", cid, item_id)
            if not rule["active"] or rule["rate"] is None:
                raise DomainError("Selecione uma regra ativa com alíquota declarada.")
            if day < rule["valid_from"] or (rule["valid_to"] and day > rule["valid_to"]):
                raise DomainError("Data fora da vigência desta versão da regra.")
            result = int((Decimal(base) * Decimal(rule["rate"]) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            response = {"simulation": True, "legal_validation": False, "rule_id": item_id, "rule_version": rule["version"], "date": day, "base_cents": base, "rate": rule["rate"], "result_cents": result, "source": rule["source"], "responsible": rule["responsible"], "memory": [f"Base declarada: {decimal_text(base)}", f"Alíquota declarada: {rule['rate']}%", "Fórmula: base × alíquota ÷ 100; arredondamento ao centavo HALF_UP.", f"Prévia: {decimal_text(result)}. Não constitui apuração legal."]}
            calc_id = conn.execute("INSERT INTO calculations(company_id,rule_id,payload_json,created_at,created_by) VALUES(?,?,?,?,?)", (cid, item_id, pack(response), now(), actor)).lastrowid
            response["calculation_id"] = calc_id
            audit(conn, cid, actor, "simulate", "rule", item_id, {"calculation_id": calc_id, "rule_version": rule["version"]})
            return response

    def templates(self):
        with self.db.read() as conn:
            return [dict(r) | {"rules": json.loads(r["rules_json"])} for r in conn.execute("SELECT * FROM templates ORDER BY name")]

    def create_template(self, payload, actor):
        cid = integer(payload.get("source_company_id"), "Empresa de origem")
        name = text(payload.get("name"), "Nome do modelo", True, 200)
        description = text(payload.get("description"), "Descrição", False, 1000)
        ids = payload.get("rule_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or len(set(ids)) != len(ids):
            raise DomainError("Selecione de 1 a 200 regras distintas para o modelo.")
        with self.db.transaction() as conn:
            company_row(conn, cid)
            rules = [select_one(conn, "rules", cid, integer(key, "Regra")) for key in ids]
            if any(x["superseded_by"] or not x["active"] for x in rules):
                raise DomainError("Modelos devem usar versões atuais e ativas.")
            item_id = conn.execute("INSERT INTO templates(name,description,source_company_id,rules_json,created_at,created_by) VALUES(?,?,?,?,?,?)", (name, description, cid, pack(rules), now(), actor)).lastrowid
            audit(conn, cid, actor, "create", "template", item_id, {"rule_ids": ids})
            return {"id": item_id, "name": name, "description": description, "source_company_id": cid, "rules": rules}

    def apply_template(self, cid, item_id, payload, actor):
        reason = text(payload.get("reason"), "Motivo da aplicação", True, 1000)
        with self.db.transaction() as conn:
            company_row(conn, cid)
            template = conn.execute("SELECT * FROM templates WHERE id=?", (item_id,)).fetchone()
            if not template:
                raise DomainError("Modelo não encontrado.", 404, "not_found")
            created = []
            for original in json.loads(template["rules_json"]):
                copied = dict(original)
                if copied.get("rate") is not None:
                    copied["rate"] = format(Decimal(copied["rate"]), "f")
                copied["status"] = "draft"
                copied["responsible"] = ""
                copied["active"] = True
                created.append(self._save_rule(conn, cid, copied, actor))
            audit(conn, cid, actor, "apply", "template", item_id, {"reason": reason, "created_rule_ids": [r["id"] for r in created]})
            return {"template_id": item_id, "rules": created, "status": "draft", "review_required": True}

    def _import_result(self, row):
        result = json.loads(row["parsed_json"])
        result.update(id=row["id"], filename=row["filename"], sha256=row["sha256"], preview_hash=row["preview_hash"], status=row["status"], period=row["period"], bank_account=row["bank_account"], created_at=row["created_at"])
        if row["confirmation_json"]:
            result["confirmation"] = json.loads(row["confirmation_json"])
        return result

    def imports(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            return [{"id": r["id"], "filename": r["filename"], "sha256": r["sha256"], "status": r["status"], "period": r["period"], "created_at": r["created_at"], "documents_count": len(json.loads(r["parsed_json"]).get("documents", [])), "transactions_count": len(json.loads(r["parsed_json"]).get("transactions", []))} for r in conn.execute("SELECT id,filename,sha256,status,period,created_at,parsed_json FROM imports WHERE company_id=? ORDER BY id DESC", (cid,))]

    def import_detail(self, cid, item_id):
        with self.db.read() as conn:
            row = select_one(conn, "imports", cid, item_id)
            return self._import_result(row)

    def preview_import(self, cid, payload, actor):
        from .importers import parse_file
        filename = text(payload.get("filename"), "Arquivo", True, 255)
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise DomainError("Informe somente o nome do arquivo, sem caminhos.")
        competence = period(payload.get("period"))
        encoded = payload.get("content_base64")
        if not isinstance(encoded, str) or len(encoded) > 28_000_000:
            raise DomainError("Arquivo ausente ou maior que 20 MiB.", 413, "file_too_large")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise DomainError("Conteúdo base64 inválido.")
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise DomainError("O arquivo deve conter entre 1 byte e 20 MiB.", 413, "file_too_large")
        options = payload.get("options", {})
        json_value(options, dict, "Opções de importação")
        bank_account = text(payload.get("bank_account"), "Conta bancária", False, 200)
        with self.db.read() as conn:
            company = company_row(conn, cid)
        identity = digest({"sha256": digest(raw), "filename": filename, "period": competence, "options": options, "company_tax_id": company["tax_id"]})
        with self.db.read() as conn:
            existing = conn.execute("SELECT * FROM imports WHERE company_id=? AND identity_hash=?", (cid, identity)).fetchone()
            if existing:
                return self._import_result(existing)
        parsed = parse_file(filename, raw, company | {"import_options": options})
        if not isinstance(parsed, dict):
            raise DomainError("O leitor não retornou uma prévia válida.", 422, "parser_invalid_result")
        for key in ("documents", "transactions", "issues", "sources"):
            if not isinstance(parsed.get(key, []), list):
                raise DomainError("Formato de prévia inválido.", 422, "parser_invalid_result")
            parsed.setdefault(key, [])
        for doc in parsed["documents"]:
            if doc.get("posting_date", "")[:7] != competence:
                parsed["issues"].append({"severity": "error", "code": "POSTING_PERIOD_MISMATCH", "message": f"Documento {doc.get('number', '')}: data de escrituração {doc.get('posting_date', '')} não pertence à competência {competence}. Informe a data de escrituração nas opções ou selecione a competência correta; a emissão será preservada.", "source": doc.get("source", {})})
        status = "blocked" if any(x.get("severity") == "error" for x in parsed["issues"]) else "preview"
        if not parsed["documents"] and not parsed["transactions"] and status != "blocked":
            parsed["issues"].append({"severity": "error", "code": "NO_SUPPORTED_RECORDS", "message": "Nenhum documento ou movimento suportado foi identificado.", "source": {"file": filename}})
            status = "blocked"
        parsed["can_confirm"] = status != "blocked"
        preview_hash = digest({"identity": identity, "parsed": parsed})
        with self.db.transaction() as conn:
            current = company_row(conn, cid)
            if current["tax_id"] != company["tax_id"]:
                raise DomainError("CNPJ alterado durante a leitura. Gere novamente a prévia.", 409, "stale_company")
            existing = conn.execute("SELECT * FROM imports WHERE company_id=? AND identity_hash=?", (cid, identity)).fetchone()
            if existing:
                return self._import_result(existing)
            iid = conn.execute("INSERT INTO imports(company_id,filename,sha256,identity_hash,preview_hash,period,company_tax_id,options_json,original,parsed_json,status,bank_account,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid, filename, digest(raw), identity, preview_hash, competence, company["tax_id"], pack(options), raw, pack(parsed), status, bank_account, now(), actor)).lastrowid
            audit(conn, cid, actor, "preview", "import", iid, {"sha256": digest(raw), "filename": filename, "status": status, "period": competence})
            return self._import_result(select_one(conn, "imports", cid, iid))

    def confirm_import(self, cid, item_id, payload, actor):
        expected_hash = text(payload.get("preview_hash"), "Hash da prévia", True, 100)
        with self.db.transaction() as conn:
            batch = select_one(conn, "imports", cid, item_id)
            company = company_row(conn, cid)
            if not hmac.compare_digest(batch["preview_hash"], expected_hash):
                raise DomainError("A prévia não corresponde ao conteúdo confirmado. Reabra a conferência.", 409, "stale_preview")
            if batch["company_tax_id"] != company["tax_id"]:
                raise DomainError("O CNPJ da empresa foi alterado. Gere uma nova prévia.", 409, "stale_company")
            parsed = json.loads(batch["parsed_json"])
            bank_account = text(payload.get("bank_account", batch["bank_account"]), "Conta bancária", bool(parsed.get("transactions")), 200)
            if batch["status"] == "confirmed":
                previous = json.loads(batch["confirmation_json"])
                if bank_account != batch["bank_account"]:
                    raise DomainError("Importação já confirmada em outra identificação de conta bancária.", 409, "idempotency_conflict")
                return previous | {"duplicate": True}
            if any(issue.get("severity") == "error" for issue in parsed["issues"]) or not parsed.get("can_confirm", True):
                raise DomainError("A prévia possui erros que impedem a confirmação. Corrija a origem ou as opções e importe novamente.", 409, "import_blocked")
            result = {"import_id": item_id, "status": "confirmed", "documents_created": 0, "documents_duplicate": 0, "transactions_created": 0, "transactions_duplicate": 0, "document_ids": [], "transaction_ids": []}
            for source_doc in parsed.get("documents", []):
                if source_doc.get("posting_date", "")[:7] != batch["period"]:
                    raise DomainError("Documento pertence a outra competência; a confirmação foi interrompida.", 409, "period_mismatch")
                doc = self._create_document(conn, cid, source_doc, actor)
                result["documents_duplicate" if doc.get("duplicate") else "documents_created"] += 1
                result["document_ids"].append(doc["id"])
            for source_tx in parsed.get("transactions", []):
                tx = self._create_bank(conn, cid, source_tx, bank_account, actor)
                result["transactions_duplicate" if tx.get("duplicate") else "transactions_created"] += 1
                result["transaction_ids"].append(tx["id"])
            conn.execute("UPDATE imports SET status='confirmed',bank_account=?,confirmation_json=? WHERE id=? AND company_id=?", (bank_account, pack(result), item_id, cid))
            audit(conn, cid, actor, "confirm", "import", item_id, result)
            return result

    def report(self, cid, kind, competence, account_id=None, cost_center_id=None):
        competence = period(competence)
        if kind not in {"diary", "ledger", "trial-balance"}:
            raise DomainError("Relatório não encontrado.", 404, "not_found")
        with self.db.read() as conn:
            company_row(conn, cid)
            clauses, params = ["l.company_id=?"], [cid]
            if account_id is not None:
                select_one(conn, "accounts", cid, integer(account_id, "Conta"))
                clauses.append("l.account_id=?")
                params.append(account_id)
            if cost_center_id is not None:
                select_one(conn, "cost_centers", cid, integer(cost_center_id, "Centro de custo"))
                clauses.append("l.cost_center_id=?")
                params.append(cost_center_id)
            where = " AND ".join(clauses)
            openings = {r["account_id"]: r["opening_cents"] for r in conn.execute("SELECT l.account_id,SUM(l.debit_cents-l.credit_cents) AS opening_cents FROM journal_lines l JOIN journals j ON j.id=l.journal_id WHERE " + where + " AND j.period<? GROUP BY l.account_id", (*params, competence))}
            line_query = "SELECT l.journal_id,j.number,j.date,j.document,j.history,j.reversal_of,j.reversed_by,l.account_id,a.access_code,a.classifier,a.name AS account_name,a.nature,l.debit_cents,l.credit_cents,l.cost_center_id,c.name AS cost_center_name FROM journal_lines l JOIN journals j ON j.id=l.journal_id JOIN accounts a ON a.id=l.account_id LEFT JOIN cost_centers c ON c.id=l.cost_center_id WHERE " + where + " AND j.period=? ORDER BY " + ("a.classifier," if kind == "ledger" else "") + "j.date,j.id,l.position"
            rows = [dict(r) for r in conn.execute(line_query, (*params, competence))]
            totals = {"debit_cents": sum(r["debit_cents"] for r in rows), "credit_cents": sum(r["credit_cents"] for r in rows)}
            if kind == "ledger":
                balances = dict(openings)
                for row in rows:
                    aid = row["account_id"]
                    row["opening_cents"] = openings.get(aid, 0)
                    balances[aid] = balances.get(aid, 0) + row["debit_cents"] - row["credit_cents"]
                    row["balance_cents"] = balances[aid]
                totals["opening_cents"] = sum(openings.values())
                totals["closing_cents"] = totals["opening_cents"] + totals["debit_cents"] - totals["credit_cents"]
            elif kind == "trial-balance":
                movements = {}
                for row in rows:
                    aid = row["account_id"]
                    entry = movements.setdefault(aid, {"debit_cents": 0, "credit_cents": 0})
                    entry["debit_cents"] += row["debit_cents"]
                    entry["credit_cents"] += row["credit_cents"]
                aquery, aparams = (" AND id=?", (cid, account_id)) if account_id else ("", (cid,))
                rows = []
                for account in conn.execute("SELECT * FROM accounts WHERE company_id=? AND analytical=1" + aquery + " ORDER BY classifier", aparams):
                    aid = account["id"]
                    entry = {"account_id": aid, "access_code": account["access_code"], "classifier": account["classifier"], "account_name": account["name"], "nature": account["nature"], "opening_cents": openings.get(aid, 0), **movements.get(aid, {"debit_cents": 0, "credit_cents": 0})}
                    entry["closing_cents"] = entry["opening_cents"] + entry["debit_cents"] - entry["credit_cents"]
                    rows.append(entry)
                totals["opening_cents"] = sum(r["opening_cents"] for r in rows)
                totals["closing_cents"] = sum(r["closing_cents"] for r in rows)
            return {"kind": kind, "company_id": cid, "period": competence, "account_id": account_id, "cost_center_id": cost_center_id, "rows": rows, "totals": totals, "scope_note": "Saldos incluem somente os lançamentos cadastrados. Centro de custo filtra partidas individualmente."}

    def dashboard(self, cid, competence):
        competence = period(competence)
        with self.db.read() as conn:
            company_row(conn, cid)
            docs = {"count": 0, "pending": 0, "reviewed": 0, "booked": 0, "total_cents": 0}
            for row in conn.execute("SELECT status,COUNT(*) AS n,COALESCE(SUM(total_cents),0) AS total FROM documents WHERE company_id=? AND period=? GROUP BY status", (cid, competence)):
                docs[row["status"]] = row["n"]
                docs["count"] += row["n"]
                docs["total_cents"] += row["total"]
            accounting = dict(conn.execute("SELECT COUNT(*) AS journals,COALESCE(SUM(total_cents),0) AS debit_cents,COALESCE(SUM(total_cents),0) AS credit_cents FROM journals WHERE company_id=? AND period=?", (cid, competence)).fetchone())
            financial = {"payable_cents": 0, "receivable_cents": 0, "overdue_cents": 0}
            for row in conn.execute("SELECT kind,SUM(amount_cents-paid_cents) AS balance FROM titles WHERE company_id=? AND cancelled=0 GROUP BY kind", (cid,)):
                financial[row["kind"] + "_cents"] = row["balance"]
            financial["overdue_cents"] = conn.execute("SELECT COALESCE(SUM(amount_cents-paid_cents),0) FROM titles WHERE company_id=? AND cancelled=0 AND due_date<?", (cid, date.today().isoformat())).fetchone()[0]
            bank = dict(conn.execute("SELECT COUNT(*) AS total,COUNT(r.id) AS matched FROM bank_transactions b LEFT JOIN reconciliations r ON r.transaction_id=b.id WHERE b.company_id=? AND substr(b.date,1,7)=?", (cid, competence)).fetchone())
            bank["pending"] = bank["total"] - bank["matched"]
            return {"company_id": cid, "period": competence, "documents": docs, "accounting": accounting, "financial": financial, "reconciliation": bank, "periods": self._periods(conn, cid, competence)}

    def audit(self, cid, limit=100):
        limit = min(max(integer(limit, "Limite"), 1), 1000)
        with self.db.read() as conn:
            company_row(conn, cid)
            return [{k: v for k, v in dict(r).items() if k != "details_json"} | {"details": json.loads(r["details_json"])} for r in conn.execute("SELECT * FROM audit WHERE company_id=? ORDER BY id DESC LIMIT ?", (cid, limit))]

    def seed_demo(self):
        with self.db.transaction() as conn:
            marker = conn.execute("SELECT value FROM meta WHERE key='demo_seeded'").fetchone()
            if marker:
                return
            if conn.execute("SELECT 1 FROM companies LIMIT 1").fetchone():
                raise RuntimeError("Modo de demonstração exige diretório vazio ou banco já identificado como demonstração.")
            for index, name in ((1, "Aurora Comércio (demonstração)"), (2, "Horizonte Serviços (demonstração)")):
                base = f"DEMO000{index}0001"
                values = self._company_values({"code": f"DEMO{index:03}", "name": name, "trade_name": name, "tax_id": base + cnpj_digits(base), "regime": "outros", "state": "SP", "city": "Cidade fictícia", "address": "Rua de demonstração", "number": str(index * 100), "prosoft_code": f"FICTICIO{index}"})
                cid = conn.execute(f"INSERT INTO companies({','.join(COMPANY_FIELDS)},created_at,updated_at) VALUES({','.join('?' for _ in range(len(COMPANY_FIELDS)+2))})", (*values.values(), now(), now())).lastrowid
                self._default_accounts(conn, cid)
                cc = conn.execute("INSERT INTO cost_centers(company_id,code,name) VALUES(?,?,?)", (cid, "ADM", "Administrativo — demonstração")).lastrowid
                accounts = {r["access_code"]: r["id"] for r in conn.execute("SELECT id,access_code FROM accounts WHERE company_id=?", (cid,))}
                if index == 1:
                    for key, debit, credit, amount, history in (("sale", "3", "5", "2500.00", "Venda fictícia para demonstração"), ("expense", "6", "4", "450.00", "Despesa fictícia para demonstração")):
                        self._create_journal(conn, cid, {"date": "2026-11-05", "document": "DEMO-" + key.upper(), "history": history, "idempotency_key": "demo:" + key, "lines": [{"account_id": accounts[debit], "debit": amount, "credit": "0.00", "cost_center_id": cc}, {"account_id": accounts[credit], "debit": "0.00", "credit": amount}]}, "demonstração")
                    for number, direction, amount in (("DEMO-001", "outgoing", "2500.00"), ("DEMO-002", "incoming", "450.00")):
                        self._create_document(conn, cid, {"direction": direction, "number": number, "series": "DEMO", "model": "DEMO", "issue_date": "2026-11-05", "posting_date": "2026-11-05", "partner_name": "Parceiro fictício — demonstração", "total": amount, "taxes": {}, "items": [], "source": {"type": "demo", "notice": "DADOS FICTÍCIOS. NÃO UTILIZAR EM OBRIGAÇÕES FISCAIS."}}, "demonstração")
                    for number, kind, amount, day in ((1, "receivable", "2500.00", "10"), (2, "payable", "450.00", "12"), (3, "receivable", "1280.00", "20"), (4, "payable", "720.00", "25")):
                        self._create_title(conn, cid, {"kind": kind, "description": f"Título fictício {number} — demonstração", "partner_name": "Parceiro fictício", "document": f"DEMO-{number:03}", "issue_date": "2026-11-05", "due_date": "2026-11-" + day, "amount": amount}, "demonstração")
                    for index_tx, day, amount, description in ((1, "10", "2500.00", "Recebimento fictício"), (2, "12", "-450.00", "Pagamento fictício")):
                        self._create_bank(conn, cid, {"date": "2026-11-" + day, "amount": amount, "description": description, "external_id": f"DEMO-{index_tx}", "reference": "DEMONSTRAÇÃO", "source": {"type": "demo"}, "source_hash": "demo"}, "Conta fictícia — demonstração", "demonstração")
                audit(conn, cid, "demonstração", "seed", "company", cid, {"fictional": True, "notice": "Dados sintéticos; sem regras tributárias."})
            conn.execute("INSERT INTO meta(key,value) VALUES('demo_seeded',?)", (now(),))
