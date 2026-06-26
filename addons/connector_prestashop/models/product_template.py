import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Campos cuyo cambio debe propagarse a PrestaShop si el producto tiene binding activo
_PS_WATCHED_FIELDS = frozenset({'name', 'list_price', 'description_sale', 'default_code', 'categ_id'})


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    prestashop_binding_ids = fields.One2many(
        comodel_name='prestashop.product',
        inverse_name='odoo_product_id',
        string='Vínculos PrestaShop',
    )
    prestashop_sync_state = fields.Selection(
        selection=[
            ('none', 'Sin vincular'),
            ('pending', 'Pendiente'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado PrestaShop',
        compute='_compute_prestashop_sync_state',
    )

    def _compute_prestashop_sync_state(self):
        for product in self:
            bindings = product.prestashop_binding_ids
            if not bindings:
                product.prestashop_sync_state = 'none'
            elif any(b.sync_state == 'error' for b in bindings):
                product.prestashop_sync_state = 'error'
            elif all(b.sync_state == 'synced' for b in bindings):
                product.prestashop_sync_state = 'synced'
            else:
                product.prestashop_sync_state = 'pending'

    def write(self, vals):
        result = super().write(vals)
        if _PS_WATCHED_FIELDS & vals.keys():
            PsProduct = self.env['prestashop.product'].sudo()
            for product in self:
                bindings = PsProduct.search([
                    ('odoo_product_id', '=', product.id),
                    ('prestashop_id', '>', 0),
                ])
                for binding in bindings:
                    try:
                        binding._sync_single_product()
                    except Exception as exc:
                        _logger.error(
                            'Auto-sync PS falló para "%s": %s', product.name, exc,
                        )
        return result

    def action_sync_to_prestashop(self):
        """Crea el vínculo si no existe y sincroniza el producto a PrestaShop."""
        config = self.env['prestashop.config'].get_active_config()
        for product in self:
            binding = self.env['prestashop.product'].search([
                ('odoo_product_id', '=', product.id),
                ('config_id', '=', config.id),
            ], limit=1)
            if not binding:
                binding = self.env['prestashop.product'].create({
                    'odoo_product_id': product.id,
                    'config_id': config.id,
                })
            binding.sync_to_prestashop()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sincronización completada',
                'message': f'{len(self)} producto(s) enviado(s) a PrestaShop.',
                'type': 'success',
                'sticky': False,
            },
        }
