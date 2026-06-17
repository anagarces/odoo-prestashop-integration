import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Estados de PS que equivalen a pedido confirmado en Odoo
_PS_CONFIRMED_STATES = frozenset({2, 3, 4, 5})
# Estados que NO deben importarse (cancelado, reembolsado, error de pago)
_PS_SKIP_STATES = frozenset({6, 7, 8})
# IDs de cuentas sistema PS (Anonymous GDPR, John DOE demo) — no son compradores reales
_PS_SYSTEM_CUSTOMER_IDS = frozenset({1, 2})


class PrestashopOrder(models.Model):
    _name = 'prestashop.order'
    _description = 'Pedido importado de PrestaShop'

    odoo_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Pedido Odoo',
        required=True,
        ondelete='restrict',
    )
    prestashop_id = fields.Integer(
        string='ID en PrestaShop',
        readonly=True,
    )
    prestashop_reference = fields.Char(
        string='Referencia PrestaShop',
        readonly=True,
    )
    config_id = fields.Many2one(
        comodel_name='prestashop.config',
        string='Configuración',
        required=True,
    )
    sync_state = fields.Selection(
        selection=[
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado',
        default='synced',
    )
    last_sync = fields.Datetime(string='Última sync', readonly=True)
    sync_message = fields.Text(string='Último mensaje', readonly=True)

    _sql_constraints = [
        (
            'ps_order_config_uniq',
            'unique(config_id, prestashop_id)',
            'Ya existe un pedido con este ID de PrestaShop en esta configuración.',
        ),
    ]

    @api.model
    def import_order(self, config, ps_order_id):
        """Importa un pedido de PrestaShop hacia Odoo. Omite si ya existe el binding."""
        if self.search([('config_id', '=', config.id), ('prestashop_id', '=', ps_order_id)], limit=1):
            _logger.debug('Pedido PS %s ya importado, omitiendo.', ps_order_id)
            return

        try:
            response = config.prestashop_get(f'orders/{ps_order_id}')
            root = config.prestashop_parse_xml(response.text)
            order_el = root.find('.//order')
            if order_el is None:
                raise UserError(f'Pedido PS {ps_order_id} no encontrado en la API.')

            ps_reference = (order_el.findtext('reference') or f'PS{ps_order_id}').strip()
            ps_customer_id = int(order_el.findtext('id_customer') or 0)
            ps_status = int(order_el.findtext('current_state') or 0)

            if ps_status in _PS_SKIP_STATES:
                _logger.info(
                    'Pedido PS %s omitido — estado %s (cancelado/reembolsado/error).',
                    ps_order_id, ps_status,
                )
                return None

            if ps_customer_id in _PS_SYSTEM_CUSTOMER_IDS:
                partner = self._partner_from_delivery_address(config, order_el)
            else:
                partner = self.env['prestashop.customer'].import_customer(config, ps_customer_id)
            order_lines = self._parse_order_lines(config, order_el)

            if not order_lines:
                raise UserError(f'El pedido PS {ps_order_id} no contiene líneas de producto.')

            sale_order = self.env['sale.order'].create({
                'partner_id': partner.id,
                'origin': f'PrestaShop {ps_reference}',
                'client_order_ref': ps_reference,
                'order_line': [(0, 0, line) for line in order_lines],
            })

            if ps_status in _PS_CONFIRMED_STATES:
                sale_order.action_confirm()

            self.create({
                'odoo_order_id': sale_order.id,
                'prestashop_id': ps_order_id,
                'prestashop_reference': ps_reference,
                'config_id': config.id,
                'sync_state': 'synced',
                'last_sync': fields.Datetime.now(),
                'sync_message': f'Importado. Estado PS: {ps_status}.',
            })
            _logger.info('Pedido PS %s (%s) importado → %s', ps_order_id, ps_reference, sale_order.name)
            return sale_order

        except UserError:
            raise
        except Exception as exc:
            raise UserError(f'Error inesperado importando pedido PS {ps_order_id}: {exc}') from exc

    def _parse_order_lines(self, config, order_el):
        """Extrae las líneas del pedido desde el XML y las mapea a productos Odoo."""
        lines = []
        for row in order_el.findall('.//order_row'):
            ps_product_id_text = row.findtext('product_id')
            ps_product_id = int(ps_product_id_text) if ps_product_id_text else 0
            product_name = (row.findtext('product_name') or 'Producto PS').strip()
            qty = float(row.findtext('product_quantity') or 1)
            price = float(row.findtext('unit_price_tax_excl') or 0.0)

            product = self._resolve_product(config, ps_product_id, product_name)
            lines.append({
                'product_id': product.id,
                'name': product_name,
                'product_uom_qty': qty,
                'price_unit': price,
                'tax_id': [(5, 0, 0)],  # precio PS ya incluye impuestos; se limpian para no duplicar
            })
        return lines

    def _partner_from_delivery_address(self, config, order_el):
        """
        Construye o reutiliza un res.partner desde la dirección de entrega del pedido.
        Se usa cuando el id_customer pertenece a una cuenta sistema PS (Anonymous/John DOE).
        """
        addr_id_text = (order_el.findtext('id_address_delivery') or '').strip()
        if addr_id_text.isdigit():
            try:
                resp = config.prestashop_get(f'addresses/{addr_id_text}')
                root = config.prestashop_parse_xml(resp.text)
                addr_el = root.find('.//address')
                if addr_el is not None:
                    firstname = (addr_el.findtext('firstname') or '').strip()
                    lastname = (addr_el.findtext('lastname') or '').strip()
                    name = f'{firstname} {lastname}'.strip()
                    phone = (addr_el.findtext('phone_mobile') or addr_el.findtext('phone') or '').strip()
                    street = (addr_el.findtext('address1') or '').strip()
                    city = (addr_el.findtext('city') or '').strip()
                    postcode = (addr_el.findtext('postcode') or '').strip()

                    if name:
                        partner = self.env['res.partner'].search([('name', '=', name)], limit=1)
                        if partner:
                            return partner
                        vals = {'name': name, 'customer_rank': 1}
                        if phone:
                            vals['mobile'] = phone
                        if street:
                            vals['street'] = street
                        if city:
                            vals['city'] = city
                        if postcode:
                            vals['zip'] = postcode
                        return self.env['res.partner'].create(vals)
            except Exception as exc:
                _logger.warning('No se pudo obtener dirección de entrega %s: %s', addr_id_text, exc)

        # Fallback: partner genérico compartido para pedidos sin datos de comprador
        partner = self.env['res.partner'].search([('name', '=', 'Invitado PrestaShop')], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({'name': 'Invitado PrestaShop', 'customer_rank': 1})
        return partner

    def _resolve_product(self, config, ps_product_id, product_name):
        """
        Devuelve un product.product para el ID de PS dado.
        Si no existe binding, crea un producto de tipo servicio como fallback
        para no bloquear la importación del pedido.
        """
        if ps_product_id:
            binding = self.env['prestashop.product'].search([
                ('config_id', '=', config.id),
                ('prestashop_id', '=', ps_product_id),
            ], limit=1)
            if binding and binding.odoo_product_id.product_variant_ids:
                return binding.odoo_product_id.product_variant_ids[:1]

        # Fallback: buscar o crear producto de servicio con el mismo nombre
        tmpl = self.env['product.template'].search(
            [('name', '=', product_name), ('type', '=', 'service')],
            limit=1,
        )
        if not tmpl:
            tmpl = self.env['product.template'].create({
                'name': product_name,
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
            })
            _logger.info('Producto fallback creado para línea PS: "%s"', product_name)
        return tmpl.product_variant_ids[:1]
