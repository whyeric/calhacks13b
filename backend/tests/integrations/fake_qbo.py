"""An in-memory QuickBooks Online company behind an httpx.MockTransport (no network).

Speaks the parts of Intuit's API the desk uses: the OAuth token and revoke endpoints, `query`
(`SELECT * FROM X [WHERE F = 'v'] [STARTPOSITION n MAXRESULTS m]`), creates (`POST /<entity>`) and
`/batch`. Like QBO it assigns Ids, computes `TotalAmt` from the lines and `Balance` for invoices
and bills, lowers that balance on Payment/BillPayment, and rejects an unbalanced JournalEntry.
Knobs: `throttle` (429s to return before serving), `fail_create` (entity -> HTTP status),
`expired` (access tokens answered with 401), `refuse_refresh`.
"""

from __future__ import annotations

import base64
import json
import re
from decimal import Decimal
from urllib.parse import parse_qs

import httpx

from app.integrations import quickbooks as qbo

REALM = "9130350000000001"
QUERY = re.compile(r"SELECT \* FROM (\w+)(?: WHERE (\w+(?:\.\w+)?) = '((?:[^'\\]|\\.)*)')?"
                   r"(?: STARTPOSITION (\d+) MAXRESULTS (\d+))?$")
CENT = Decimal("0.01")


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


class FakeQbo:
    def __init__(self, realm: str = REALM, host: str = "sandbox-quickbooks.api.intuit.com"):
        self.realm, self.host = realm, host
        self.tables: dict[str, list[dict]] = {"CompanyInfo": [{"Id": "1", "CompanyName": "Sandbox Company_US_1"}]}
        self.next_id = 100
        self.throttle = 0  # answer this many requests with 429 first
        self.fail_create: dict[str, int] = {}
        self.expired: set[str] = set()
        self.refuse_refresh = False
        self.issued = 0
        self.token_calls: list[dict] = []
        self.revoked: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.batch_sizes: list[int] = []
        self.transport = httpx.MockTransport(self.handle)

    # -- OAuth --

    def _tokens(self) -> httpx.Response:
        self.issued += 1
        return httpx.Response(200, json={"access_token": f"a{self.issued}", "refresh_token": f"r{self.issued}",
                                         "expires_in": 3600, "x_refresh_token_expires_in": 8726400,
                                         "token_type": "bearer"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == qbo.TOKEN_URL:
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_calls.append(form)
            if form["grant_type"] == "refresh_token" and self.refuse_refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return self._tokens()
        if url == qbo.REVOKE_URL:
            assert request.headers["Authorization"].startswith("Basic ")
            self.revoked.append(json.loads(request.content))
            return httpx.Response(200)
        assert request.url.host == self.host, request.url
        prefix = f"/v3/company/{self.realm}/"
        assert request.url.path.startswith(prefix), request.url.path
        assert request.url.params["minorversion"] == qbo.MINOR_VERSION
        if request.headers["Authorization"].removeprefix("Bearer ") in self.expired:
            return httpx.Response(401, json={"fault": {"error": [{"message": "AuthenticationFailed"}]}})
        if self.throttle > 0:
            self.throttle -= 1
            return httpx.Response(429, json={"fault": {"error": [{"message": "ThrottleExceeded"}]}})
        path = request.url.path.removeprefix(prefix)
        if path == "query":
            return self._json({"QueryResponse": self.query(request.url.params["query"]), "time": "t"})
        body = json.loads(request.content, parse_float=Decimal)
        if path == "batch":
            items = body["BatchItemRequest"]
            self.batch_sizes.append(len(items))
            if len(items) > 30:
                return httpx.Response(400, json={"Fault": {"Error": [{"Message": "too many batch items"}]}})
            return self._json({"BatchItemResponse": [self._batch_item(it) for it in items], "time": "t"})
        entity = next(e for e in self._entities() if e.lower() == path)
        status = self.fail_create.get(entity)
        if status:
            return httpx.Response(status, json={"Fault": {"Error": [{"Message": "Service unavailable",
                                                                      "Detail": "try later"}]}})
        try:
            return self._json({entity: self.create(entity, body), "time": "t"})
        except ValueError as e:
            return httpx.Response(400, json={"Fault": {"Error": [{"Message": str(e)}], "type": "ValidationFault"}})

    @staticmethod
    def _entities() -> tuple[str, ...]:
        return ("Account", "Customer", "Vendor", "Item", "SalesReceipt", "Invoice", "PurchaseOrder", "Bill",
                "Estimate", "Payment", "BillPayment", "JournalEntry")

    @staticmethod
    def _json(obj) -> httpx.Response:
        return httpx.Response(200, text=qbo.dumps(obj))

    def _batch_item(self, item: dict) -> dict:
        entity = next(e for e in self._entities() if e in item)
        try:
            return {"bId": item["bId"], entity: self.create(entity, item[entity])}
        except ValueError as e:
            return {"bId": item["bId"], "Fault": {"Error": [{"Message": str(e)}], "type": "ValidationFault"}}

    # -- data --

    def query(self, sql: str) -> dict:
        m = QUERY.match(sql)
        assert m, sql
        entity, fld, value, start, size = m.groups()
        rows = self.tables.get(entity, [])
        if fld:
            value = value.replace("\\'", "'").replace("\\\\", "\\")
            rows = [r for r in rows if str(r.get(fld)) == value]
        start, size = int(start or 1), int(size or 100)
        page = rows[start - 1:start - 1 + size]
        return {entity: page, "startPosition": start, "maxResults": len(page)} if page else {}

    def create(self, entity: str, obj: dict) -> dict:
        obj = json.loads(qbo.dumps(obj), parse_float=Decimal)
        self.next_id += 1
        obj = {**obj, "Id": str(self.next_id), "SyncToken": "0"}
        lines = [ln for ln in obj.get("Line") or [] if ln.get("DetailType") != "SubTotalLineDetail"]
        if entity in ("SalesReceipt", "Invoice", "PurchaseOrder", "Bill", "Estimate"):
            total = sum((_dec(ln["Amount"]) for ln in lines), Decimal("0")).quantize(CENT)
            obj["TotalAmt"] = total
            if entity == "SalesReceipt":
                obj["Balance"] = Decimal("0.00")
            if entity in ("Invoice", "Bill"):
                obj["Balance"] = total
        if entity in ("Customer", "Vendor") and any(r["DisplayName"] == obj["DisplayName"]
                                                    for r in self.tables.get(entity, [])):
            raise ValueError("Duplicate Name Exists Error")
        if entity in ("Payment", "BillPayment"):
            for ln in lines:
                for link in ln["LinkedTxn"]:
                    doc = next(r for r in self.tables[link["TxnType"]] if r["Id"] == link["TxnId"])
                    doc["Balance"] = (_dec(doc["Balance"]) - _dec(ln["Amount"])).quantize(CENT)
        if entity == "JournalEntry":
            side = {"Debit": Decimal("0"), "Credit": Decimal("0")}
            for ln in lines:
                side[ln["JournalEntryLineDetail"]["PostingType"]] += _dec(ln["Amount"])
                acct = ln["JournalEntryLineDetail"]["AccountRef"]["value"]
                assert any(a["Id"] == acct for a in self.tables.get("Account", [])), f"no account {acct}"
            if side["Debit"] != side["Credit"]:
                raise ValueError("Transaction must balance")
            obj["TotalAmt"] = side["Debit"]
        self.tables.setdefault(entity, []).append(obj)
        return obj

    def creates(self, entity: str) -> list[dict]:
        return self.tables.get(entity, [])
