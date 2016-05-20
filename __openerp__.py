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
    'depends': [],
    'test': [
        
    ],

    'data': [
        'descuento_de_cheques_view.xml',
        'models/subcuenta_view.xml'

    ],
    'installable': True,
    'auto_install': False,
}