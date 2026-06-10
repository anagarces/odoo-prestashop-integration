import requests
import xml.etree.ElementTree as ET
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PrestashopProduct(models.Model):
    _name = 'prestashop.product'
    _description = 'Producto sincronizado con PrestaShop'

    # Relación con el producto de Odoo
    odoo_product_id = fields.Many2one(
        comodel_name='product.template',
        string='Producto Odoo',
        required=True,
        ondelete='cascade'
    )
    # ID del producto en PrestaShop
    prestashop_id = fields.Integer(
        string='ID en PrestaShop',
        readonly=True
    )
    prestashop_reference = fields.Char(
        string='Referencia PrestaShop',
        readonly=True
    )
    config_id = fields.Many2one(
        comodel_name='prestashop.config',
        string='Configuración',
        required=True
    )
    sync_state = fields.Selection(
        selection=[
            ('pending', 'Pendiente'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado sync',
        default='pending'
    )
    last_sync = fields.Datetime(
        string='Última sync',
        readonly=True
    )
    sync_message = fields.Text(
        string='Último mensaje',
        readonly=True
    )

    def _build_product_xml(self, product, lang_id=1):
        """Construye el XML necesario para crear/actualizar un producto en PrestaShop"""
        name        = product.name or ''
        price       = product.list_price or 0.0
        reference   = product.default_code or ''
        description = product.description_sale or name
        slug        = name.lower().replace(' ', '-')

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    <product>
        <active>1</active>
        <price>{price:.6f}</price>
        <reference>{reference}</reference>
        <minimal_quantity>1</minimal_quantity>
        <show_price>1</show_price>
        <available_for_order>1</available_for_order>
        <name>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </name>
        <description>
            <language id="{lang_id}"><![CDATA[{description}]]></language>
        </description>
        <description_short>
            <language id="{lang_id}"><![CDATA[{description[:100]}]]></language>
        </description_short>
        <link_rewrite>
            <language id="{lang_id}"><![CDATA[{slug}]]></language>
        </link_rewrite>
        <meta_title>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </meta_title>
    </product>
</prestashop>"""

    def sync_to_prestashop(self):
        """Sincroniza el producto de Odoo hacia PrestaShop"""
        self.ensure_one()
        config  = self.config_id
        product = self.odoo_product_id
        headers = {"Content-Type": "application/xml"}
        auth    = config._get_auth()
        api_url = config._get_api_url()

        try:
            xml_data = self._build_product_xml(product)

            if self.prestashop_id:
                # Actualizar producto existente (PUT)
                xml_data = xml_data.replace(
                    '<product>',
                    f'<product><id>{self.prestashop_id}</id>'
                )
                url      = f"{api_url}/products/{self.prestashop_id}"
                response = requests.put(
                    url,
                    auth=auth,
                    headers=headers,
                    data=xml_data.encode('utf-8')
                )
                expected_status = 200
            else:
                # Crear nuevo producto (POST)
                url      = f"{api_url}/products"
                response = requests.post(
                    url,
                    auth=auth,
                    headers=headers,
                    data=xml_data.encode('utf-8')
                )
                expected_status = 201

            if response.status_code == expected_status:
                # Extraer ID asignado por PrestaShop
                root       = ET.fromstring(response.text)
                id_element = root.find('.//id')
                if id_element is not None:
                    self.prestashop_id = int(id_element.text.strip())

                self.sync_state   = 'synced'
                self.last_sync    = fields.Datetime.now()
                self.sync_message = f'Sincronizado correctamente. PS ID: {self.prestashop_id}'
                _logger.info(f'Producto {product.name} sincronizado. PS ID: {self.prestashop_id}')
            else:
                self.sync_state   = 'error'
                self.sync_message = f'HTTP {response.status_code}: {response.text[:200]}'
                raise UserError(f'Error sincronizando producto: {response.status_code}')

        except requests.exceptions.ConnectionError as e:
            self.sync_state   = 'error'
            self.sync_message = str(e)
            raise UserError(f'Error de conexión con PrestaShop: {e}')