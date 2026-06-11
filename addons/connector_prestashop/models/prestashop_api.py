import logging
import unicodedata
import xml.etree.ElementTree as ET

import requests
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PrestashopApiMixin(models.AbstractModel):
    _name = 'prestashop.api.mixin'
    _description = 'Cliente HTTP para la API Webservice de PrestaShop'

    def _prestashop_api_url(self):
        self.ensure_one()
        return f"{self.url.rstrip('/')}/api"

    def _prestashop_auth(self):
        self.ensure_one()
        return (self.api_key, '')

    def _prestashop_request(self, method, endpoint, data=None, params=None, expected_status=None):
        """Ejecuta una petición contra la API y valida el código HTTP."""
        self.ensure_one()
        url = f"{self._prestashop_api_url()}/{endpoint.lstrip('/')}"
        headers = {'Content-Type': 'application/xml'} if data else {}
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self._prestashop_auth(),
                headers=headers,
                data=data.encode('utf-8') if data else None,
                params=params,
                timeout=30,
            )
        except requests.exceptions.ConnectionError as exc:
            raise UserError(
                f'No se puede conectar a {self.url}. '
                f'Verifica que PrestaShop esté corriendo.'
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise UserError('Timeout — PrestaShop no responde.') from exc

        if expected_status and response.status_code not in (
            expected_status if isinstance(expected_status, (list, tuple)) else [expected_status]
        ):
            raise UserError(
                f'Error API PrestaShop ({method} {endpoint}): '
                f'HTTP {response.status_code}\n{response.text[:500]}'
            )
        return response

    def prestashop_get(self, endpoint, params=None):
        return self._prestashop_request('GET', endpoint, params=params, expected_status=200)

    def prestashop_post(self, endpoint, xml_data):
        return self._prestashop_request('POST', endpoint, data=xml_data, expected_status=201)

    def prestashop_put(self, endpoint, xml_data):
        return self._prestashop_request('PUT', endpoint, data=xml_data, expected_status=200)

    def prestashop_parse_xml(self, xml_text):
        return ET.fromstring(xml_text)

    def prestashop_extract_id(self, xml_text):
        root = self.prestashop_parse_xml(xml_text)
        id_element = root.find('.//id')
        if id_element is not None and id_element.text:
            return int(id_element.text.strip())
        return None

    def prestashop_get_default_language_id(self):
        """Obtiene el ID del primer idioma disponible en la tienda."""
        self.ensure_one()
        response = self.prestashop_get('languages')
        root = self.prestashop_parse_xml(response.text)
        language = root.find('.//language')
        if language is not None and language.get('id'):
            return int(language.get('id'))
        return 1

    @staticmethod
    def prestashop_slugify(text):
        normalized = unicodedata.normalize('NFKD', text or 'producto')
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        slug = ascii_text.lower().strip()
        slug = ''.join(c if c.isalnum() or c in '-_' else '-' for c in slug)
        while '--' in slug:
            slug = slug.replace('--', '-')
        return slug.strip('-') or 'producto'
