from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PrestashopCategory(models.Model):
    _name = 'prestashop.category'
    _description = 'Categoría sincronizada con PrestaShop'

    odoo_category_id = fields.Many2one(
        comodel_name='product.category',
        string='Categoría Odoo',
        required=True,
        ondelete='cascade'
    )
    prestashop_id = fields.Integer(
        string='ID en PrestaShop',
        readonly=True
    )
    config_id = fields.Many2one(
        comodel_name='prestashop.config',
        string='Configuración',
        required=True
    )
    sync_state = fields.Selection(
        selection=[
            ('pending', 'Pendiente'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado sync',
        default='pending'
    )
    last_sync = fields.Datetime(
        string='Última sync',
        readonly=True
    )
    sync_message = fields.Text(
        string='Último mensaje',
        readonly=True
    )

    _sql_constraints = [
        (
            'odoo_category_config_uniq',
            'unique(config_id, odoo_category_id)',
            'Ya existe un mapeo para esta categoría Odoo en esta configuración.',
        ),
    ]

    def _get_parent_prestashop_id(self):
        self.ensure_one()
        parent = self.odoo_category_id.parent_id
        if not parent:
            return self.config_id.default_category_ps_id or 2
        mapping = self.search([
            ('config_id', '=', self.config_id.id),
            ('odoo_category_id', '=', parent.id),
            ('prestashop_id', '!=', False),
        ], limit=1)
        if mapping:
            return mapping.prestashop_id
        return self.config_id.default_category_ps_id or 2

    def _build_category_xml(self, lang_id):
        self.ensure_one()
        category = self.odoo_category_id
        name = category.name or 'Categoría'
        slug = self.env['prestashop.api.mixin'].prestashop_slugify(name)
        parent_id = self._get_parent_prestashop_id()

        product_tag = f'<category><id>{self.prestashop_id}</id>' if self.prestashop_id else '<category>'

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    {product_tag}
        <active>1</active>
        <id_parent>{parent_id}</id_parent>
        <name>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </name>
        <description>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </description>
        <link_rewrite>
            <language id="{lang_id}"><![CDATA[{slug}]]></language>
        </link_rewrite>
    </category>
</prestashop>"""

    def sync_to_prestashop(self):
        """Sincroniza la categoría de Odoo hacia PrestaShop."""
        for record in self:
            record._sync_single_category()

    def _sync_single_category(self):
        self.ensure_one()
        config = self.config_id
        lang_id = config.default_lang_id or config.prestashop_get_default_language_id()

        try:
            xml_data = self._build_category_xml(lang_id)
            if self.prestashop_id:
                response = config.prestashop_put(
                    f'categories/{self.prestashop_id}',
                    xml_data,
                )
            else:
                response = config.prestashop_post('categories', xml_data)

            ps_id = config.prestashop_extract_id(response.text)
            self.write({
                'prestashop_id': ps_id or self.prestashop_id,
                'sync_state': 'synced',
                'last_sync': fields.Datetime.now(),
                'sync_message': f'Categoría sincronizada. PS ID: {ps_id or self.prestashop_id}',
            })
            _logger.info(
                'Categoría %s sincronizada. PS ID: %s',
                self.odoo_category_id.name,
                ps_id or self.prestashop_id,
            )
        except UserError as exc:
            self.write({
                'sync_state': 'error',
                'sync_message': str(exc),
            })
            raise
