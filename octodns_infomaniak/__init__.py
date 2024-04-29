from requests import Session
import logging
from collections import defaultdict

from octodns import __VERSION__ as octodns_version
from octodns.provider import ProviderException
from octodns.provider.base import BaseProvider
from octodns.record import Record

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = "0.0.1"


class InfomaniakClientException(ProviderException):
    pass


class InfomaniakClientBadRequest(InfomaniakClientException):
    def __init__(self):
        super().__init__("Bad request")


class InfomaniakClientUnauthorized(InfomaniakClientException):
    def __init__(self):
        super().__init__("Unauthorized")


class InfomaniakClient(object):
    BASE = "https://api.infomaniak.com"

    def __init__(self, token):
        sess = Session()
        sess.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": f"octodns/{octodns_version} octodns-infomaniak/{__VERSION__}",
            }
        )
        self._sess = sess

    def _request(self, method, path, params=None, data=None):
        url = f"{self.BASE}{path}"
        res = self._sess.request(method, url, params=params, json=data)
        if res.status_code == 400:
            raise InfomaniakClientBadRequest()
        elif res.status_code == 401:
            raise InfomaniakClientUnauthorized()
        res.raise_for_status()
        return res.json()

    def records(self, domain_name):
        domain_name = domain_name.rstrip(".")
        path = f"/1/domain/{domain_name}/dns/record"
        return self._request("GET", path)["data"]

    def record_create(self, domain_name, params):
        path = f"/1/domain/{domain_name}/dns/record"
        self._request("POST", path, data=params)

    def record_delete(self, domain_name, record_id):
        path = f"/1/domain/{domain_name}/dns/record/{record_id}"
        self._request("DELETE", path)


class InfomaniakProvider(BaseProvider):
    SUPPORTS_GEO = False
    SUPPORTS_DYNAMIC = False
    SUPPORTS = set(("A", "AAAA", "CNAME"))

    def __init__(self, id, token, *args, **kwargs):
        self.log = logging.getLogger(f"InfomaniakProvider[{id}]")
        self.log.debug(f"__init__: id={id}")
        self._client = InfomaniakClient(token)
        super().__init__(id, *args, **kwargs)

        self._zone_records = {}

    def populate(self, zone, target=False, lenient=False):
        self.log.debug(
            "populate: name=%s, target=%s, lenient=%s",
            zone.name,
            target,
            lenient,
        )

        values = defaultdict(lambda: defaultdict(list))

        for record in self.zone_records(zone):
            _type = record["type"]
            _name = record["source"]

            if _type not in self.SUPPORTS:
                self.log.warning(
                    f"populate: skipping unsupported {_type} {_name}.{zone} record"
                )
                continue
            values[_name][_type].append(record)

        before = len(zone.records)
        for name, types in values.items():
            for _type, records in types.items():
                data_for = getattr(self, f"_data_for_{_type}")

                if name == ".":
                    name = ""

                record = Record.new(
                    zone,
                    name,
                    data_for(_type, records),
                    source=self,
                    lenient=lenient,
                )
                zone.add_record(record, lenient=lenient)

        exists = zone.name in self._zone_records
        self.log.info(
            "populate:   found %s records, exists=%s",
            len(self._client.records(zone.name)) - before,
            exists,
        )

        return exists

    def zone_records(self, zone):
        if zone.name not in self._zone_records:
            try:
                self._zone_records[zone.name] = self._client.records(zone.name[:-1])
            except InfomaniakClientException:
                return []

        return self._zone_records[zone.name]

    def _data_for_generic(self, _type, records):
        return {"ttl": records[0]["ttl"], "type": _type, "value": records[0]["target"]}

    _data_for_A = _data_for_generic
    _data_for_AAAA = _data_for_generic
    _data_for_CNAME = _data_for_generic

    def _params_for_generic(self, record):
        yield {
            "target": record.value,
            "source": record.name,
            "ttl": record.ttl,
            "type": record._type,
        }

    def _params_for_multiple(self, record):
        for value in record.values:
            yield {
                "target": value,
                "source": record.name,
                "ttl": record.ttl,
                "type": record._type,
            }

    _params_for_A = _params_for_multiple
    _params_for_AAAA = _params_for_multiple
    _params_for_CNAME = _params_for_generic

    def _apply_create(self, changes):
        new = changes.new
        params_for = getattr(self, f"_params_for_{new._type}")
        for params in params_for(new):
            self._client.record_create(new.zone.name[:-1], params)

    def _apply_delete(self, changes):
        existing = changes.existing
        zone = existing.zone

        if existing.name == "":
            existing.name = "."

        for record in self.zone_records(zone):
            if existing.name == record["source"] and existing._type == record["type"]:
                self._client.record_delete(zone.name[:-1], record["id"])

    def _apply_update(self, changes):
        self._apply_delete(changes)
        self._apply_create(changes)

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        self.log.debug("_apply: zone=%s, len(changes)=%d", desired.name, len(changes))

        for change in changes:
            class_name = change.__class__.__name__.lower()
            getattr(self, f"_apply_{class_name}")(change)

        # Clear out the cache if any
        self._zone_records.pop(desired.name, None)
