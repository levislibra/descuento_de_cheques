# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Descuento de cheques',
    'version': '1.0',
    'author': 'Libra Levis',
    'category': 'Financiera',
    'summary': 'Descuento de cheques',
    'description': """
Descuento de cheques
===========================

Manejo de operatoria de descuento de cheques a clientes.

""",
    'website': 'www.levislibra.com.ar',
    'depends': [cheques_de_terceros],
    'test': [
        
    ],

    'data': [
        'liquidacion_view.xml',

    ],
    'installable': True,
    'auto_install': False,
}