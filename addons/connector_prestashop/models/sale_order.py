import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Mapeo de estados Odoo → PS
_ODOO_TO_PS_STATE = {
    'sale': 2,    # Pago aceptado
    'cancel': 6,  # Cancelado
}


class SaleOrder(models.Model):
    """Extiende sale.order para sincronizar cambios de estado hacia PrestaShop.

    Solo actúa cuando el pedido tiene un binding prestashop.order asociado.
    Los errores de API PS nunca bloquean el flujo normal de Odoo.
    El contexto skip_ps_state_push evita el push circular durante la importación.
    """
    _inherit = 'sale.order'

    def write(self, vals):
        result = super().write(vals)
        new_state = vals.get('state')
        if new_state in _ODOO_TO_PS_STATE and not self.env.context.get('skip_ps_state_push'):
            ps_state_id = _ODOO_TO_PS_STATE[new_state]
            PsOrder = self.env['prestashop.order'].sudo()
            for rec in self:
                binding = PsOrder.search([('odoo_order_id', '=', rec.id)], limit=1)
                if binding and binding.prestashop_id:
                    binding._push_state_to_prestashop(ps_state_id)
        return result
