import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    """Extensión de stock.picking para sincronizar stock a PrestaShop al validar albaranes.

    Cuando state pasa a 'done', los quants ya están actualizados en la misma transacción,
    por lo que qty_available ya refleja el stock correcto.
    Errores de API PS nunca interrumpen la validación del albarán.
    """
    _inherit = 'stock.picking'

    def write(self, vals):
        result = super().write(vals)
        if vals.get('state') == 'done':
            self._ps_sync_moved_products()
        return result

    def _ps_sync_moved_products(self):
        """Sincroniza stock a PS para cada variante afectada por este albarán.

        Prioridad:
        1. Si el producto tiene bindings de combinación PS → sync a nivel variante.
        2. Si sólo hay binding de plantilla (producto simple) → sync a nivel plantilla.
        Ambos caminos usan sudo para que usuarios de almacén sin rol de gestor puedan
        validar albaranes sin errores de acceso a los modelos PS.
        """
        sudo_config = self.env['prestashop.config'].sudo()
        config = sudo_config.search([('active', '=', True), ('state', '=', 'connected')], limit=1)
        if not config:
            return

        moved_variants = self.mapped('move_ids.product_id')
        if not moved_variants:
            return

        CombModel = self.env['prestashop.product.combination'].sudo()
        ProdModel = self.env['prestashop.product'].sudo()

        for variant in moved_variants:
            tmpl = variant.product_tmpl_id

            # Intentar sync por combinación primero
            combo_binding = CombModel.search([
                ('config_id', '=', config.id),
                ('odoo_variant_id', '=', variant.id),
            ], limit=1)

            if combo_binding and combo_binding.product_binding_id.prestashop_id:
                prod_binding = combo_binding.product_binding_id
                qty = int(variant.qty_available)
                try:
                    prod_binding._sync_stock_to_prestashop(
                        config,
                        prod_binding.prestashop_id,
                        qty,
                        ps_combination_id=combo_binding.prestashop_combination_id,
                    )
                    _logger.info(
                        'Stock PS actualizado (albarán %s): "%s" combinación %s → %s uds',
                        self.name, variant.display_name, combo_binding.prestashop_combination_id, qty,
                    )
                except Exception as exc:
                    _logger.error(
                        'Error sync stock PS (albarán %s, variante "%s"): %s',
                        self.name, variant.display_name, exc,
                    )
                continue

            # Fallback: producto simple (sin combinaciones) — sync a nivel plantilla
            prod_binding = ProdModel.search([
                ('config_id', '=', config.id),
                ('odoo_product_id', '=', tmpl.id),
                ('prestashop_id', '>', 0),
            ], limit=1)

            if not prod_binding:
                continue

            qty = int(tmpl.qty_available)
            try:
                prod_binding._sync_stock_to_prestashop(config, prod_binding.prestashop_id, qty)
                _logger.info(
                    'Stock PS actualizado (albarán %s): "%s" → %s uds',
                    self.name, tmpl.name, qty,
                )
            except Exception as exc:
                _logger.error(
                    'Error sync stock PS (albarán %s, producto "%s"): %s',
                    self.name, tmpl.name, exc,
                )
