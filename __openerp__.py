# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Descuento de cheques',
    'version': '1.1',
    'author': 'Libra Levis',
    'category': 'Financiera',
    'summary': 'Descuento de cheques',
    'description': """
Descuento de cheques
===========================

Manejo de operatoria de descuento de cheques a clientes.

""",
    'website': 'www.levislibra.com.ar',
    'depends': ['account_accountant', 'cheques_de_terceros'],
    'test': [
        
    ],

    'data': [
        'descuento_de_cheques_view.xml',
        'views/subcuenta_view.xml',
        'views/cuenta_entidad_view.xml',
        'views/transferencia_view.xml',
        'views/plazo_fijo_view.xml',
        'views/balance_view.xml',

    ],
    'installable': True,
    'auto_install': False,
}