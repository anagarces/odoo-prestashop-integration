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
    'depends': [
        'base',
        'product',
        'stock',
        'sale',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/prestashop_config_views.xml',
        'views/prestashop_product_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}