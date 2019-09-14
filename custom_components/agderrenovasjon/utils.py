import logging
import re

from difflib import SequenceMatcher
from collections import defaultdict

from datetime import datetime, date, timedelta

import voluptuous as vol
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import nor_days, nor_months


_LOGGER = logging.getLogger(__name__)


def check_settings(config, hass):
    if not any(config.get(i) for i in ["street_id", "kommune"]):
        _LOGGER.debug("street_id or kommune was not set config")
    else:
        return True
    if not config.get("address"):
        _LOGGER.debug("address was not set")
    else:
        return True

    if not hass.config.latitude or not hass.config.longitude:
        _LOGGER.debug("latitude and longitude is not set in ha settings.")
    else:
        return True

    raise vol.Invalid("Missing settings to setup the sensor.")


def find_next_garbage_pickup(dates):
    if dates is None:
        return

    today = datetime.now().date()
    for i in sorted(dates):
        if i.date() >= today:
            return i

def to_dt(i):
    # 2019-09-13
    return datetime.strptime(i, "%Y-%m-%d")


def parse_tomme_kalender(text=None):
    if text is None:
        # err
        return {}
    tomme_days = defaultdict(list)
    tomme_day = text["adresse"]["meta"]["tommedag"]
    tomme_days["tomme_day"] = tomme_day

    for i in text["hentedager"]["Rest"]:
        tomme_days["mixed"].append(to_dt(i.get('hentedag')))
        tomme_days["bio"].append(to_dt(i.get('hentedag')))

    for i in text["hentedager"]["Glass/Metall"]:
        tomme_days["metal"].append(to_dt(i.get('hentedag')))

    for i in text["hentedager"]["Papir"]:
        tomme_days["paper"].append(to_dt(i.get('hentedag')))

    for i in text["hentedager"]["Plast"]:
        tomme_days["plastic"].append(to_dt(i.get('hentedag')))

    _LOGGER.info("bio %r", tomme_days.get("bio"))
    _LOGGER.info("rest %r", tomme_days.get("mixed"))

    return tomme_days


async def verify_that_we_can_find_adr(config, hass):
    client = async_get_clientsession(hass)
    try:
        adr = await find_address(config.get("address"))
        if adr:
            return True
    except:
        pass

    try:
        adr = await find_address_from_lat_lon(hass.config.latitude, hass.config.longitude, client)
        if adr:
            return True
    except:
        pass

    try:
        # This just to check the lat and lon, the other
        # stuff is tested above.
        check_settings(config, hass)
    except vol.Invalid:
        return False

    return False


async def find_address(address):

    from algoliasearch.search_client import SearchClient

    async with SearchClient.create('4SEG6H6DJJ', '1505bdc72bef6863f8ad3811374f77b8') as client:
        index = client.init_index('renovasjonskalender')
        results = await index.search_async(address)

        if len(results.get("hits", [])):
            # the id is the info we need.
            # the first one seems to be the most correct one.
            res = results["hits"][0]
            _LOGGER.debug('Got %s %s', res["name"], res["kommune"])
            return res["id"]


async def find_address_from_lat_lon(lat, lon, client):
    if lat is None or lon is None:
        return

    url = f"https://ws.geonorge.no/adresser/v1/punktsok?lon={lon}&lat={lat}&radius=20"
    resp = await client.get(url)
    if resp.status == 200:
        result = await resp.json()
        res = result.get("adresser", [])
        if res:
            # The first one seems to be the most correct.
            res = res[0]
            _LOGGER.debug('Got adresse %s from lat %s lon %s', res.get("adressetekst"), lat, lon)
            return "%s, %s" % (res["adressetekst"], res["kommunenavn"])
    elif resp.status == 400:
        result = await resp.json()
        _LOGGER.info("Api returned 400, error %r", result.get("message", ""))
        raise ValueError('lat and lon is not in Norway.')
