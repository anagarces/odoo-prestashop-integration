import logging
import os

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _default_prestashop_url():
    return os.environ.get('PRESTASHOP_URL', 'http://prestashop')


def _default_prestashop_api_key():
    return os.environ.get('PRESTASHOP_API_KEY', '')


class PrestashopConfig(models.Model):
    _name = 'prestashop.config'
    _inherit = ['prestashop.api.mixin']
    _description = 'Configuración de conexión a PrestaShop'

    name = fields.Char(
        string='Nombre',
        required=True,
        default='StyleSync PrestaShop'
    )
    url = fields.Char(
        string='URL de PrestaShop',
        required=True,
        default=_default_prestashop_url,
        help=(
            'URL base de la tienda. '
            'Desde Docker use http://prestashop. '
            'Desde el host use http://localhost:8080'
        )
    )
    api_key = fields.Char(
        string='API Key',
        required=True,
        default=_default_prestashop_api_key,
        help='Clave generada en PrestaShop → Parámetros Avanzados → Webservice'
    )
    active = fields.Boolean(
        string='Activo',
        default=True
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Sin verificar'),
            ('connected', 'Conectado'),
            ('error', 'Error'),
        ],
        string='Estado',
        default='draft',
        readonly=True
    )
    default_lang_id = fields.Integer(
        string='ID idioma PrestaShop',
        readonly=True,
        help='Detectado automáticamente al probar la conexión'
    )
    default_category_ps_id = fields.Integer(
        string='Categoría PS por defecto',
        default=2,
        help='ID de categoría en PrestaShop cuando el producto no tiene mapeo (2 = Inicio)'
    )
    last_sync = fields.Datetime(
        string='Última sincronización',
        readonly=True
    )

    @api.model
    def get_active_config(self):
        """Devuelve la configuración activa y conectada."""
        config = self.search([
            ('active', '=', True),
            ('state', '=', 'connected'),
        ], limit=1)
        if not config:
            raise UserError(
                'No hay ninguna configuración PrestaShop activa y conectada. '
                'Configure la conexión y pulse "Probar Conexión".'
            )
        return config

    def action_import_customers(self):
        """Importa todos los clientes de PrestaShop hacia Odoo."""
        self.ensure_one()
        response = self.prestashop_get('customers')
        root = self.prestashop_parse_xml(response.text)
        customer_ids = [
            int(el.get('id'))
            for el in root.findall('.//customer')
            if el.get('id')
        ]

        imported, errors = 0, 0
        for ps_id in customer_ids:
            try:
                self.env['prestashop.customer'].import_customer(self, ps_id)
                imported += 1
            except Exception as exc:
                _logger.error('Error importando cliente PS %s: %s', ps_id, exc)
                errors += 1

        msg = f'{imported} cliente(s) importado(s).'
        if errors:
            msg += f' {errors} con error (ver log).'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Importación de clientes',
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': False,
            },
        }

    def action_import_orders(self):
        """Importa pedidos de PrestaShop hacia Odoo desde la última sincronización."""
        self.ensure_one()
        params = {'sort': '[id_ASC]'}
        if self.last_sync:
            date_str = self.last_sync.strftime('%Y-%m-%d %H:%M:%S')
            params['filter[date_upd]'] = f'[{date_str},]'

        response = self.prestashop_get('orders', params=params)
        root = self.prestashop_parse_xml(response.text)
        order_ids = [
            int(el.get('id'))
            for el in root.findall('.//order')
            if el.get('id')
        ]

        imported, errors = 0, 0
        for ps_id in order_ids:
            try:
                self.env['prestashop.order'].import_order(self, ps_id)
                imported += 1
            except Exception as exc:
                _logger.error('Error importando pedido PS %s: %s', ps_id, exc)
                errors += 1

        self.last_sync = fields.Datetime.now()
        msg = f'{imported} pedido(s) importado(s).'
        if errors:
            msg += f' {errors} con error (ver log).'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Importación de pedidos',
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': False,
            },
        }

    def test_connection(self):
        """Prueba la conexión con PrestaShop y detecta el idioma por defecto."""
        self.ensure_one()
        try:
            response = self.prestashop_get('')
            if response.status_code == 200:
                lang_id = self.prestashop_get_default_language_id()
                self.write({
                    'state': 'connected',
                    'default_lang_id': lang_id,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '¡Conexión exitosa!',
                        'message': (
                            f'Conectado a {self.url}. '
                            f'Idioma detectado: ID {lang_id}'
                        ),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            self.state = 'error'
            raise UserError(f'Error de conexión: HTTP {response.status_code}')
        except UserError:
            self.state = 'error'
            raise
