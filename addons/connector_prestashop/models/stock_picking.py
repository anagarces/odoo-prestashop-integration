import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    """Extensión mínima de stock.picking para sincronizar stock a PrestaShop
    cuando se valida un albarán (entrega, recepción o ajuste de inventario).

    El hook actúa en write(state='done') porque en ese momento los quants
    ya están actualizados y qty_available refleja el nuevo saldo real.
    Los errores de la API de PS nunca interrumpen la validación del albarán.
    """
    _inherit = 'stock.picking'

    def write(self, vals):
        result = super().write(vals)
        if vals.get('state') == 'done':
            self._ps_sync_moved_products()
        return result

    def _ps_sync_moved_products(self):
        """Actualiza el stock en PS para cada producto con binding afectado por este albarán.

        Ejecuta las consultas a modelos PS en sudo para que usuarios de almacén
        sin acceso de gestor puedan validar albaranes sin errores de permisos.
        La clave API de PS nunca queda expuesta al usuario que valida.
        """
        sudo_env = self.env['prestashop.config'].sudo()
        config = sudo_env.search([
            ('active', '=', True),
            ('state', '=', 'connected'),
        ], limit=1)
        if not config:
            return

        product_tmpls = self.mapped('move_ids.product_id.product_tmpl_id')
        if not product_tmpls:
            return

        bindings = self.env['prestashop.product'].sudo().search([
            ('config_id', '=', config.id),
            ('odoo_product_id', 'in', product_tmpls.ids),
            ('prestashop_id', '>', 0),
        ])
        if not bindings:
            return

        for binding in bindings:
            try:
                qty = int(binding.odoo_product_id.qty_available)
                binding._sync_stock_to_prestashop(config, binding.prestashop_id, qty)
                _logger.info(
                    'Stock PS actualizado (albarán %s): "%s" → %s uds',
                    self.name, binding.odoo_product_id.name, qty,
                )
            except Exception as exc:
                _logger.error(
                    'Error sync stock PS (albarán %s, producto "%s"): %s',
                    self.name, binding.odoo_product_id.name, exc,
                )
