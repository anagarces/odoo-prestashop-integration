import os

from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    """Crea la configuración PrestaShop por defecto en entornos Docker."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    if env['prestashop.config'].search_count([]):
        return
    env['prestashop.config'].create({
        'name': 'StyleSync PrestaShop',
        'url': os.environ.get('PRESTASHOP_URL', 'http://prestashop'),
        'api_key': os.environ.get('PRESTASHOP_API_KEY', ''),
    })
