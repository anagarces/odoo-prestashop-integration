import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PrestashopProductCombination(models.Model):
    _name = 'prestashop.product.combination'
    _description = 'Combinación de producto (variante) sincronizada con PrestaShop'

    config_id = fields.Many2one(
        comodel_name='prestashop.config',
        string='Configuración',
        required=True,
    )
    product_binding_id = fields.Many2one(
        comodel_name='prestashop.product',
        string='Producto PS',
        required=True,
        ondelete='cascade',
    )
    odoo_variant_id = fields.Many2one(
        comodel_name='product.product',
        string='Variante Odoo',
        required=True,
        ondelete='cascade',
    )
    prestashop_combination_id = fields.Integer(
        string='ID Combinación PS',
        readonly=True,
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
    sync_message = fields.Text(string='Mensaje', readonly=True)

    _sql_constraints = [
        (
            'ps_combination_config_uniq',
            'unique(config_id, prestashop_combination_id)',
            'Ya existe un binding para esta combinación de PrestaShop en esta configuración.',
        ),
    ]
