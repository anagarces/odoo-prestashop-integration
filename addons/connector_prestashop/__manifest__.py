{
    'name': 'Connector PrestaShop',
    'version': '17.0.1.0.0',
    'category': 'Connector',
    'summary': 'Integración bidireccional entre Odoo y PrestaShop',
    'description': """
        Módulo de integración Odoo ↔ PrestaShop
        ========================================
        Funcionalidades:
        - Sincronizar productos Odoo → PrestaShop
        - Importar pedidos PrestaShop → Odoo
        - Sincronizar clientes PrestaShop → Odoo
        - Sincronizar stock en tiempo real
    """,
    'author': 'StyleSync',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'stock',
        'sales_team',
        'sale',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/prestashop_config_view.xml',
        'views/prestashop_category_view.xml',
        'views/prestashop_product_view.xml',
        'views/prestashop_customer_view.xml',
        'views/res_partner_view.xml',
        'views/prestashop_order_view.xml',
        'views/product_template_view.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}