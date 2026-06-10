import requests
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PrestashopConfig(models.Model):
    _name = 'prestashop.config'
    _description = 'Configuración de conexión a PrestaShop'

    name = fields.Char(
        string='Nombre',
        required=True,
        default='StyleSync PrestaShop'
    )
    url = fields.Char(
        string='URL de PrestaShop',
        required=True,
        help='URL base de tu tienda. Ejemplo: http://localhost:8080'
    )
    api_key = fields.Char(
        string='API Key',
        required=True,
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
    last_sync = fields.Datetime(
        string='Última sincronización',
        readonly=True
    )

    def _get_api_url(self):
        """Construye la URL base de la API"""
        return f"{self.url.rstrip('/')}/api"

    def _get_auth(self):
        """Retorna la tupla de autenticación para requests"""
        return (self.api_key, "")

    def test_connection(self):
        """Prueba la conexión con PrestaShop"""
        self.ensure_one()
        try:
            url      = self._get_api_url()
            response = requests.get(
                url,
                auth=self._get_auth(),
                timeout=10
            )
            if response.status_code == 200:
                self.state = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '¡Conexión exitosa!',
                        'message': f'Conectado correctamente a {self.url}',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.state = 'error'
                raise UserError(
                    f'Error de conexión: HTTP {response.status_code}'
                )
        except requests.exceptions.ConnectionError:
            self.state = 'error'
            raise UserError(
                f'No se puede conectar a {self.url}. '
                f'Verifica que PrestaShop esté corriendo.'
            )
        except requests.exceptions.Timeout:
            self.state = 'error'
            raise UserError('Timeout — PrestaShop no responde.')