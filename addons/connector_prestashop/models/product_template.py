from odoo import models, fields
from odoo.exceptions import UserError


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
