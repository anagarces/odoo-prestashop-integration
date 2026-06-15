from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PrestashopProduct(models.Model):
    _name = 'prestashop.product'
    _description = 'Producto sincronizado con PrestaShop'

    odoo_product_id = fields.Many2one(
        comodel_name='product.template',
        string='Producto Odoo',
        required=True,
        ondelete='cascade'
    )
    prestashop_id = fields.Integer(
        string='ID en PrestaShop',
        readonly=True
    )
    prestashop_reference = fields.Char(
        string='Referencia PrestaShop',
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
            'odoo_product_config_uniq',
            'unique(config_id, odoo_product_id)',
            'Ya existe un vínculo para este producto Odoo en esta configuración.',
        ),
    ]

    def _get_prestashop_category_id(self, product, config):
        if product.categ_id:
            mapping = self.env['prestashop.category'].search([
                ('config_id', '=', config.id),
                ('odoo_category_id', '=', product.categ_id.id),
                ('prestashop_id', '!=', False),
            ], limit=1)
            if mapping:
                return mapping.prestashop_id
        return config.default_category_ps_id or 2

    def _build_product_xml(self, product, config, lang_id):
        name = product.name or ''
        price = product.list_price or 0.0
        reference = product.default_code or ''
        description = product.description_sale or name
        slug = self.env['prestashop.api.mixin'].prestashop_slugify(name)
        category_id = self._get_prestashop_category_id(product, config)
        tax_group_id = config.default_tax_rules_group_id or 1

        product_open = f'<product><id>{self.prestashop_id}</id>' if self.prestashop_id else '<product>'

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    {product_open}
        <state>1</state>
        <active>1</active>
        <id_category_default>{category_id}</id_category_default>
        <id_tax_rules_group>{tax_group_id}</id_tax_rules_group>
        <price>{price:.6f}</price>
        <reference>{reference}</reference>
        <minimal_quantity>1</minimal_quantity>
        <show_price>1</show_price>
        <available_for_order>1</available_for_order>
        <name>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </name>
        <description>
            <language id="{lang_id}"><![CDATA[{description}]]></language>
        </description>
        <description_short>
            <language id="{lang_id}"><![CDATA[{description[:100]}]]></language>
        </description_short>
        <link_rewrite>
            <language id="{lang_id}"><![CDATA[{slug}]]></language>
        </link_rewrite>
        <meta_title>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </meta_title>
        <associations>
            <categories>
                <category>
                    <id>{category_id}</id>
                </category>
            </categories>
        </associations>
    </product>
</prestashop>"""

    def _sync_stock_to_prestashop(self, config, prestashop_product_id, quantity):
        """Actualiza el stock disponible del producto en PrestaShop."""
        response = config.prestashop_get(
            'stock_availables',
            params={
                'filter[id_product]': f'[{prestashop_product_id}]',
                'filter[id_product_attribute]': '[0]',
            },
        )
        root = config.prestashop_parse_xml(response.text)
        id_element = root.find('.//stock_available/id') or root.find('.//id')
        stock_id = int(id_element.text.strip()) if id_element is not None and id_element.text else None
        if not stock_id:
            _logger.warning(
                'No se encontró stock_available para producto PS %s',
                prestashop_product_id,
            )
            return

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    <stock_available>
        <id>{stock_id}</id>
        <id_product>{prestashop_product_id}</id_product>
        <id_product_attribute>0</id_product_attribute>
        <quantity>{int(quantity)}</quantity>
    </stock_available>
</prestashop>"""
        config.prestashop_put(f'stock_availables/{stock_id}', xml_data)

    def import_product(self, config, ps_product_id):
        """Importa un producto de PrestaShop hacia Odoo.

        Retorna None si el binding ya existe (idempotente).
        Retorna el product.template creado/encontrado si se importó correctamente.
        Estrategia de deduplicación: busca por referencia interna (default_code) antes de crear.
        """
        existing = self.search([
            ('config_id', '=', config.id),
            ('prestashop_id', '=', ps_product_id),
        ], limit=1)
        if existing:
            return None

        response = config.prestashop_get(f'products/{ps_product_id}', params={'display': 'full'})
        root = config.prestashop_parse_xml(response.text)
        p = root.find('.//product')
        if p is None:
            raise UserError(f'No se encontraron datos para el producto PS {ps_product_id}.')

        # Nombre: preferir idioma configurado, caer al primero disponible
        lang_id = str(config.default_lang_id or 1)
        name_el = (
            p.find(f'.//name/language[@id="{lang_id}"]')
            or p.find('.//name/language')
        )
        name = (name_el.text or '').strip() if name_el is not None else f'Producto PS {ps_product_id}'

        reference = (p.findtext('reference') or '').strip() or None
        price = float(p.findtext('price') or 0)

        desc_el = (
            p.find(f'.//description_short/language[@id="{lang_id}"]')
            or p.find('.//description_short/language')
        )
        description = (desc_el.text or '').strip() if desc_el is not None else ''

        # Categoría Odoo via binding de categoría PS
        categ_id = (
            self.env['product.category']
            .search([('complete_name', '=', 'All / Saleable')], limit=1).id
            or self.env.ref('product.product_category_all').id
        )
        ps_cat_text = p.findtext('id_category_default')
        if ps_cat_text and ps_cat_text.strip().isdigit():
            cat_binding = self.env['prestashop.category'].search([
                ('config_id', '=', config.id),
                ('prestashop_id', '=', int(ps_cat_text)),
            ], limit=1)
            if cat_binding:
                categ_id = cat_binding.odoo_category_id.id

        # Deduplicación por referencia interna → evita duplicados si el producto
        # ya existe en Odoo con el mismo código
        odoo_product = None
        if reference:
            odoo_product = self.env['product.template'].search(
                [('default_code', '=', reference)], limit=1
            )

        if not odoo_product:
            vals = {
                'name': name,
                'type': 'product',
                'list_price': price,
                'sale_ok': True,
                'categ_id': categ_id,
            }
            if reference:
                vals['default_code'] = reference
            if description:
                vals['description_sale'] = description
            odoo_product = self.env['product.template'].create(vals)

        self.create({
            'config_id': config.id,
            'odoo_product_id': odoo_product.id,
            'prestashop_id': ps_product_id,
            'prestashop_reference': reference or '',
            'sync_state': 'synced',
            'last_sync': fields.Datetime.now(),
            'sync_message': f'Importado desde PS. Precio: {price}',
        })
        _logger.info('Producto PS %s "%s" importado → Odoo ID %s', ps_product_id, name, odoo_product.id)
        return odoo_product

    def sync_to_prestashop(self):
        """Sincroniza el producto de Odoo hacia PrestaShop, incluyendo stock."""
        for record in self:
            record._sync_single_product()

    def _sync_single_product(self):
        self.ensure_one()
        config = self.config_id
        product = self.odoo_product_id
        lang_id = config.default_lang_id or config.prestashop_get_default_language_id()

        try:
            xml_data = self._build_product_xml(product, config, lang_id)
            if self.prestashop_id:
                response = config.prestashop_put(
                    f'products/{self.prestashop_id}',
                    xml_data,
                )
            else:
                response = config.prestashop_post('products', xml_data)

            ps_id = config.prestashop_extract_id(response.text) or self.prestashop_id
            quantity = int(product.qty_available)

            if ps_id:
                self._sync_stock_to_prestashop(config, ps_id, quantity)

            reference = product.default_code or ''
            self.write({
                'prestashop_id': ps_id,
                'prestashop_reference': reference,
                'sync_state': 'synced',
                'last_sync': fields.Datetime.now(),
                'sync_message': (
                    f'Sincronizado correctamente. PS ID: {ps_id}, stock: {quantity}'
                ),
            })
            config.last_products_sync = fields.Datetime.now()
            _logger.info(
                'Producto %s sincronizado. PS ID: %s, stock: %s',
                product.name,
                ps_id,
                quantity,
            )
        except UserError as exc:
            self.write({
                'sync_state': 'error',
                'sync_message': str(exc),
            })
            raise
