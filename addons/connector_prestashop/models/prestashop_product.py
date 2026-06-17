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
    combination_ids = fields.One2many(
        comodel_name='prestashop.product.combination',
        inverse_name='product_binding_id',
        string='Combinaciones',
        readonly=True,
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

    def _sync_stock_to_prestashop(self, config, prestashop_product_id, quantity, ps_combination_id=0):
        """Actualiza el stock disponible del producto (o combinación) en PrestaShop.

        ps_combination_id=0 → producto simple (sin variante).
        ps_combination_id>0 → combinación específica (talla, color…).
        """
        response = config.prestashop_get(
            'stock_availables',
            params={
                'filter[id_product]': f'[{prestashop_product_id}]',
                'filter[id_product_attribute]': f'[{ps_combination_id}]',
            },
        )
        root = config.prestashop_parse_xml(response.text)
        id_element = root.find('.//stock_available/id') or root.find('.//id')
        stock_id = int(id_element.text.strip()) if id_element is not None and id_element.text else None
        if not stock_id:
            _logger.warning(
                'No se encontró stock_available para producto PS %s (combination=%s)',
                prestashop_product_id, ps_combination_id,
            )
            return

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    <stock_available>
        <id>{stock_id}</id>
        <id_product>{prestashop_product_id}</id_product>
        <id_product_attribute>{ps_combination_id}</id_product_attribute>
        <quantity>{int(quantity)}</quantity>
    </stock_available>
</prestashop>"""
        config.prestashop_put(f'stock_availables/{stock_id}', xml_data)

    def import_product(self, config, ps_product_id):
        """Importa un producto de PrestaShop hacia Odoo (idempotente).

        Detecta automáticamente si el producto tiene combinaciones (variantes).
        Sin combinaciones → product.template simple.
        Con combinaciones → product.template + product.product por variante + bindings de combinación.
        """
        if self.search([('config_id', '=', config.id), ('prestashop_id', '=', ps_product_id)], limit=1):
            return None

        response = config.prestashop_get(f'products/{ps_product_id}', params={'display': 'full'})
        root = config.prestashop_parse_xml(response.text)
        p = root.find('.//product')
        if p is None:
            raise UserError(f'No se encontraron datos para el producto PS {ps_product_id}.')

        lang_id = str(config.default_lang_id or 1)
        name_el = p.find(f'.//name/language[@id="{lang_id}"]') or p.find('.//name/language')
        name = (name_el.text or '').strip() if name_el is not None else f'Producto PS {ps_product_id}'

        reference = (p.findtext('reference') or '').strip() or None
        price = float(p.findtext('price') or 0)

        desc_el = (
            p.find(f'.//description_short/language[@id="{lang_id}"]')
            or p.find('.//description_short/language')
        )
        description = (desc_el.text or '').strip() if desc_el is not None else ''

        categ_id = (
            self.env['product.category'].search([('complete_name', '=', 'All / Saleable')], limit=1).id
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

        # Detectar combinaciones
        combination_ids = [
            int(c.findtext('id'))
            for c in p.findall('.//associations/combinations/combination')
            if c.findtext('id') and c.findtext('id').strip().isdigit()
        ]

        if combination_ids:
            return self._import_product_with_combinations(
                config, ps_product_id, combination_ids,
                name, reference, price, categ_id, lang_id, description,
            )

        # Producto simple — dedup por referencia interna
        odoo_product = (
            self.env['product.template'].search([('default_code', '=', reference)], limit=1)
            if reference else self.env['product.template']
        )
        if not odoo_product:
            vals = {'name': name, 'type': 'product', 'list_price': price,
                    'sale_ok': True, 'categ_id': categ_id}
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

    def _import_product_with_combinations(
        self, config, ps_product_id, combination_ids,
        name, reference, price, categ_id, lang_id, description,
    ):
        """Importa un producto PS con combinaciones como product.template con variantes Odoo.

        Flujo:
        1. Crear/encontrar product.template (dedup por referencia).
        2. Obtener atributos y valores de cada combinación PS (con caché local).
        3. Crear product.attribute / product.attribute.value si no existen.
        4. Añadir attribute_line_ids al template → Odoo genera las variantes automáticamente.
        5. Emparejar cada combinación PS con su product.product y crear el binding.
        """
        # 1. Crear/encontrar template
        odoo_product = (
            self.env['product.template'].search([('default_code', '=', reference)], limit=1)
            if reference else self.env['product.template']
        )
        if not odoo_product:
            vals = {'name': name, 'type': 'product', 'list_price': price,
                    'sale_ok': True, 'categ_id': categ_id}
            if reference:
                vals['default_code'] = reference
            if description:
                vals['description_sale'] = description
            odoo_product = self.env['product.template'].create(vals)

        # 2. Binding a nivel de plantilla
        binding = self.create({
            'config_id': config.id,
            'odoo_product_id': odoo_product.id,
            'prestashop_id': ps_product_id,
            'prestashop_reference': reference or '',
            'sync_state': 'synced',
            'last_sync': fields.Datetime.now(),
            'sync_message': f'Importado con {len(combination_ids)} combinaciones.',
        })

        # 3. Obtener datos de combinaciones con caché para minimizar llamadas API
        option_cache = {}       # {ps_option_id: attr_name}
        option_val_cache = {}   # {ps_option_value_id: (val_name, ps_option_id)}
        # {ps_option_id: (attr_name, {ps_ov_id: val_name})}
        attr_map = {}
        combination_data = []   # [{combo_id, attrs:{attr_name: val_name}}]

        for combo_id in combination_ids:
            try:
                combo_resp = config.prestashop_get(
                    f'combinations/{combo_id}', params={'display': 'full'}
                )
                combo_el = config.prestashop_parse_xml(combo_resp.text).find('.//combination')
                if combo_el is None:
                    continue

                ov_ids = [
                    int(ov.findtext('id'))
                    for ov in combo_el.findall('.//associations/product_option_values/product_option_value')
                    if ov.findtext('id') and ov.findtext('id').strip().isdigit()
                ]
                combo_attrs = {}

                for ov_id in ov_ids:
                    if ov_id not in option_val_cache:
                        ov_resp = config.prestashop_get(f'product_option_values/{ov_id}')
                        ov_el = config.prestashop_parse_xml(ov_resp.text).find('.//product_option_value')
                        ov_name_el = (
                            ov_el.find(f'.//name/language[@id="{lang_id}"]')
                            or ov_el.find('.//name/language')
                        )
                        ov_name = (ov_name_el.text or '').strip() if ov_name_el is not None else f'Valor {ov_id}'
                        ps_opt_id = int(ov_el.findtext('id_attribute') or 0)
                        option_val_cache[ov_id] = (ov_name, ps_opt_id)
                    else:
                        ov_name, ps_opt_id = option_val_cache[ov_id]

                    if ps_opt_id and ps_opt_id not in option_cache:
                        opt_resp = config.prestashop_get(f'product_options/{ps_opt_id}')
                        opt_el = config.prestashop_parse_xml(opt_resp.text).find('.//product_option')
                        opt_name_el = (
                            opt_el.find(f'.//name/language[@id="{lang_id}"]')
                            or opt_el.find('.//name/language')
                        )
                        option_cache[ps_opt_id] = (
                            (opt_name_el.text or '').strip() if opt_name_el is not None
                            else f'Atributo {ps_opt_id}'
                        )

                    attr_name = option_cache.get(ps_opt_id, f'Atributo {ps_opt_id}')
                    combo_attrs[attr_name] = ov_name

                    if ps_opt_id not in attr_map:
                        attr_map[ps_opt_id] = (attr_name, {})
                    attr_map[ps_opt_id][1][ov_id] = ov_name

                if combo_attrs:
                    combination_data.append({'combo_id': combo_id, 'attrs': combo_attrs})

            except Exception as exc:
                _logger.error('Error obteniendo combinación PS %s: %s', combo_id, exc)

        if not combination_data:
            _logger.warning('Producto PS %s: no se pudieron cargar combinaciones.', ps_product_id)
            return odoo_product

        # 4. Crear atributos y valores Odoo, añadir attribute_line_ids si el template es nuevo
        odoo_attr_lines = {}  # {attr_name: (product.attribute, {val_name: product.attribute.value})}
        for ps_opt_id, (attr_name, val_map) in attr_map.items():
            odoo_attr = self.env['product.attribute'].search([('name', '=', attr_name)], limit=1)
            if not odoo_attr:
                odoo_attr = self.env['product.attribute'].create({'name': attr_name})

            value_objs = {}
            for _ov_id, val_name in val_map.items():
                odoo_val = self.env['product.attribute.value'].search([
                    ('attribute_id', '=', odoo_attr.id), ('name', '=', val_name),
                ], limit=1)
                if not odoo_val:
                    odoo_val = self.env['product.attribute.value'].create(
                        {'attribute_id': odoo_attr.id, 'name': val_name}
                    )
                value_objs[val_name] = odoo_val
            odoo_attr_lines[attr_name] = (odoo_attr, value_objs)

        if not odoo_product.attribute_line_ids:
            for attr_name, (odoo_attr, value_objs) in odoo_attr_lines.items():
                odoo_product.write({'attribute_line_ids': [(0, 0, {
                    'attribute_id': odoo_attr.id,
                    'value_ids': [(6, 0, [v.id for v in value_objs.values()])],
                })]})
            # Invalidar caché para ver las variantes recién generadas
            odoo_product.invalidate_recordset(['product_variant_ids'])

        # 5. Emparejar cada combinación PS con su variante Odoo y crear binding
        CombModel = self.env['prestashop.product.combination']
        for combo in combination_data:
            combo_id = combo['combo_id']
            combo_attrs = combo['attrs']  # {attr_name: val_name}

            odoo_variant = None
            for variant in odoo_product.product_variant_ids:
                variant_attrs = {
                    ptav.attribute_id.name: ptav.product_attribute_value_id.name
                    for ptav in variant.product_template_attribute_value_ids
                }
                if variant_attrs == combo_attrs:
                    odoo_variant = variant
                    break

            if not odoo_variant:
                _logger.warning(
                    'Producto PS %s: no se encontró variante Odoo para combinación %s %s',
                    ps_product_id, combo_id, combo_attrs,
                )
                continue

            CombModel.create({
                'config_id': config.id,
                'product_binding_id': binding.id,
                'odoo_variant_id': odoo_variant.id,
                'prestashop_combination_id': combo_id,
                'sync_state': 'synced',
                'last_sync': fields.Datetime.now(),
                'sync_message': str(combo_attrs),
            })
            _logger.info(
                'Combinación PS %s → variante "%s" (Odoo ID %s)',
                combo_id, odoo_variant.display_name, odoo_variant.id,
            )

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
