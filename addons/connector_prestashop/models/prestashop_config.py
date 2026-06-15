import logging
import os

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        default=lambda self: os.environ.get('PRESTASHOP_URL', 'http://host.docker.internal:8080'),
        help=(
            'URL base de la tienda. '
            'Desde Docker Desktop use http://host.docker.internal:8080'
        )
    )
    api_key = fields.Char(
        string='API Key',
        required=True,
        default=lambda self: os.environ.get('PRESTASHOP_API_KEY', ''),
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
    default_tax_rules_group_id = fields.Integer(
        string='Grupo de IVA PrestaShop',
        default=1,
        help=(
            'ID del grupo de reglas de impuesto en PrestaShop. '
            'Consulta: Back-Office → Internacional → Impuestos → Reglas de impuesto. '
            'Valor por defecto: 1 (IVA estándar del país)'
        )
    )
    last_customer_sync = fields.Datetime(
        string='Última sync clientes',
        readonly=True,
    )
    last_products_sync = fields.Datetime(
        string='Última sync productos',
        readonly=True,
    )
    last_sync = fields.Datetime(
        string='Última sync pedidos',
        readonly=True,
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
        """Importa clientes nuevos de PrestaShop hacia Odoo.

        El endpoint /customers de PS no soporta filter[date_upd], por lo que
        se obtiene la lista completa de IDs y se filtra localmente: solo se
        importan aquellos sin binding existente en Odoo.
        """
        self.ensure_one()
        response = self.prestashop_get('customers', params={'sort': '[id_ASC]'})
        root = self.prestashop_parse_xml(response.text)
        all_ps_ids = [
            int(el.get('id'))
            for el in root.findall('.//customer')
            if el.get('id')
        ]

        # IDs ya vinculados — consulta batch (una sola query)
        existing_ps_ids = set(
            self.env['prestashop.customer']
            .search([('config_id', '=', self.id)])
            .mapped('prestashop_id')
        )

        new_ids = [ps_id for ps_id in all_ps_ids if ps_id not in existing_ps_ids]
        skipped = len(all_ps_ids) - len(new_ids)

        created, errors = 0, 0
        for ps_id in new_ids:
            try:
                self.env['prestashop.customer'].import_customer(self, ps_id)
                created += 1
            except Exception as exc:
                _logger.error('Error importando cliente PS %s: %s', ps_id, exc)
                errors += 1

        self.last_customer_sync = fields.Datetime.now()

        parts = []
        if created:
            parts.append(f'{created} nuevo(s)')
        if skipped:
            parts.append(f'{skipped} ya importado(s)')
        if not created and not skipped:
            parts.append('sin cambios')
        msg = ', '.join(parts) + '.'
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

    def action_export_products(self):
        """Exporta productos vendibles (no servicio) de Odoo hacia PrestaShop.

        Crea el binding si no existe (nuevo producto en PS) o actualiza
        si ya fue exportado antes. Los productos de tipo servicio se omiten
        para no exportar los fallbacks generados por la importación de pedidos.
        """
        self.ensure_one()
        products = self.env['product.template'].search([
            ('active', '=', True),
            ('sale_ok', '=', True),
            ('type', 'in', ['product', 'consu']),
        ])

        created, updated, errors = 0, 0, 0
        for product in products:
            binding = self.env['prestashop.product'].search([
                ('config_id', '=', self.id),
                ('odoo_product_id', '=', product.id),
            ], limit=1)
            is_new = not binding
            if not binding:
                binding = self.env['prestashop.product'].create({
                    'config_id': self.id,
                    'odoo_product_id': product.id,
                })
            try:
                binding._sync_single_product()
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                _logger.error('Error exportando producto "%s": %s', product.name, exc)
                errors += 1

        self.last_products_sync = fields.Datetime.now()

        parts = []
        if created:
            parts.append(f'{created} creado(s) en PS')
        if updated:
            parts.append(f'{updated} actualizado(s)')
        if not created and not updated:
            parts.append('sin cambios')
        msg = ', '.join(parts) + '.'
        if errors:
            msg += f' {errors} con error (ver log).'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Exportación de productos',
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

        imported, skipped, errors = 0, 0, 0
        for ps_id in order_ids:
            try:
                result = self.env['prestashop.order'].import_order(self, ps_id)
                if result:
                    imported += 1
                else:
                    skipped += 1
            except Exception as exc:
                _logger.error('Error importando pedido PS %s: %s', ps_id, exc)
                errors += 1

        self.last_sync = fields.Datetime.now()
        parts = []
        if imported:
            parts.append(f'{imported} nuevo(s)')
        if skipped:
            parts.append(f'{skipped} ya existente(s)')
        if not parts:
            parts.append('sin cambios')
        msg = ', '.join(parts) + '.'
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
