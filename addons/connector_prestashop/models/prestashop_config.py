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

    def action_import_products(self):
        """Importa productos nuevos de PrestaShop hacia Odoo.

        Obtiene todos los IDs de PS, descarta los que ya tienen binding,
        e importa los nuevos creando product.template y prestashop.product.
        Los productos ya vinculados se omiten (operación idempotente).
        """
        self.ensure_one()
        response = self.prestashop_get('products', params={'sort': '[id_ASC]'})
        root = self.prestashop_parse_xml(response.text)
        all_ps_ids = [
            int(el.get('id'))
            for el in root.findall('.//product')
            if el.get('id')
        ]

        existing_ps_ids = set(
            self.env['prestashop.product']
            .search([('config_id', '=', self.id)])
            .mapped('prestashop_id')
        )

        new_ids = [ps_id for ps_id in all_ps_ids if ps_id not in existing_ps_ids]
        skipped = len(all_ps_ids) - len(new_ids)

        created, errors = 0, 0
        for ps_id in new_ids:
            try:
                result = self.env['prestashop.product'].import_product(self, ps_id)
                if result:
                    created += 1
            except Exception as exc:
                _logger.error('Error importando producto PS %s: %s', ps_id, exc)
                errors += 1

        self.last_products_sync = fields.Datetime.now()

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
                'title': 'Importación de productos',
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': False,
            },
        }

    def action_import_categories(self):
        """Importa categorías de PrestaShop hacia Odoo creando bindings y product.category.

        Estrategia de mapeo:
        - PS ID=1 (Raíz): omitida — categoría técnica interna de PS.
        - PS ID=2 (Inicio): vinculada a 'All / Saleable' de Odoo sin crear nueva categoría.
        - Resto: se crean como product.category bajo el padre correspondiente.
        Las categorías se procesan de mayor a menor nivel (padres antes que hijos),
        garantizando que el padre exista en Odoo antes de crear el hijo.
        """
        self.ensure_one()
        response = self.prestashop_get('categories', params={
            'display': 'full',
            'sort': '[level_depth_ASC]',
        })
        root = self.prestashop_parse_xml(response.text)
        cats_root = root.find('categories')
        if cats_root is None:
            raise UserError('Respuesta inesperada del API de categorías de PrestaShop.')

        # PS "Inicio" (ID=2) se ancla a "All / Saleable" — raíz de productos vendibles
        saleable = (
            self.env['product.category'].search(
                [('complete_name', '=', 'All / Saleable')], limit=1
            )
            or self.env.ref('product.product_category_all')
        )

        created, updated, skipped, errors = 0, 0, 0, 0

        for cat_el in cats_root.findall('category'):
            ps_id_text = (cat_el.findtext('id') or '').strip()
            if not ps_id_text.isdigit():
                continue
            ps_id = int(ps_id_text)

            if ps_id == 1:  # raíz técnica de PS, sin equivalente en Odoo
                continue

            if cat_el.findtext('active') == '0':
                skipped += 1
                continue

            name_el = cat_el.find('.//name/language')
            name = (name_el.text or '').strip() if name_el is not None else ''
            if not name:
                skipped += 1
                continue

            ps_parent_text = (cat_el.findtext('id_parent') or '').strip()
            ps_parent_id = int(ps_parent_text) if ps_parent_text.isdigit() else None

            binding = self.env['prestashop.category'].search([
                ('config_id', '=', self.id),
                ('prestashop_id', '=', ps_id),
            ], limit=1)

            if ps_id == 2:
                # "Inicio" = raíz visible de la tienda → anclar a "All / Saleable"
                if not binding:
                    self.env['prestashop.category'].create({
                        'config_id': self.id,
                        'odoo_category_id': saleable.id,
                        'prestashop_id': ps_id,
                        'sync_state': 'synced',
                        'last_sync': fields.Datetime.now(),
                        'sync_message': f'Vinculado a "{saleable.complete_name}"',
                    })
                    created += 1
                else:
                    skipped += 1
                continue

            # Resolver padre Odoo a través del binding del padre PS
            # (funciona porque los padres se procesan primero por level_depth_ASC)
            odoo_parent = saleable
            if ps_parent_id and ps_parent_id not in (0, 1):
                parent_binding = self.env['prestashop.category'].search([
                    ('config_id', '=', self.id),
                    ('prestashop_id', '=', ps_parent_id),
                ], limit=1)
                if parent_binding:
                    odoo_parent = parent_binding.odoo_category_id

            if binding:
                if binding.odoo_category_id.name != name:
                    binding.odoo_category_id.name = name
                    binding.write({
                        'sync_state': 'synced',
                        'last_sync': fields.Datetime.now(),
                        'sync_message': f'Nombre actualizado desde PS: {name}',
                    })
                    updated += 1
                else:
                    skipped += 1
            else:
                try:
                    odoo_cat = self.env['product.category'].create({
                        'name': name,
                        'parent_id': odoo_parent.id,
                    })
                    self.env['prestashop.category'].create({
                        'config_id': self.id,
                        'odoo_category_id': odoo_cat.id,
                        'prestashop_id': ps_id,
                        'sync_state': 'synced',
                        'last_sync': fields.Datetime.now(),
                        'sync_message': f'Importado desde PS. ID PS: {ps_id}',
                    })
                    created += 1
                    _logger.info('Categoría PS %s "%s" → Odoo ID %s', ps_id, name, odoo_cat.id)
                except Exception as exc:
                    _logger.error('Error importando categoría PS %s "%s": %s', ps_id, name, exc)
                    errors += 1

        parts = []
        if created:
            parts.append(f'{created} importada(s)')
        if updated:
            parts.append(f'{updated} actualizada(s)')
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
                'title': 'Importación de categorías',
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
