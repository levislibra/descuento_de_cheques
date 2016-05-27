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
from openerp.exceptions import ValidationError
import logging
from openerp.osv import orm

import openerp.addons.cheques_de_terceros
_logger = logging.getLogger(__name__)
#       _logger.error("date now : %r", date_now)


# Add a new floats fields and date object cheques.de.terceros
class cheques_de_terceros(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'
    _name = 'cheques.de.terceros'
    _description = 'opciones extras de cheques para calculo del descuento'

    _columns = {
        'liquidacion_id': fields.many2one('descuento.de.cheques', 'Liquidacion id'),
		'tasa_fija_descuento': fields.float('% Fija', compute="_calcular_descuento_tasas"),
		'monto_fijo_descuento': fields.float(string='Gasto', compute='_calcular_descuento_fijo', readonly=True, store=True),
        'tasa_mensual_descuento': fields.float('% Mensual', compute="_calcular_descuento_tasas"),
        'monto_mensual_descuento': fields.float(string='Interes', compute='_calcular_descuento_mensual', readonly=True, store=True),
        'fecha_acreditacion_descuento': fields.date('Acreditacion', compute='_calcular_fecha_acreditacion'),
        'monto_neto_descuento': fields.float(string='Neto', compute='_calcular_descuento_neto', readonly=True, store=True),
        'dias_descuento': fields.integer(string='Dias', compute='_calcular_descuento_dias', readonly=True, store=True),
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

    #Ojo -- actualizar bien esta funcion.
    @api.one
    @api.depends('name')
    def _calcular_descuento_tasas(self):
        if self.liquidacion_id is not None and self.liquidacion_id.cliente_id is not None:
            self.tasa_fija_descuento = self.liquidacion_id.cliente_id.tasa_fija_recomendada
            self.tasa_mensual_descuento = self.liquidacion_id.cliente_id.tasa_mensual_recomendada

    @api.one
    @api.depends('fecha_vencimiento')
    def _calcular_fecha_acreditacion(self):
        self.fecha_acreditacion_descuento = self.fecha_vencimiento


    @api.one
    @api.depends('monto_fijo_descuento', 'monto_mensual_descuento')
    def _calcular_descuento_neto(self):
    	self.monto_neto_descuento = self.importe - self.monto_fijo_descuento - self.monto_mensual_descuento



# Add a new floats fields object res.partner
class res_partner(osv.Model):
    # This OpenERP object inherits from res.partner
    # to add a new textual field
    _inherit = 'res.partner'

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
        'fecha_liquidacion': fields.date('Fecha', required=True),
        'active': fields.boolean('Activa'),
        'cliente_id': fields.many2one('res.partner', 'Cliente', required=True),
        'cliente_subcuenta_id': fields.many2one('subcuenta', 'Subcuenta' , required=True),
        'cheques_ids': fields.one2many('cheques.de.terceros', 'liquidacion_id', 'Cheques', ondelete='cascade'),
        'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada'), ('cancelada', 'Cancelada')], string='Status', readonly=True, track_visibility='onchange'),

        'cliente_id_subcuenta_ids':fields.one2many('subcuenta', 'subcuenta_id', 'Subcuentas', compute="_calcular_cliente_subcuenta_ids", readonly=True),
        'bruto_liquidacion': fields.float(string='Bruto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_liquidacion': fields.float(string='Gasto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'interes_liquidacion': fields.float(string='Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_interes_liquidacion': fields.float(string='Gasto + Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'neto_liquidacion': fields.float(string='Neto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
    }

    @api.one
    @api.constrains('cliente_subcuenta_id')
    def _check_description(self):
        _logger.error("control 1 : %r", self.cliente_subcuenta_id.subcuenta_id.id)
        _logger.error("control_ 2 : %r", self.cliente_id.id)
        if self.cliente_subcuenta_id.subcuenta_id.id != self.cliente_id.id:
            raise ValidationError("La subcuenta no pertenece al cliente")

    @api.onchange('cliente_id', 'cliente_subcuenta_id')
    def _calcular_cliente_subcuenta_ids(self):
        _logger.error("################################")
        if self.cliente_id:
            self.cliente_subcuenta_id = False
            self.cliente_id_subcuenta_ids = self.cliente_id.subcuenta_ids


    @api.one
    @api.depends('cheques_ids')
    def _calcular_montos_liquidacion(self):
        self.bruto_liquidacion = 0
        self.gasto_liquidacion = 0
        self.interes_liquidacion = 0
        self.gasto_interes_liquidacion = 0
        self.neto_liquidacion = 0
        for cheque in self.cheques_ids:
            self.bruto_liquidacion += cheque.importe
            self.gasto_liquidacion += cheque.monto_fijo_descuento
            self.interes_liquidacion += cheque.monto_mensual_descuento
            self.gasto_interes_liquidacion += cheque.monto_fijo_descuento + cheque.monto_mensual_descuento
            self.neto_liquidacion += cheque.monto_neto_descuento

    def confirmar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'confirmada'}, context=None)
        return True

    def cancelar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'cancelada'}, context=None)
        return True
    

    _defaults = {
		'fecha_liquidacion': lambda *a: time.strftime('%Y-%m-%d'),
    	'state': 'cotizacion',
    	'active': True,
    }
    _sql_constraints = [
            ('id_uniq', 'unique (id)', "El Nro de liquidacion ya existe!"),
    ]
