import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    """Extensión mínima de res.partner para exponer el vínculo con PS.

    No altera ningún campo nativo — solo añade la relación inversa y el
    contador necesario para el smart button en el formulario de Contacts.
    """
    _inherit = 'res.partner'

    prestashop_customer_ids = fields.One2many(
        comodel_name='prestashop.customer',
        inverse_name='odoo_partner_id',
        string='Cuentas PrestaShop',
        readonly=True,
    )
    prestashop_customer_count = fields.Integer(
        compute='_compute_prestashop_customer_count',
        string='Cuentas PS',
    )

    @api.depends('prestashop_customer_ids')
    def _compute_prestashop_customer_count(self):
        for partner in self:
            partner.prestashop_customer_count = len(partner.prestashop_customer_ids)

    def action_view_prestashop_account(self):
        """Abre los registros de cliente PS vinculados a este contacto."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cuenta PrestaShop',
            'res_model': 'prestashop.customer',
            'view_mode': 'tree,form',
            'domain': [('odoo_partner_id', '=', self.id)],
            'context': {'default_odoo_partner_id': self.id},
        }


class PrestashopCustomer(models.Model):
    _name = 'prestashop.customer'

    _description = 'Cliente importado de PrestaShop'

    odoo_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contacto Odoo',
        required=True,
        ondelete='restrict',
    )
    prestashop_id = fields.Integer(
        string='ID en PrestaShop',
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
    # Campos relacionados para mostrar en vistas sin notación de punto
    partner_email = fields.Char(related='odoo_partner_id.email', string='Email', readonly=True)
    partner_mobile = fields.Char(related='odoo_partner_id.mobile', string='Teléfono', readonly=True)
    partner_street = fields.Char(related='odoo_partner_id.street', string='Dirección', readonly=True)
    partner_city = fields.Char(related='odoo_partner_id.city', string='Ciudad', readonly=True)

    _sql_constraints = [
        (
            'ps_customer_config_uniq',
            'unique(config_id, prestashop_id)',
            'Ya existe un cliente con este ID de PrestaShop en esta configuración.',
        ),
    ]

    def action_open_partner(self):
        """Navega al formulario nativo del contacto Odoo vinculado."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.odoo_partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def import_customer(self, config, ps_customer_id):
        """Importa o actualiza un cliente desde PrestaShop. Retorna el res.partner."""
        binding = self.search([
            ('config_id', '=', config.id),
            ('prestashop_id', '=', ps_customer_id),
        ], limit=1)

        try:
            response = config.prestashop_get(f'customers/{ps_customer_id}')
            root = config.prestashop_parse_xml(response.text)
            customer_el = root.find('.//customer')
            if customer_el is None:
                raise UserError(f'Cliente PS {ps_customer_id} no encontrado en la API.')

            firstname = (customer_el.findtext('firstname') or '').strip()
            lastname = (customer_el.findtext('lastname') or '').strip()
            email = (customer_el.findtext('email') or '').strip()
            name = f'{firstname} {lastname}'.strip() or email or f'Cliente PS {ps_customer_id}'

            partner_vals = self._fetch_partner_vals(config, ps_customer_id, name, email)

            if binding:
                binding.odoo_partner_id.write(partner_vals)
                binding.write({
                    'sync_state': 'synced',
                    'last_sync': fields.Datetime.now(),
                    'sync_message': 'Actualizado desde PrestaShop.',
                })
                return binding.odoo_partner_id

            # Evitar duplicados buscando por email
            partner = (
                self.env['res.partner'].search([('email', '=', email)], limit=1)
                if email else self.env['res.partner']
            )
            if partner:
                partner.write(partner_vals)
            else:
                partner = self.env['res.partner'].create(partner_vals)

            self.create({
                'odoo_partner_id': partner.id,
                'prestashop_id': ps_customer_id,
                'config_id': config.id,
                'sync_state': 'synced',
                'last_sync': fields.Datetime.now(),
                'sync_message': 'Importado desde PrestaShop.',
            })
            _logger.info('Cliente PS %s importado → partner %s (id=%s)', ps_customer_id, partner.name, partner.id)
            return partner

        except UserError:
            if binding:
                binding.write({'sync_state': 'error', 'sync_message': 'Error al sincronizar.'})
            raise

    def _fetch_partner_vals(self, config, ps_customer_id, name, email):
        """Construye los valores de res.partner enriquecidos con la dirección de PS."""
        vals = {'name': name, 'email': email, 'customer_rank': 1}
        try:
            addr_resp = config.prestashop_get(
                'addresses',
                params={
                    'filter[id_customer]': f'[{ps_customer_id}]',
                    'display': 'full',
                },
            )
            root = config.prestashop_parse_xml(addr_resp.text)
            addr_el = root.find('.//address')
            if addr_el is not None:
                street = addr_el.findtext('address1') or ''
                city = addr_el.findtext('city') or ''
                postcode = addr_el.findtext('postcode') or ''
                phone = addr_el.findtext('phone_mobile') or addr_el.findtext('phone') or ''
                if street:
                    vals['street'] = street
                if city:
                    vals['city'] = city
                if postcode:
                    vals['zip'] = postcode
                if phone:
                    vals['mobile'] = phone
        except Exception:
            pass  # los datos de dirección son opcionales
        return vals
