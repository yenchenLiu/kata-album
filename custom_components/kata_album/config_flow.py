"""Config flow: paste exported private JSON; reauth with a fresh export."""
from __future__ import annotations

import json

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import KataAuth
from .cloud import KataCloud
from .const import CONF_ACCOUNT, CONF_DEVICE_ID, CONF_LOCAL, CONF_NOTIFY, DOMAIN
from .errors import AuthRejected, KataError

_REQUIRED = ("refresh_token", "client_id", "client_secret", "terminal_device_id", "user_id")
SCHEMA = vol.Schema({vol.Required("export"): str})


def parse_export(text: str) -> dict:
    """Return entry data. Raises ValueError with a safe message."""
    try:
        doc = json.loads(text)
        schema = int(doc.get("schema_version", 1))
        account = doc["account"]
        device_id = doc["device"]["device_id"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("invalid_format") from None
    if schema not in (1, 2) or any(not account.get(k) for k in _REQUIRED) or not device_id:
        raise ValueError("invalid_format")
    notify = (doc.get("initialization") or {}).get("notify")
    if notify is not None and not (isinstance(notify, dict) and notify.get("url")):
        notify = None
    data = {CONF_ACCOUNT: {k: account[k] for k in _REQUIRED},
            CONF_DEVICE_ID: str(device_id), CONF_NOTIFY: notify}
    return data


class KataAlbumConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, data: dict) -> str | None:
        session = async_get_clientsession(self.hass)
        auth = KataAuth(session, data[CONF_ACCOUNT])
        cloud = KataCloud(session, auth, data[CONF_DEVICE_ID], data[CONF_NOTIFY])
        try:
            await auth.ensure_access_token()
            data[CONF_LOCAL] = await cloud.get_local_info()
        except AuthRejected:
            return "auth_failed"
        except KataError:
            return "cannot_connect"
        data[CONF_ACCOUNT] = auth.account  # may carry a rotated refresh token
        return None

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input:
            try:
                data = parse_export(user_input["export"])
            except ValueError:
                errors["base"] = "invalid_format"
            else:
                await self.async_set_unique_id(data[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                err = await self._validate(data)
                if err:
                    errors["base"] = err
                else:
                    return self.async_create_entry(title="Kata Album", data=data)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input:
            try:
                data = parse_export(user_input["export"])
            except ValueError:
                errors["base"] = "invalid_format"
            else:
                if data[CONF_DEVICE_ID] != entry.data[CONF_DEVICE_ID]:
                    errors["base"] = "wrong_device"
                else:
                    data[CONF_NOTIFY] = data[CONF_NOTIFY] or entry.data.get(CONF_NOTIFY)
                    err = await self._validate(data)
                    if err:
                        errors["base"] = err
                    else:
                        return self.async_update_reload_and_abort(entry, data={**entry.data, **data})
        return self.async_show_form(step_id="reauth_confirm", data_schema=SCHEMA, errors=errors)
