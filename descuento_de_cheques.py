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
class extends_cheque(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'
    _name = 'extends.cheque'
    _description = 'opciones extras de cheques para calculo del descuento'


    _columns = {
        'liquidacion_id': fields.many2one('descuento.de.cheques', 'Liquidacion id'),
		'tasa_fija_descuento': fields.float('% Fija'),
		'monto_fijo_descuento': fields.float(string='Gasto', compute='_calcular_descuento_fijo', readonly=True, store=True),
        'tasa_mensual_descuento': fields.float('% Mensual'),
        'monto_mensual_descuento': fields.float(string='Interes', compute='_calcular_descuento_mensual', readonly=True, store=True),
        'fecha_acreditacion_descuento': fields.date('Acreditacion'),
        'monto_neto_descuento': fields.float(string='Neto', compute='_calcular_descuento_neto', readonly=True, store=True),
        'dias_descuento': fields.integer(string='Dias', compute='_calcular_descuento_dias', readonly=True, store=True),
        'fecha_s': fields.char(string='Fecha_s', compute='_calcular_descuento_fijo', readonly=True, store=True),
    }
    @api.one
    @api.depends('importe', 'tasa_fija_descuento')
    def _calcular_descuento_fijo(self):
    	self.monto_fijo_descuento = self.importe * (self.tasa_fija_descuento / 100)

    @api.one
    @api.depends('importe', 'tasa_mensual_descuento', 'dias_descuento')
    def _calcular_descuento_mensual(self):
    	self.monto_mensual_descuento = self.dias_descuento * ((self.tasa_mensual_descuento / 30) / 100) * self.importe

    @api.one
    @api.depends('liquidacion_id.fecha_liquidacion', 'fecha_acreditacion_descuento')
    def _calcular_descuento_dias(self):
    	fecha_inicial_str = str(self.liquidacion_id.fecha_liquidacion)
    	fecha_final_str = str(self.fecha_acreditacion_descuento)
    	if fecha_inicial_str and len(fecha_inicial_str) > 0 and fecha_inicial_str != "False":
    		if fecha_final_str and len(fecha_final_str) > 0 and fecha_final_str  != "False":
    			formato_fecha = "%Y-%m-%d"
	    		fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
	    		fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
	    		diferencia = fecha_final - fecha_inicial
	    		if diferencia.days > 0:
	    			self.dias_descuento = diferencia.days
	    		else:
	    			self.dias_descuento = 0


    @api.one
    @api.depends('monto_fijo_descuento', 'monto_mensual_descuento')
    def _calcular_descuento_neto(self):
    	self.monto_neto_descuento = self.importe - self.monto_fijo_descuento - self.monto_mensual_descuento



# Add a new floats fields object res.partner
class res_partner_add_fields(osv.Model):
    # This OpenERP object inherits from res.partner
    # to add a new textual field
    _inherit = 'res.partner'
    #'res.partner'

    _columns = {
        'tasa_fija_recomendada' : fields.float('Tasa Fija Recomendada'),
        'tasa_mensual_recomendada' : fields.float('Tasa Mensual Recomendada'),
    }


class descuento_de_cheques(osv.Model):
    _name = 'descuento.de.cheques'
    _description = 'liquidacion de cheques'
    _rec_name = 'id'
    _columns =  {
        'id': fields.integer('Nro liquidacion'),
        'fecha_liquidacion': fields.date('Fecha liquidacion', required=True),
        'active': fields.boolean('Activa', help="Cancelar liquidacion luego de validarla"),
        'cliente_id': fields.many2one('res.partner', 'Cliente'),
        'cheques_ids': fields.one2many('extends.cheque', 'liquidacion_id', 'Cheques', ondelete='cascade'),


        'name': fields.char("Numero del cheque", size=8),
        'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada')], string='Status', readonly=True, track_visibility='onchange'),
    }
    _defaults = {
		'fecha_liquidacion': lambda *a: time.strftime('%Y-%m-%d'),
    	'state': 'cotizacion',
    	'active': True,

    }
    _sql_constraints = [
            ('id_uniq', 'unique (id)', "El Nro de liquidacion ya existe!"),
    ]
