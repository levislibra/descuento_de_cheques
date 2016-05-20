# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

#from openerp.osv import osv, orm
#from datetime import time, datetime
#from openerp.tools.translate import _
#from openerp import models, fields


import pytz
import re
import time
import openerp
import openerp.service.report
import uuid
import collections
import babel.dates
from werkzeug.exceptions import BadRequest
from datetime import datetime, timedelta
from dateutil import parser
from dateutil import rrule
from dateutil.relativedelta import relativedelta
from openerp import api
from openerp import tools, SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
from openerp.http import request
from operator import itemgetter
from openerp.exceptions import UserError

import openerp.addons.cheques_de_terceros

# Add a new floats fields and date object cheques.de.terceros
class account_move_line(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'account.move.line'
    _name = 'account.move.line'
    _description = 'account.move.line'

    _columns = {
        'liquidacion_id': fields.many2one('subcuenta', 'Subcuenta'),
#		'tasa_fija_descuento': fields.float('% Fija', compute="_calcular_descuento_tasas"),
    }

 #   @api.one
 #   @api.depends('importe', 'tasa_fija_descuento')
 #   def _calcular_descuento_fijo(self):
 #   	self.monto_fijo_descuento = self.importe * (self.tasa_fija_descuento / 100)



class subcuenta(osv.Model):
    _name = 'subcuenta'
    _description = 'subcuenta'
    _rec_name = 'id'
    _columns =  {
        'name': fields.integer('Nombre subcuenta'),
        'active': fields.boolean('Activa'),
        'cuenta_corriente': fields.boolean('Cuenta Corriente'),
        'cliente_id': fields.many2one('res.partner', 'Cliente'),
        'apuntes_ids': fields.one2many('account.move.line', 'subcuenta_id', 'Apuntes', ondelete='cascade'),
        #'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada'), ('cancelada', 'Cancelada')], string='Status', readonly=True, track_visibility='onchange'),
    }
    @api.one
    @api.depends('name')
    def _escribir_nombre_cuenta(self):
        name_prefijo = self.cliente_id.name + "_" + self.create_date + self.name
        self.name = name_prefijo


    _defaults = {
#		'fecha_liquidacion': lambda *a: time.strftime('%Y-%m-%d'),
    	'active': True,
    }
    _sql_constraints = [
    ]
